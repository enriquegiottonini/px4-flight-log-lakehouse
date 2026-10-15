"""PX4 log index: snapshot to landing (conditional GET) and diff-load into bronze (D-003)."""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import re
import zlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import ijson
from pyiceberg.catalog.rest import RestCatalog

from drone_ingest import audit, catalog as cat, storage
from drone_ingest.config import Settings
from drone_ingest.http import request
from drone_ingest.schemas import validate_record

log = logging.getLogger(__name__)

INDEX_PREFIX = "px4/index/"


class IndexFileError(RuntimeError):
    """The downloaded index is not a complete gzip JSON array: the whole snapshot is rejected."""


# --- pure functions (unit-tested) -------------------------------------------------------------

def iter_index_file(path: Path) -> Iterator:
    """Stream records from a gzip JSON array without loading the whole file (~2 GB as objects)."""
    try:
        with gzip.open(path, "rb") as f:
            # use_float: keep ints as int and floats as float (ijson defaults to Decimal), so the
            # canonical JSON and its hash match what json.load would produce
            yield from ijson.items(f, "item", use_float=True)
    except (EOFError, OSError, zlib.error, ijson.JSONError, UnicodeDecodeError) as e:
        raise IndexFileError(f"{path.name}: not a complete gzip JSON array ({type(e).__name__}: {e})") from e


def read_index_file(path: Path) -> list:
    return list(iter_index_file(path))


def count_index_file(path: Path) -> int:
    """Integrity check of a downloaded snapshot: parse it fully, keep nothing."""
    return sum(1 for _ in iter_index_file(path))


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


def classify(rec: dict, latest_hash: dict[str, str], start_date: date) -> tuple[str, dict | None]:
    """One valid record -> ('out_of_window' | 'unchanged' | 'insert' | 'update', bronze row or None)."""
    log_date = date.fromisoformat(rec["log_date"])
    if log_date < start_date:
        return "out_of_window", None
    canon = canonical_json(rec)
    h = payload_hash(canon)
    prev = latest_hash.get(rec["log_id"])
    if prev == h:
        return "unchanged", None
    kind = "insert" if prev is None else "update"
    return kind, {"log_id": rec["log_id"], "log_date": log_date, "payload": canon, "payload_hash": h,
                  "_change_type": kind}


def diff_records(valid: list[dict], latest_hash: dict[str, str], start_date: date) -> Diff:
    """Compare a snapshot's valid records with bronze's latest hash per log_id."""
    diff = Diff()
    for rec in valid:
        _add(diff, *classify(rec, latest_hash, start_date))
    return diff


def _add(diff: Diff, kind: str, row: dict | None) -> None:
    if kind == "insert":
        diff.inserts.append(row)
    elif kind == "update":
        diff.updates.append(row)
    elif kind == "unchanged":
        diff.unchanged += 1
    else:
        diff.out_of_window += 1


# --- I/O --------------------------------------------------------------------------------------

def _latest_hashes(catalog: RestCatalog) -> dict[str, str]:
    rows = cat.scan(catalog, "bronze.logs_index_raw", ("log_id", "payload_hash", "_ingested_at"))
    latest: dict[str, tuple[datetime, str]] = {}
    for log_id, h, ts in zip(*(rows[c].to_pylist() for c in ("log_id", "payload_hash", "_ingested_at"))):
        if log_id not in latest or ts >= latest[log_id][0]:
            latest[log_id] = (ts, h)
    return {k: v[1] for k, v in latest.items()}


def safe_id(run_id: str) -> str:
    """Airflow run ids contain ':' and '+'; keep paths and S3 keys plain."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", run_id)


def snapshot_index(settings: Settings, catalog: RestCatalog, run_id: str) -> dict:
    """Conditional GET of the index; on 200 land the raw gz + manifest. Returns a summary dict."""
    started = audit.now()
    etag = audit.last_loaded_etag(catalog)
    work = Path(settings.work_dir) / safe_id(run_id)
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

    n_records = count_index_file(dest)  # streams; raises IndexFileError on a truncated/corrupt download
    snapshot_date = started.date().isoformat()
    folder = f"{INDEX_PREFIX}snapshot_date={snapshot_date}/run_id={safe_id(run_id)}/"
    manifest = {
        "etag": resp.headers.get("etag"), "last_modified": resp.headers.get("last-modified"),
        "bytes": resp.bytes_written, "records": n_records, "sha256": resp.sha256,
        "source_url": settings.index_url, "fetched_at": audit.now().isoformat(), "run_id": run_id,
    }
    s3 = storage.s3_client(settings)
    storage.put_file(s3, settings.landing_bucket, folder + "dbinfo.json.gz", dest)
    # The manifest goes last: a folder without it is an incomplete run (DESIGN_PROPOSAL, Ingesta)
    storage.put_bytes(s3, settings.landing_bucket, folder + "_manifest.json", json.dumps(manifest, indent=1).encode())
    dest.unlink()  # old snapshots expire by themselves: RustFS lifecycle rule on px4/index/ (setup.py)

    audit.record_run(catalog, "index_snapshot", run_id, "success", started, source=manifest["etag"],
                     read=n_records, bytes=resp.bytes_written)
    log.info("200: %d records, %.1f MB -> s3://%s/%s",
             n_records, resp.bytes_written / 1e6, settings.landing_bucket, folder)
    return {"status": "downloaded", "etag": manifest["etag"], "records": n_records,
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
    work = Path(settings.work_dir) / safe_id(run_id)
    work.mkdir(parents=True, exist_ok=True)
    local = work / "dbinfo.json.gz"
    storage.get_file(s3, settings.landing_bucket, data_key, local)
    if hashlib.sha256(local.read_bytes()).hexdigest() != manifest["sha256"]:
        raise IndexFileError(f"{data_key}: sha256 does not match its manifest")

    latest_hash = _latest_hashes(catalog)
    diff, rejected, seen, n_read = Diff(), [], set(), 0
    for rec in iter_index_file(local):  # one record at a time: validate -> window -> hash -> diff
        n_read += 1
        if (rejection := validate_record(rec, seen)) is not None:
            rejected.append(rejection)
            continue
        _add(diff, *classify(rec, latest_hash, settings.index_start_date))
    local.unlink()
    ingested_at = audit.now()
    rows = [{**r, "_snapshot_etag": manifest["etag"], "_run_id": run_id,
             "_source_file": f"s3://{settings.landing_bucket}/{data_key}", "_ingested_at": ingested_at}
            for r in diff.inserts + diff.updates]
    cat.append(catalog, "bronze.logs_index_raw", rows)
    audit.record_rejections(catalog, run_id, rejected)
    audit.record_run(catalog, "logs_index", run_id, "success", started, source=manifest["etag"], read=n_read,
                     inserted=len(diff.inserts), updated=len(diff.updates), rejected=len(rejected))
    summary = {"etag": manifest["etag"], "read": n_read, "inserted": len(diff.inserts),
               "updated": len(diff.updates), "unchanged": diff.unchanged,
               "out_of_window": diff.out_of_window, "rejected": len(rejected)}
    log.info("loaded index: %s", summary)
    return summary
