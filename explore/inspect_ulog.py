"""Download a few small ULogs and check the topics/fields bronze.telemetry_raw needs.

Picks small, real (non-SITL) logs of different vehicle classes from the HEAD
sample (run ulog_sizes.py first), or takes explicit log ids. Writes
reports/ulog_inspection.md.

    uv run python inspect_ulog.py                 # auto-pick 3
    uv run python inspect_ulog.py <log_id> ...    # specific logs
"""

import json
import sys
from pathlib import Path

import numpy as np
from pyulog import ULog

from px4http import request

HERE = Path(__file__).parent
SIZES = HERE / "data" / "ulog_sizes.json"
ULOG_DIR = HERE / "data" / "ulogs"
REPORT = HERE / "reports" / "ulog_inspection.md"

# topic -> fields we plan to keep (CLAUDE.md section 6, bronze.telemetry_raw)
WANTED = {
    "vehicle_global_position": ["lat", "lon", "alt"],
    "vehicle_local_position": ["vx", "vy", "vz", "z"],
    "battery_status": ["remaining", "voltage_v", "current_a"],
    "vehicle_status": ["nav_state", "arming_state"],
    "vehicle_air_data": ["baro_alt_meter"],
}
CLASSES = [("multirotor", {"Quadrotor", "Hexarotor", "Octorotor"}),
           ("fixed_wing", {"Fixed Wing"}),
           ("vtol", {"VTOL Standard", "Tiltrotor VTOL", "Quad-rotor VTOL (Tailsitter)",
                     "Two-rotor VTOL (Tailsitter)"})]


def pick_logs() -> list[dict]:
    sample = [r for r in json.loads(SIZES.read_text())
              if r["bytes"] and "SITL" not in r["sys_hw"].upper() and r["duration_s"] >= 30]
    picks = []
    for _, types in CLASSES:
        cands = sorted((r for r in sample if r["mav_type"] in types), key=lambda r: r["bytes"])
        if cands:
            picks.append(cands[0])
    return picks


def download(log_id: str) -> Path:
    ULOG_DIR.mkdir(parents=True, exist_ok=True)
    dest = ULOG_DIR / f"{log_id}.ulg"
    if not dest.exists():
        resp = request(f"https://cdn.logs.px4.io/{log_id}.ulg", dest=dest)
        print(f"downloaded {log_id} ({resp.status}, {dest.stat().st_size / 1e6:.2f} MB)")
    return dest


def inspect(path: Path) -> list[str]:
    ulog = ULog(str(path))
    secs = (ulog.last_timestamp - ulog.start_timestamp) / 1e6
    info = ulog.msg_info_dict
    md = [f"## `{path.stem}`", "",
          f"- File: {path.stat().st_size / 1e6:.2f} MB, logged span {secs:.0f} s",
          f"- sys_name: {info.get('sys_name')}, ver_hw: {info.get('ver_hw')}, "
          f"ver_sw_release: {info.get('ver_sw_release')}, time_ref_utc: {info.get('time_ref_utc')}",
          f"- Topics: {len(ulog.data_list)}, parameters: {len(ulog.initial_parameters)}, "
          f"logged messages: {len(ulog.logged_messages)}", "", "### Wanted fields", "",
          "| topic | instances | msgs | rate Hz | fields present | fields missing |", "| --- | --- | --- | --- | --- | --- |"]
    for topic, fields in WANTED.items():
        ds = [d for d in ulog.data_list if d.name == topic]
        if not ds:
            md.append(f"| `{topic}` | 0 | – | – | – | {', '.join(fields)} |")
            continue
        d0 = ds[0]
        n = len(d0.data["timestamp"])
        span = (d0.data["timestamp"][-1] - d0.data["timestamp"][0]) / 1e6 if n > 1 else 0
        present = [f for f in fields if f in d0.data]
        missing = [f for f in fields if f not in d0.data]
        md.append(f"| `{topic}` | {len(ds)} | {n:,} | {n / span if span else 0:.0f} | "
                  f"{', '.join(present) or '–'} | {', '.join(missing) or '–'} |")

    gp = next((d for d in ulog.data_list if d.name == "vehicle_global_position"), None)
    if gp is not None:
        lat, lon, alt = gp.data["lat"], gp.data["lon"], gp.data["alt"]
        rows_1hz = len(np.unique((gp.data["timestamp"] // 1_000_000)))
        md += ["", f"- Global position: lat {lat.min():.4f}..{lat.max():.4f}, lon {lon.min():.4f}..{lon.max():.4f}, "
                   f"alt {alt.min():.1f}..{alt.max():.1f} m AMSL; zeros (lat=lon=0): {int(((lat == 0) & (lon == 0)).sum())}",
               f"- Rows after 1 Hz downsampling: {rows_1hz:,}"]
    bat = next((d for d in ulog.data_list if d.name == "battery_status"), None)
    if bat is not None and "remaining" in bat.data:
        rem = bat.data["remaining"]
        md.append(f"- Battery remaining: {rem.max():.2f} -> {rem[-1]:.2f} (range {rem.min():.2f}..{rem.max():.2f})")

    levels: dict[str, int] = {}
    for m in ulog.logged_messages:
        levels[m.log_level_str()] = levels.get(m.log_level_str(), 0) + 1
    md += ["", f"- Logged message levels: {levels}", "", "First logged messages:", "", "```"]
    md += [f"{m.timestamp / 1e6:9.2f}s {m.log_level_str():8} {m.message}" for m in ulog.logged_messages[:8]]
    md += ["```", "", "<details><summary>All topics</summary>", "",
           "| topic | multi_id | msgs | fields |", "| --- | --- | --- | --- |"]
    md += [f"| {d.name} | {d.multi_id} | {len(d.data['timestamp']):,} | {len(d.data)} |"
           for d in sorted(ulog.data_list, key=lambda d: (d.name, d.multi_id))]
    return md + ["", "</details>", ""]


def main() -> None:
    log_ids = sys.argv[1:] or [r["log_id"] for r in pick_logs()]
    md = ["# ULog inspection", ""]
    if not sys.argv[1:]:
        md += ["Auto-picked: the smallest real (non-SITL, >= 30 s) log per vehicle class from the HEAD sample.", ""]
    for log_id in log_ids:
        md += inspect(download(log_id))
    REPORT.write_text("\n".join(md))
    print("\n".join(md))


if __name__ == "__main__":
    main()
