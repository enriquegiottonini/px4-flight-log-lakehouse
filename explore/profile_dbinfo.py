"""Profile the PX4 log index: types, empties, sentinels, distributions.

Reads data/dbinfo.json.gz (run fetch_index.py first) and writes
reports/dbinfo_profile.md. The findings feed the silver-layer cleaning rules.

    uv run python profile_dbinfo.py
"""

import gzip
import json
import re
import statistics
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from lookups import ERROR_LABELS, FLIGHT_MODES

HERE = Path(__file__).parent
INDEX_FILE = HERE / "data" / "dbinfo.json.gz"
STATE_FILE = HERE / "data" / "dbinfo.state.json"
REPORT = HERE / "reports" / "dbinfo_profile.md"

RELEASE_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)")
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def pct(n: int, total: int) -> str:
    return f"{100 * n / total:.1f} %"


def quantile(values: list[float], q: float) -> float:
    values = sorted(values)
    return values[min(len(values) - 1, int(q * len(values)))]


def table(headers: list[str], rows: list[list]) -> list[str]:
    out = ["| " + " | ".join(headers) + " |", "|" + " --- |" * len(headers)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return out + [""]


def main() -> None:
    records = json.load(gzip.open(INDEX_FILE))
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    n = len(records)
    md: list[str] = ["# PX4 index profile", ""]
    md += [f"- Records: **{n:,}**",
           f"- ETag: `{state.get('etag')}`, Last-Modified: {state.get('last_modified')}",
           f"- Compressed size: {INDEX_FILE.stat().st_size / 1e6:.1f} MB", ""]

    # --- per-field overview -------------------------------------------------
    fields = sorted({k for r in records for k in r})
    rows = []
    for f in fields:
        vals = [r.get(f) for r in records]
        types = Counter(type(v).__name__ for v in vals)
        empty = sum(1 for v in vals if v == "" or v == [])
        missing = sum(1 for r in records if f not in r)
        hashable = [json.dumps(v) if isinstance(v, list) else v for v in vals]
        rows.append([f"`{f}`", ", ".join(f"{t} {c:,}" for t, c in types.most_common()),
                     f"{empty:,} ({pct(empty, n)})", missing, f"{len(set(hashable)):,}"])
    md += ["## Fields", ""] + table(["field", "python types", "empty \"\" / []", "missing key", "distinct"], rows)

    # --- keys -----------------------------------------------------------------
    ids = Counter(r["log_id"] for r in records)
    dup = sum(c - 1 for c in ids.values() if c > 1)
    bad_uuid = sum(1 for i in ids if not UUID_RE.match(i))
    url_ok = sum(1 for r in records if r["download_url"] == f"https://cdn.logs.px4.io/{r['log_id']}.ulg")
    md += ["## Keys", "",
           f"- Duplicate `log_id`s: {dup:,}",
           f"- `log_id` not a UUID: {bad_uuid:,}",
           f"- `download_url` == `https://cdn.logs.px4.io/<log_id>.ulg`: {url_ok:,} ({pct(url_ok, n)})", ""]

    # --- sentinels and dirty values ------------------------------------------
    wind = Counter(r["wind_speed"] for r in records)
    md += ["## Sentinels and dirty values", "", "### `wind_speed`", ""]
    md += table(["value", "count", "share"], [[v, f"{c:,}", pct(c, n)] for v, c in wind.most_common(8)])

    md += ["### `rating`", ""]
    md += table(["value", "count", "share"],
                [[f"`{v!r}`", f"{c:,}", pct(c, n)] for v, c in Counter(r["rating"] for r in records).most_common()])

    at = Counter(type(r["airframe_type"]).__name__ for r in records)
    int_af = Counter(r["airframe_type"] for r in records if isinstance(r["airframe_type"], int))
    autostart_match = sum(1 for r in records if isinstance(r["airframe_type"], int)
                          and r["airframe_type"] == r["sys_autostart_id"])
    md += ["### `airframe_type`", "",
           f"- Types: {dict(at)}",
           f"- int values equal to `sys_autostart_id`: {autostart_match:,} of {sum(int_af.values()):,}",
           f"- Top int values: {int_af.most_common(5)}", ""]

    rel = [r["ver_sw_release"] for r in records]
    parsed = Counter(f"v{m[1]}.{m[2]}" for v in rel if (m := RELEASE_RE.match(v or "")))
    md += ["### `ver_sw_release`", "",
           f"- Empty: {sum(1 for v in rel if not v):,} ({pct(sum(1 for v in rel if not v), n)})",
           f"- Parseable as `vX.Y.Z`: {sum(parsed.values()):,} ({pct(sum(parsed.values()), n)})",
           f"- Unparseable non-empty examples: {[v for v in set(rel) if v and not RELEASE_RE.match(v)][:8]}",
           "- Top major.minor:", ""]
    md += table(["release", "count"], [[k, f"{v:,}"] for k, v in parsed.most_common(10)])

    # --- categorical distributions -------------------------------------------
    md += ["## Categorical distributions", "", "### `mav_type`", ""]
    md += table(["mav_type", "count", "share"],
                [[v, f"{c:,}", pct(c, n)] for v, c in Counter(r["mav_type"] for r in records).most_common()])
    for f in ("source", "type", "estimator"):
        md += [f"### `{f}`", ""]
        md += table([f, "count"], [[f"`{v!r}`", f"{c:,}"] for v, c in Counter(r[f] for r in records).most_common(8)])

    # --- flight modes and error labels ---------------------------------------
    mode_count = Counter(m for r in records for m in r["flight_modes"])
    mode_secs = Counter()
    bad_pairs = 0
    for r in records:
        for pair in r["flight_mode_durations"]:
            if isinstance(pair, list) and len(pair) == 2:
                mode_secs[pair[0]] += pair[1]
            else:
                bad_pairs += 1
    unknown_modes = sorted(m for m in mode_count if m not in FLIGHT_MODES)
    md += ["## Flight modes", "",
           f"- Logs with no modes: {sum(1 for r in records if not r['flight_modes']):,}",
           f"- Malformed `flight_mode_durations` pairs: {bad_pairs:,}",
           f"- Mode IDs missing from the lookup table: {unknown_modes}", ""]
    md += table(["id", "name", "logs using it", "total hours"],
                [[m, FLIGHT_MODES.get(m, "?"), f"{c:,}", f"{mode_secs[m] / 3600:,.0f}"]
                 for m, c in mode_count.most_common(15)])

    labels = Counter(l for r in records for l in r["error_labels"])
    md += ["## Error labels", "",
           f"- Logs with at least one label: {sum(1 for r in records if r['error_labels']):,}", ""]
    md += table(["id", "name", "logs"], [[l, ERROR_LABELS.get(l, "?"), c] for l, c in labels.most_common()])

    # --- numeric fields --------------------------------------------------------
    md += ["## Numeric fields", ""]
    rows = []
    for f in ("duration_s", "num_logged_errors", "num_logged_warnings"):
        vals = [r[f] for r in records if isinstance(r[f], (int, float))]
        rows.append([f"`{f}`", min(vals), statistics.median(vals), quantile(vals, 0.95), max(vals),
                     sum(1 for v in vals if v <= 0)])
    md += table(["field", "min", "median", "p95", "max", "<= 0"], rows)

    # --- dates -----------------------------------------------------------------
    dates = [r["log_date"] for r in records]
    by_year = Counter(d[:4] for d in dates)
    by_day = Counter(dates)
    last = max(date.fromisoformat(d) for d in dates)
    last90 = [by_day.get((last - timedelta(days=i)).isoformat(), 0) for i in range(1, 91)]
    md += ["## `log_date`", "",
           f"- Range: {min(dates)} -> {max(dates)}",
           f"- Logs/day over the last 90 full days: median {statistics.median(last90):.0f}, "
           f"p95 {quantile(last90, 0.95)}, max {max(last90)}",
           f"- Logs with `log_date >= 2025-01-01` (default INDEX_START_DATE): "
           f"{sum(1 for d in dates if d >= '2025-01-01'):,}", ""]
    md += table(["year", "logs"], [[y, f"{c:,}"] for y, c in sorted(by_year.items())])
    md += ["Last 14 days:", ""]
    md += table(["log_date", "logs"],
                [[(last - timedelta(days=i)).isoformat(), by_day.get((last - timedelta(days=i)).isoformat(), 0)]
                 for i in range(14)])

    # --- vehicles --------------------------------------------------------------
    uuids = Counter(r["vehicle_uuid"] for r in records if r["vehicle_uuid"])
    md += ["## Vehicles", "",
           f"- Distinct non-empty `vehicle_uuid`: {len(uuids):,}",
           f"- Logs without `vehicle_uuid`: {sum(1 for r in records if not r['vehicle_uuid']):,}",
           f"- Logs per vehicle: median {statistics.median(uuids.values()):.0f}, max {max(uuids.values()):,}",
           f"- Distinct `sys_hw`: {len({r['sys_hw'] for r in records}):,}; top: "
           f"{Counter(r['sys_hw'] for r in records).most_common(6)}", ""]

    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text("\n".join(md))
    print("\n".join(md))
    print(f"\nwrote {REPORT.relative_to(HERE)}")


if __name__ == "__main__":
    main()
