"""PX4 ULog files: plan -> fetch to landing -> parse to bronze at 1 Hz -> purge old raw files (D-004)."""

from __future__ import annotations

import logging
import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from pyiceberg.catalog.rest import RestCatalog
from pyulog import ULog

from drone_ingest import audit, catalog as cat, storage
from drone_ingest.config import Settings
from drone_ingest.http import request
from drone_ingest.index import safe_id

log = logging.getLogger(__name__)

ULOG_PREFIX = "px4/ulog/"
CDN = "https://cdn.logs.px4.io"

# topic -> {ulog field: bronze column}; continuous values are averaged per second
MEAN_FIELDS = {
    "vehicle_global_position": {"lat": "lat", "lon": "lon", "alt": "alt_m"},
    "vehicle_local_position": {"vx": "vx", "vy": "vy", "vz": "vz"},
    "battery_status": {"remaining": "battery_remaining", "voltage_v": "battery_voltage_v",
                       "current_a": "battery_current_a"},
}
# states keep the last value of each second
LAST_FIELDS = {"vehicle_status": {"nav_state": "nav_state", "arming_state": "arming_state"}}
GPS_TOPICS = ("vehicle_gps_position", "sensor_gps")
TELEMETRY_COLUMNS = ["t_boot_s", "ts_utc", "lat", "lon", "alt_m", "vx", "vy", "vz", "battery_remaining",
                     "battery_voltage_v", "battery_current_a", "nav_state", "arming_state"]


class DiskGuardError(RuntimeError):
    """Downloading this batch would leave less free disk than MIN_FREE_DISK_GB."""


def landing_key(log_date: date | str, log_id: str) -> str:
    return f"{ULOG_PREFIX}log_date={log_date}/{log_id}.ulg"


# --- pure functions (unit-tested) -------------------------------------------------------------

def check_disk(free_bytes: int, needed_bytes: int, min_free_gb: float) -> None:
    left = free_bytes - needed_bytes
    if left < min_free_gb * 1e9:
        raise DiskGuardError(f"batch needs {needed_bytes / 1e9:.2f} GB, {free_bytes / 1e9:.2f} GB free: would leave "
                             f"{left / 1e9:.2f} GB < MIN_FREE_DISK_GB={min_free_gb}")


def size_ok(path: Path, expected_bytes: int) -> bool:
    """pyulog parses truncated files without error, so the download size is the only check."""
    return path.stat().st_size == expected_bytes


def classify_parse_error(exc: Exception) -> str:
    return "invalid_ulog_header" if "header" in str(exc).lower() else "parse_error"


def _utc_offset_us(ulog: ULog) -> int | None:
    """Boot clock -> UTC offset from GPS time, or None without a GPS fix."""
    for topic in GPS_TOPICS:
        for d in ulog.data_list:
            if d.name == topic and "time_utc_usec" in d.data:
                utc, boot = d.data["time_utc_usec"].astype(np.int64), d.data["timestamp"].astype(np.int64)
                ok = utc > 0
                if ok.any():
                    return int(np.median(utc[ok] - boot[ok]))
    return None


