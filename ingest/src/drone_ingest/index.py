"""PX4 log index: snapshot to landing (conditional GET) and diff-load into bronze (D-003)."""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import zlib
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from pyiceberg.catalog.rest import RestCatalog

from drone_ingest import audit, catalog as cat, storage
from drone_ingest.config import Settings
from drone_ingest.http import request
from drone_ingest.schemas import validate_records

log = logging.getLogger(__name__)

INDEX_PREFIX = "px4/index/"


class IndexFileError(RuntimeError):
    """The downloaded index is not a complete gzip JSON array: the whole snapshot is rejected."""


# --- pure functions (unit-tested) -------------------------------------------------------------

def read_index_file(path: Path) -> list:
    try:
        with gzip.open(path, "rb") as f:
            data = json.load(f)
    except (EOFError, OSError, zlib.error, json.JSONDecodeError, UnicodeDecodeError) as e:
        raise IndexFileError(f"{path.name}: not a complete gzip JSON file ({type(e).__name__}: {e})") from e
    if not isinstance(data, list):
        raise IndexFileError(f"{path.name}: expected a JSON array, got {type(data).__name__}")
    return data


def canonical_json(record: dict) -> str:
    """Same content -> same string -> same hash, regardless of key order."""
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def payload_hash(canon: str) -> str:
    return hashlib.sha256(canon.encode()).hexdigest()


@dataclass
class Diff:
    inserts: list[dict] = field(default_factory=list)   # rows for bronze, _change_type='insert'
    updates: list[dict] = field(default_factory=list)   # rows for bronze, _change_type='update'
    unchanged: int = 0
    out_of_window: int = 0


def diff_records(valid: list[dict], latest_hash: dict[str, str], start_date: date) -> Diff:
    """Compare a snapshot's valid records with bronze's latest hash per log_id."""
    diff = Diff()
    for rec in valid:
        log_date = date.fromisoformat(rec["log_date"])
        if log_date < start_date:
            diff.out_of_window += 1
            continue
        canon = canonical_json(rec)
        h = payload_hash(canon)
        prev = latest_hash.get(rec["log_id"])
        if prev == h:
            diff.unchanged += 1
            continue
        row = {"log_id": rec["log_id"], "log_date": log_date, "payload": canon, "payload_hash": h,
               "_change_type": "insert" if prev is None else "update"}
        (diff.inserts if prev is None else diff.updates).append(row)
    return diff


# --- I/O --------------------------------------------------------------------------------------

def _latest_hashes(catalog: RestCatalog) -> dict[str, str]:
    rows = cat.scan(catalog, "bronze.logs_index_raw", ("log_id", "payload_hash", "_ingested_at"))
    latest: dict[str, tuple[datetime, str]] = {}
    for log_id, h, ts in zip(*(rows[c].to_pylist() for c in ("log_id", "payload_hash", "_ingested_at"))):
        if log_id not in latest or ts >= latest[log_id][0]:
            latest[log_id] = (ts, h)
    return {k: v[1] for k, v in latest.items()}


def _prune_snapshots(s3, settings: Settings) -> int:
    """Keep only the newest N snapshot folders (snapshot_date=*/run_id=*/)."""
    keep = max(settings.index_snapshot_retention, 1)
    folders = [run for day in storage.list_prefixes(s3, settings.landing_bucket, INDEX_PREFIX)
               for run in storage.list_prefixes(s3, settings.landing_bucket, day)]
    stamped = []
    for folder in folders:
        meta = storage.head(s3, settings.landing_bucket, folder + "_manifest.json")
        stamped.append((meta["LastModified"].timestamp() if meta else 0.0, folder))  # incomplete runs sort first
    stamped.sort()
    expired = [folder for _, folder in stamped[:-keep]] if len(stamped) > keep else []
    for folder in expired:
        storage.delete_prefix(s3, settings.landing_bucket, folder)
    return len(expired)


