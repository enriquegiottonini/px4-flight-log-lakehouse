"""Settings from environment variables.

On the host, the repo-root .env is loaded automatically, so `uv run drone-ingest ...` talks to the
compose stack through its published ports (localhost:9000, localhost:8181). Inside containers
(Phase 5), set S3_ENDPOINT / CATALOG_URI to the internal names (http://rustfs:9000, ...).
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache

from dotenv import find_dotenv, load_dotenv


def _get(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or default


def _required(name: str) -> str:
    value = _get(name)
    if value is None:
        raise RuntimeError(f"environment variable {name} is required (see .env.example)")
    return value


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


@dataclass(frozen=True)
class Settings:
    # services
    s3_endpoint: str
    s3_access_key: str
    s3_secret_key: str
    s3_region: str
    catalog_uri: str
    warehouse: str
    landing_bucket: str
    # PX4 index
    index_url: str
    index_start_date: date            # bronze ignores records uploaded before this date
    index_snapshot_retention: int     # raw index snapshots kept in landing
    # PX4 ULogs (D-004): one full UTC day of uploads, [start, end)
    ulog_start_date: date
    ulog_end_date: date
    ulog_retention_days: int          # raw .ulg kept in landing
    ulog_max_bytes: int               # bigger logs are rejected as too_large
    max_ulogs_per_run: int | None     # None = all (cap only for development)
    ulog_batch_size: int
    ulog_concurrency: int
    min_free_disk_gb: float           # fetch aborts if a batch would leave less than this
    disk_guard_path: str              # filesystem whose free space the guard checks
    work_dir: str                     # temp files (downloads before upload, parse inputs)


@lru_cache
def get_settings() -> Settings:
    load_dotenv(find_dotenv(usecwd=True), override=False)
    today = utc_today()
    max_ulogs = _get("MAX_ULOGS_PER_RUN")
    return Settings(
        s3_endpoint=_get("S3_ENDPOINT", "http://localhost:9000"),
        s3_access_key=_required("S3_ACCESS_KEY"),
        s3_secret_key=_required("S3_SECRET_KEY"),
        s3_region=_get("S3_REGION", "us-east-1"),
        catalog_uri=_get("CATALOG_URI", "http://localhost:8181/catalog"),
        warehouse=_get("WAREHOUSE", "px4"),
        landing_bucket=_get("LANDING_BUCKET", "landing"),
        index_url=_get("INDEX_URL", "https://review.px4.io/dbinfo"),
        index_start_date=date.fromisoformat(_get("INDEX_START_DATE", "2025-01-01")),
        index_snapshot_retention=int(_get("INDEX_SNAPSHOT_RETENTION", "7")),
        ulog_start_date=date.fromisoformat(_get("ULOG_START_DATE", (today - timedelta(days=1)).isoformat())),
        ulog_end_date=date.fromisoformat(_get("ULOG_END_DATE", today.isoformat())),
        ulog_retention_days=int(_get("ULOG_RETENTION_DAYS", "1")),
        ulog_max_bytes=int(_get("ULOG_MAX_BYTES", "300000000")),
        max_ulogs_per_run=int(max_ulogs) if max_ulogs else None,
        ulog_batch_size=int(_get("ULOG_BATCH_SIZE", "50")),
        ulog_concurrency=int(_get("ULOG_CONCURRENCY", "4")),
        min_free_disk_gb=float(_get("MIN_FREE_DISK_GB", "3")),
        disk_guard_path=_get("DISK_GUARD_PATH", tempfile.gettempdir()),
        work_dir=_get("WORK_DIR", os.path.join(tempfile.gettempdir(), "drone_ingest")),
    )
