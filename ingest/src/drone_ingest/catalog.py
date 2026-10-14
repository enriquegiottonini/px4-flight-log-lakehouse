"""Iceberg tables written by the ingestion (bronze + audit), through Lakekeeper's REST catalog.

PyIceberg asks Lakekeeper for vended credentials by default, so writes use short-lived STS keys
and the warehouse endpoint (http://rustfs.localhost:9000). The static keys below are a fallback.
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass

import pyarrow as pa
from pyiceberg.catalog.rest import RestCatalog
from pyiceberg.exceptions import CommitFailedException
from pyiceberg.partitioning import UNPARTITIONED_PARTITION_SPEC, PartitionField, PartitionSpec
from pyiceberg.schema import Schema
from pyiceberg.table import Table
from pyiceberg.transforms import IdentityTransform, MonthTransform
from pyiceberg.types import (DateType, DoubleType, IntegerType, LongType, NestedField, StringType,
                             TimestamptzType)

from drone_ingest.config import Settings

log = logging.getLogger(__name__)


def get_catalog(settings: Settings) -> RestCatalog:
    return RestCatalog("px4", **{
        "uri": settings.catalog_uri,
        "warehouse": settings.warehouse,
        "s3.endpoint": settings.s3_endpoint,
        "s3.access-key-id": settings.s3_access_key,
        "s3.secret-access-key": settings.s3_secret_key,
        "s3.region": settings.s3_region,
        "s3.path-style-access": "true",
    })


def _schema(*fields: tuple[str, object]) -> Schema:
    # All columns optional: bronze keeps whatever arrived; silver enforces quality.
    return Schema(*[NestedField(i, name, typ, required=False) for i, (name, typ) in enumerate(fields, start=1)])


@dataclass(frozen=True)
class TableDef:
    schema: Schema
    partition_spec: PartitionSpec = UNPARTITIONED_PARTITION_SPEC


def _partition(schema: Schema, column: str, transform, name: str) -> PartitionSpec:
    return PartitionSpec(PartitionField(source_id=schema.find_field(column).field_id, field_id=1000,
                                        transform=transform, name=name))


_logs_index = _schema(
    ("log_id", StringType()), ("log_date", DateType()), ("payload", StringType()), ("payload_hash", StringType()),
    ("_change_type", StringType()), ("_snapshot_etag", StringType()), ("_run_id", StringType()),
    ("_source_file", StringType()), ("_ingested_at", TimestamptzType()),
)
_telemetry = _schema(
    ("log_id", StringType()), ("t_boot_s", LongType()), ("ts_utc", TimestamptzType()),
    ("lat", DoubleType()), ("lon", DoubleType()), ("alt_m", DoubleType()),
    ("vx", DoubleType()), ("vy", DoubleType()), ("vz", DoubleType()),
    ("battery_remaining", DoubleType()), ("battery_voltage_v", DoubleType()), ("battery_current_a", DoubleType()),
    ("nav_state", IntegerType()), ("arming_state", IntegerType()),
    ("_log_date", DateType()), ("_run_id", StringType()), ("_source_file", StringType()), ("_ingested_at", TimestamptzType()),
)
_messages = _schema(
    ("log_id", StringType()), ("t_boot_s", DoubleType()), ("ts_utc", TimestamptzType()),
    ("level", StringType()), ("message", StringType()),
    ("_log_date", DateType()), ("_run_id", StringType()), ("_source_file", StringType()), ("_ingested_at", TimestamptzType()),
)
_rejected = _schema(
    ("entity", StringType()), ("log_id", StringType()), ("reason", StringType()), ("detail", StringType()),
    ("raw", StringType()), ("_run_id", StringType()), ("_rejected_at", TimestamptzType()),
)
_index_snapshots = _schema(
    ("etag", StringType()), ("last_modified", StringType()), ("bytes", LongType()), ("records", LongType()),
    ("sha256", StringType()), ("landing_key", StringType()), ("run_id", StringType()), ("fetched_at", TimestamptzType()),
)
_ingestion_runs = _schema(
    ("entity", StringType()), ("run_id", StringType()), ("status", StringType()), ("source", StringType()),
    ("read", LongType()), ("inserted", LongType()), ("updated", LongType()), ("rejected", LongType()),
    ("bytes", LongType()), ("duration_s", DoubleType()), ("started_at", TimestamptzType()),
    ("finished_at", TimestamptzType()),
)
_ulog_downloads = _schema(  # append-only event log; latest event per log_id = current status
    ("log_id", StringType()), ("log_date", DateType()), ("status", StringType()), ("reason", StringType()),
    ("bytes", LongType()), ("sha256", StringType()), ("landing_key", StringType()),
    ("telemetry_rows", LongType()), ("message_rows", LongType()), ("run_id", StringType()), ("event_at", TimestamptzType()),
)

TABLES: dict[str, TableDef] = {
    "bronze.logs_index_raw": TableDef(_logs_index, _partition(_logs_index, "log_date", MonthTransform(), "log_date_month")),
    "bronze.telemetry_raw": TableDef(_telemetry, _partition(_telemetry, "_log_date", IdentityTransform(), "_log_date")),
    "bronze.log_messages_raw": TableDef(_messages, _partition(_messages, "_log_date", IdentityTransform(), "_log_date")),
    "bronze.rejected_records": TableDef(_rejected),
    "audit.index_snapshots": TableDef(_index_snapshots),
    "audit.ingestion_runs": TableDef(_ingestion_runs),
    "audit.ulog_downloads": TableDef(_ulog_downloads),
}


def ensure_tables(catalog: RestCatalog) -> list[str]:
    """Create any missing table (idempotent). Namespaces come from trino-init (Phase 3)."""
    created = []
    existing = {".".join(t) for ns in ("bronze", "audit") for t in catalog.list_tables(ns)}
    for name, tdef in TABLES.items():
        if name not in existing:
            catalog.create_table(name, schema=tdef.schema, partition_spec=tdef.partition_spec,
                                 properties={"write.parquet.compression-codec": "zstd"})
            created.append(name)
    return created


def arrow_table(name: str, rows: list[dict]) -> pa.Table:
    """Rows -> Arrow table with exactly the Iceberg schema (missing keys become nulls)."""
    return pa.Table.from_pylist(rows, schema=TABLES[name].schema.as_arrow())


def append(catalog: RestCatalog, name: str, rows: list[dict] | pa.Table, attempts: int = 6) -> int:
    """Append rows, retrying on commit conflicts (parallel Airflow tasks write the same tables)."""
    data = rows if isinstance(rows, pa.Table) else arrow_table(name, rows)
    if data.num_rows == 0:
        return 0
    for attempt in range(1, attempts + 1):
        table: Table = catalog.load_table(name)
        try:
            table.append(data)
            return data.num_rows
        except CommitFailedException:
            if attempt == attempts:
                raise
            wait = random.uniform(0.5, 1.5) * attempt
            log.warning("commit conflict on %s; retry %d/%d in %.1fs", name, attempt, attempts - 1, wait)
            time.sleep(wait)
    return 0


def scan(catalog: RestCatalog, name: str, columns: tuple[str, ...], row_filter: str | None = None) -> pa.Table:
    table = catalog.load_table(name)
    return table.scan(selected_fields=columns, **({"row_filter": row_filter} if row_filter else {})).to_arrow()