def snapshot_index(settings: Settings, catalog: RestCatalog, run_id: str) -> dict:
    """Conditional GET of the index; on 200 land the raw gz + manifest. Returns a summary dict."""
    started = audit.now()
    etag = audit.last_loaded_etag(catalog)
    work = Path(settings.work_dir) / run_id
    work.mkdir(parents=True, exist_ok=True)
    dest = work / "dbinfo.json.gz"
    log.info("GET %s If-None-Match=%s", settings.index_url, etag or "(none)")
    resp = request(settings.index_url, headers={"If-None-Match": etag} if etag else None, dest=dest)

    if resp.status == 304:
        audit.record_run(catalog, "index_snapshot", run_id, "not_modified", started, source=etag, bytes=0)
        log.info("304 Not Modified: index unchanged since the last load")
        return {"status": "not_modified", "etag": etag}
    if resp.status != 200:
        raise RuntimeError(f"unexpected HTTP {resp.status} from {settings.index_url}")

    records = read_index_file(dest)  # raises IndexFileError on a truncated/corrupt download
    snapshot_date = started.date().isoformat()
    folder = f"{INDEX_PREFIX}snapshot_date={snapshot_date}/run_id={run_id}/"
    manifest = {
        "etag": resp.headers.get("etag"), "last_modified": resp.headers.get("last-modified"),
        "bytes": resp.bytes_written, "records": len(records), "sha256": resp.sha256,
        "source_url": settings.index_url, "fetched_at": audit.now().isoformat(), "run_id": run_id,
    }
    s3 = storage.s3_client(settings)
    storage.put_file(s3, settings.landing_bucket, folder + "dbinfo.json.gz", dest)
    # The manifest goes last: a folder without it is an incomplete run (DESIGN_PROPOSAL, Ingesta)
    storage.put_bytes(s3, settings.landing_bucket, folder + "_manifest.json", json.dumps(manifest, indent=1).encode())
    dest.unlink()
    pruned = _prune_snapshots(s3, settings)

    cat.append(catalog, "audit.index_snapshots", [{
        **{k: manifest[k] for k in ("etag", "last_modified", "bytes", "records", "sha256")},
        "landing_key": folder + "dbinfo.json.gz", "run_id": run_id, "fetched_at": audit.now()}])
    audit.record_run(catalog, "index_snapshot", run_id, "success", started, source=manifest["etag"],
                     read=len(records), bytes=resp.bytes_written)
    log.info("200: %d records, %.1f MB -> s3://%s/%s (pruned %d old snapshots)",
             len(records), resp.bytes_written / 1e6, settings.landing_bucket, folder, pruned)
    return {"status": "downloaded", "etag": manifest["etag"], "records": len(records),
            "bytes": resp.bytes_written, "manifest_key": folder + "_manifest.json"}


def latest_manifest_key(settings: Settings) -> str:
    s3 = storage.s3_client(settings)
    keys = [o for o in storage.list_keys(s3, settings.landing_bucket, INDEX_PREFIX) if o["Key"].endswith("_manifest.json")]
    if not keys:
        raise RuntimeError("no index snapshot in landing yet: run snapshot-index first")
    return max(keys, key=lambda o: o["LastModified"])["Key"]


def load_index(settings: Settings, catalog: RestCatalog, run_id: str, manifest_key: str | None = None) -> dict:
    """Validate the landed snapshot and append only new/changed records to bronze."""
    started = audit.now()
    s3 = storage.s3_client(settings)
    manifest_key = manifest_key or latest_manifest_key(settings)
    manifest = json.loads(storage.get_bytes(s3, settings.landing_bucket, manifest_key))
    data_key = manifest_key.replace("_manifest.json", "dbinfo.json.gz")
    work = Path(settings.work_dir) / run_id
    work.mkdir(parents=True, exist_ok=True)
    local = work / "dbinfo.json.gz"
    storage.get_file(s3, settings.landing_bucket, data_key, local)
    if hashlib.sha256(local.read_bytes()).hexdigest() != manifest["sha256"]:
        raise IndexFileError(f"{data_key}: sha256 does not match its manifest")

    records = read_index_file(local)
    local.unlink()
    valid, rejected = validate_records(records)
    diff = diff_records(valid, _latest_hashes(catalog), settings.index_start_date)
    ingested_at = audit.now()
    rows = [{**r, "_snapshot_etag": manifest["etag"], "_run_id": run_id,
             "_source_file": f"s3://{settings.landing_bucket}/{data_key}", "_ingested_at": ingested_at}
            for r in diff.inserts + diff.updates]
    cat.append(catalog, "bronze.logs_index_raw", rows)
    audit.record_rejections(catalog, run_id, rejected)
    audit.record_run(catalog, "logs_index", run_id, "success", started, source=manifest["etag"], read=len(records),
                     inserted=len(diff.inserts), updated=len(diff.updates), rejected=len(rejected))
    summary = {"etag": manifest["etag"], "read": len(records), "inserted": len(diff.inserts),
               "updated": len(diff.updates), "unchanged": diff.unchanged,
               "out_of_window": diff.out_of_window, "rejected": len(rejected)}
    log.info("loaded index: %s", summary)
    return summary
