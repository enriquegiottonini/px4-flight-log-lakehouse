"""Audit tables: what ran, what was downloaded, and the current status of each ULog."""

from __future__ import annotations

from datetime import datetime, timezone

import pyarrow.compute as pc
from pyiceberg.catalog.rest import RestCatalog

from drone_ingest import catalog as cat
from drone_ingest.schemas import Rejection

# ULog statuses: parsed/rejected are terminal; downloaded needs parsing; failed is retried next run.
TERMINAL = {"parsed", "rejected"}


def now() -> datetime:
    return datetime.now(timezone.utc)


def record_run(catalog: RestCatalog, entity: str, run_id: str, status: str, started_at: datetime,
               source: str | None = None, **counts) -> None:
    finished = now()
    cat.append(catalog, "audit.ingestion_runs", [{
        "entity": entity, "run_id": run_id, "status": status, "source": source,
        "started_at": started_at, "finished_at": finished,
        "duration_s": (finished - started_at).total_seconds(), **counts,
    }])


def record_rejections(catalog: RestCatalog, run_id: str, rejections: list[Rejection]) -> int:
    ts = now()
    return cat.append(catalog, "bronze.rejected_records", [
        {"entity": r.entity, "log_id": r.log_id, "reason": r.reason, "detail": r.detail, "raw": r.raw,
         "_run_id": run_id, "_rejected_at": ts} for r in rejections])


def last_loaded_etag(catalog: RestCatalog) -> str | None:
    """ETag of the newest index snapshot that was fully loaded into bronze.

    Used for If-None-Match: if a download succeeded but loading failed, the ETag is not
    recorded here, so the next run downloads and loads it again.
    """
    runs = cat.scan(catalog, "audit.ingestion_runs", ("entity", "status", "source", "finished_at"),
                    "entity == 'logs_index' and status == 'success'")
    if runs.num_rows == 0:
        return None
    newest = pc.index(runs["finished_at"], pc.max(runs["finished_at"])).as_py()
    return runs["source"][newest].as_py()


def ulog_status(catalog: RestCatalog) -> dict[str, str]:
    """Current status per log_id = its most recent event."""
    events = cat.scan(catalog, "audit.ulog_downloads", ("log_id", "status", "event_at"))
    latest: dict[str, tuple[datetime, str]] = {}
    for log_id, status, ts in zip(*(events[c].to_pylist() for c in ("log_id", "status", "event_at"))):
        if log_id not in latest or ts >= latest[log_id][0]:
            latest[log_id] = (ts, status)
    return {k: v[1] for k, v in latest.items()}