def _topic_frame(ulog: ULog, topic: str, fields: dict[str, str]) -> pd.DataFrame | None:
    d = next((d for d in ulog.data_list if d.name == topic and d.multi_id == 0), None)
    if d is None or len(d.data["timestamp"]) == 0:
        return None
    cols = {col: d.data[f] for f, col in fields.items() if f in d.data}
    if not cols:
        return None
    df = pd.DataFrame(cols)
    df["t_boot_s"] = (d.data["timestamp"] // 1_000_000).astype(np.int64)
    return df


def parse_ulog(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """One ULog -> (telemetry at 1 Hz, logged messages). Missing topics become null columns."""
    ulog = ULog(str(path), message_name_filter_list=[*MEAN_FIELDS, *LAST_FIELDS, *GPS_TOPICS])
    offset = _utc_offset_us(ulog)

    def to_utc(boot_us: pd.Series) -> pd.Series:
        if offset is None:
            return pd.Series(pd.NaT, index=boot_us.index, dtype="datetime64[us, UTC]")
        return pd.to_datetime(boot_us.astype(np.int64) + offset, unit="us", utc=True)

    frames = []
    for topic, fields in MEAN_FIELDS.items():
        if (df := _topic_frame(ulog, topic, fields)) is not None:
            frames.append(df.groupby("t_boot_s").mean())
    for topic, fields in LAST_FIELDS.items():
        if (df := _topic_frame(ulog, topic, fields)) is not None:
            frames.append(df.groupby("t_boot_s").last())
    telemetry = pd.concat(frames, axis=1).sort_index().reset_index() if frames else pd.DataFrame({"t_boot_s": []})
    for col in TELEMETRY_COLUMNS:
        if col not in telemetry:
            telemetry[col] = np.nan
    for col in ("nav_state", "arming_state"):
        telemetry[col] = telemetry[col].astype("Int32")
    telemetry["t_boot_s"] = telemetry["t_boot_s"].astype(np.int64)
    telemetry["ts_utc"] = to_utc(telemetry["t_boot_s"] * 1_000_000)
    telemetry = telemetry[TELEMETRY_COLUMNS]

    msgs = list(ulog.logged_messages)
    for tagged in getattr(ulog, "logged_messages_tagged", {}).values():
        msgs += tagged
    messages = pd.DataFrame({
        "t_boot_s": [m.timestamp / 1e6 for m in msgs],
        "level": [m.log_level_str() for m in msgs],
        "message": [m.message.strip() for m in msgs],
    })
    messages["ts_utc"] = to_utc((messages["t_boot_s"] * 1e6).round()) if len(messages) else pd.Series(dtype="datetime64[us, UTC]")
    return telemetry, messages.sort_values("t_boot_s", ignore_index=True)


# --- plan ---------------------------------------------------------------------------------------

def plan_ulogs(settings: Settings, catalog: RestCatalog, start: date | None = None, end: date | None = None) -> list[dict]:
    """Log ids uploaded in [start, end) that are not parsed/rejected yet. Returns plain dicts."""
    start, end = start or settings.ulog_start_date, end or settings.ulog_end_date
    rows = cat.scan(catalog, "bronze.logs_index_raw", ("log_id", "log_date"),
                    f"log_date >= '{start}' and log_date < '{end}'")
    status = audit.ulog_status(catalog)
    todo = sorted({(d.isoformat(), i) for i, d in zip(rows["log_id"].to_pylist(), rows["log_date"].to_pylist())
                   if status.get(i) not in audit.TERMINAL})
    if settings.max_ulogs_per_run is not None:
        todo = todo[:settings.max_ulogs_per_run]
    return [{"log_id": i, "log_date": d, "status": status.get(i, "new")} for d, i in todo]


def batches(entries: list[dict], size: int) -> list[list[dict]]:
    return [entries[i:i + size] for i in range(0, len(entries), size)]


# --- fetch --------------------------------------------------------------------------------------

@dataclass
class Event:
    log_id: str
    log_date: str
    status: str
    reason: str | None = None
    bytes: int | None = None
    sha256: str | None = None
    landing_key: str | None = None
    telemetry_rows: int | None = None
    message_rows: int | None = None

    def row(self, run_id: str) -> dict:
        return {**self.__dict__, "log_date": date.fromisoformat(self.log_date), "run_id": run_id, "event_at": audit.now()}


def _download_one(settings: Settings, s3, entry: dict, size: int, work: Path) -> Event:
    log_id, log_date = entry["log_id"], entry["log_date"]
    dest = work / f"{log_id}.ulg"
    for attempt in (1, 2):  # one retry for a cut-off download
        resp = request(f"{CDN}/{log_id}.ulg", dest=dest, timeout=600)
        if resp.status == 404:
            return Event(log_id, log_date, "rejected", "not_found")
        if size_ok(dest, size):
            break
        log.warning("%s: got %d bytes, expected %d (attempt %d)", log_id, dest.stat().st_size, size, attempt)
    else:
        dest.unlink(missing_ok=True)
        return Event(log_id, log_date, "failed", "size_mismatch", bytes=size)
    key = landing_key(log_date, log_id)
    storage.put_file(s3, settings.landing_bucket, key, dest, metadata={"sha256": resp.sha256 or ""})
    dest.unlink()
    return Event(log_id, log_date, "downloaded", bytes=size, sha256=resp.sha256, landing_key=key)


def fetch_ulogs(settings: Settings, catalog: RestCatalog, entries: list[dict], run_id: str) -> dict:
    """Download a batch from the CDN into landing. Already-landed files are skipped."""
    started = audit.now()
    s3 = storage.s3_client(settings)
    work = Path(settings.work_dir) / safe_id(run_id) / "ulog"
    work.mkdir(parents=True, exist_ok=True)
    status = audit.ulog_status(catalog)  # current status, not the (possibly stale) one in the plan
    events: list[Event] = []
    to_download: list[tuple[dict, int]] = []
    skipped = 0
    for e in entries:
        if status.get(e["log_id"]) in audit.TERMINAL | {"downloaded"}:
            skipped += 1
            continue
        key = landing_key(e["log_date"], e["log_id"])
        if (meta := storage.head(s3, settings.landing_bucket, key)) is not None:
            # landed by an earlier run whose audit write failed: record it, don't download again
            events.append(Event(e["log_id"], e["log_date"], "downloaded", "already_in_landing",
                                bytes=meta["ContentLength"], landing_key=key))
            continue
        head = request(f"{CDN}/{e['log_id']}.ulg", method="HEAD", timeout=60)
        if head.status == 404:
            events.append(Event(e["log_id"], e["log_date"], "rejected", "not_found"))
            continue
        size = int(head.headers.get("content-length", 0))
        if size > settings.ulog_max_bytes:
            events.append(Event(e["log_id"], e["log_date"], "rejected", "too_large", bytes=size))
            continue
        to_download.append((e, size))

    needed = sum(size for _, size in to_download)
    check_disk(shutil.disk_usage(settings.disk_guard_path).free, needed, settings.min_free_disk_gb)
    log.info("fetching %d ULogs (%.1f MB); %d already handled", len(to_download), needed / 1e6, skipped)
    with ThreadPoolExecutor(max_workers=settings.ulog_concurrency) as pool:
        events += list(pool.map(lambda es: _download_one(settings, s3, es[0], es[1], work), to_download))

    cat.append(catalog, "audit.ulog_downloads", [ev.row(run_id) for ev in events])
    counts = {s: sum(1 for ev in events if ev.status == s) for s in ("downloaded", "rejected", "failed")}
    audit.record_run(catalog, "ulog_fetch", run_id, "success", started, read=len(entries),
                     inserted=counts["downloaded"], rejected=counts["rejected"] + counts["failed"],
                     bytes=sum(ev.bytes or 0 for ev in events if ev.status == "downloaded"))
    return {"entries": len(entries), "skipped": skipped, **counts, "bytes": needed}


# --- parse --------------------------------------------------------------------------------------

def parse_ulogs(settings: Settings, catalog: RestCatalog, entries: list[dict], run_id: str) -> dict:
    """Parse landed ULogs of a batch into bronze.telemetry_raw + bronze.log_messages_raw."""
    started = audit.now()
    s3 = storage.s3_client(settings)
    status = audit.ulog_status(catalog)
    work = Path(settings.work_dir) / safe_id(run_id) / "parse"
    work.mkdir(parents=True, exist_ok=True)
    tel_frames, msg_frames, events = [], [], []
    ingested_at = audit.now()
    for e in entries:
        log_id, log_date = e["log_id"], e["log_date"]
        if status.get(log_id) != "downloaded":
            continue
        key = landing_key(log_date, log_id)
        local = work / f"{log_id}.ulg"
        storage.get_file(s3, settings.landing_bucket, key, local)
        try:
            telemetry, messages = parse_ulog(local)
        except Exception as exc:  # a broken file must not stop the batch
            events.append(Event(log_id, log_date, "rejected", classify_parse_error(exc)))
            log.warning("%s: %s", log_id, exc)
            continue
        finally:
            local.unlink(missing_ok=True)
        meta = {"log_id": log_id, "_log_date": date.fromisoformat(log_date), "_run_id": run_id,
                "_source_file": f"s3://{settings.landing_bucket}/{key}", "_ingested_at": ingested_at}
        tel_frames.append(telemetry.assign(**meta))
        msg_frames.append(messages.assign(**meta))
        events.append(Event(log_id, log_date, "parsed", telemetry_rows=len(telemetry), message_rows=len(messages)))

    def to_arrow(name: str, frames: list[pd.DataFrame]):
        if not frames:
            return []
        df = pd.concat(frames, ignore_index=True)
        rows = df.astype(object).where(df.notna(), None).to_dict("records")
        return cat.arrow_table(name, rows)

    n_tel = cat.append(catalog, "bronze.telemetry_raw", to_arrow("bronze.telemetry_raw", tel_frames))
    n_msg = cat.append(catalog, "bronze.log_messages_raw", to_arrow("bronze.log_messages_raw", msg_frames))
    cat.append(catalog, "audit.ulog_downloads", [ev.row(run_id) for ev in events])
    parsed = sum(1 for ev in events if ev.status == "parsed")
    rejected = sum(1 for ev in events if ev.status == "rejected")
    audit.record_run(catalog, "ulog_parse", run_id, "success", started, read=len(events), inserted=parsed,
                     rejected=rejected)
    return {"parsed": parsed, "rejected": rejected, "telemetry_rows": n_tel, "message_rows": n_msg}


# --- purge --------------------------------------------------------------------------------------

def purge_ulogs(settings: Settings, today: date | None = None) -> dict:
    """Delete landed .ulg folders older than the retention window. Run BEFORE fetching (D-004)."""
    today = today or datetime.now(timezone.utc).date()
    cutoff = today - timedelta(days=settings.ulog_retention_days)
    s3 = storage.s3_client(settings)
    deleted_files = deleted_bytes = 0
    purged = []
    for prefix in storage.list_prefixes(s3, settings.landing_bucket, ULOG_PREFIX):
        day = date.fromisoformat(prefix.rstrip("/").split("log_date=")[-1])
        if day < cutoff:
            n, b = storage.delete_prefix(s3, settings.landing_bucket, prefix)
            deleted_files, deleted_bytes = deleted_files + n, deleted_bytes + b
            purged.append(day.isoformat())
    log.info("purged %d ULog days before %s: %d files, %.1f MB", len(purged), cutoff, deleted_files, deleted_bytes / 1e6)
    return {"cutoff": cutoff.isoformat(), "days": purged, "files": deleted_files, "bytes": deleted_bytes}


# --- all-in-one for one window (used by the backfill DAG, one day at a time) ----------------------

def run_ulogs(settings: Settings, catalog: RestCatalog, run_id: str, start: date, end: date,
              today: date | None = None) -> dict:
    """purge -> plan -> fetch + parse each batch -> purge. Landing never holds more than the window."""
    before = purge_ulogs(settings, today)
    entries = plan_ulogs(settings, catalog, start, end)
    totals = {"entries": len(entries), "downloaded": 0, "rejected": 0, "failed": 0, "parsed": 0,
              "telemetry_rows": 0, "message_rows": 0}
    for batch in batches(entries, settings.ulog_batch_size):
        fetched = fetch_ulogs(settings, catalog, batch, run_id)
        parsed = parse_ulogs(settings, catalog, batch, run_id)
        for k in ("downloaded", "rejected", "failed"):
            totals[k] += fetched[k]
        totals["rejected"] += parsed["rejected"]
        for k in ("parsed", "telemetry_rows", "message_rows"):
            totals[k] += parsed[k]
    after = purge_ulogs(settings, today)
    return {"window": [start.isoformat(), end.isoformat()], **totals,
            "purged_days": sorted(set(before["days"]) | set(after["days"]))}
