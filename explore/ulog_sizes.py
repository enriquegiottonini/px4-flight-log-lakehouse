"""Estimate ULog storage needs with HEAD requests (no file bodies downloaded).

Samples N random logs from the last D days of the index, reads Content-Length,
and projects GB/day and GB per ULOG window. Writes reports/ulog_sizes.md and
data/ulog_sizes.json (reused by inspect_ulog.py to pick small files).

    uv run python ulog_sizes.py [--n 200] [--days 7] [--seed 42]
"""

import argparse
import gzip
import json
import random
import statistics
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

from px4http import request

HERE = Path(__file__).parent
INDEX_FILE = HERE / "data" / "dbinfo.json.gz"
OUT_JSON = HERE / "data" / "ulog_sizes.json"
REPORT = HERE / "reports" / "ulog_sizes.md"


def head_size(rec: dict) -> dict:
    resp = request(rec["download_url"], method="HEAD", timeout=60)
    size = int(resp.headers.get("content-length", 0)) if resp.status == 200 else None
    return {"log_id": rec["log_id"], "log_date": rec["log_date"], "mav_type": rec["mav_type"],
            "sys_hw": rec["sys_hw"], "duration_s": rec["duration_s"], "status": resp.status, "bytes": size}


def q(values: list[float], p: float) -> float:
    values = sorted(values)
    return values[min(len(values) - 1, int(p * len(values)))]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    records = json.load(gzip.open(INDEX_FILE))
    last = max(date.fromisoformat(r["log_date"]) for r in records)
    since = (last - timedelta(days=args.days)).isoformat()
    window = [r for r in records if since < r["log_date"] <= last.isoformat()]
    sample = random.Random(args.seed).sample(window, min(args.n, len(window)))
    print(f"{len(window):,} logs in ({since}, {last}]; HEAD on {len(sample)} of them, 4 at a time")

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(head_size, sample))
    OUT_JSON.write_text(json.dumps(results, indent=1))

    ok = [r for r in results if r["bytes"] is not None]
    sizes = [r["bytes"] / 1e6 for r in ok]
    per_day = len(window) / args.days
    mean = statistics.mean(sizes)
    rate = [r["bytes"] / r["duration_s"] / 1e3 for r in ok if 0 < r["duration_s"] < 86400]

    md = ["# ULog size sample", "",
          f"- Window: log_date in ({since}, {last}], {len(window):,} logs (~{per_day:.0f}/day)",
          f"- Sample: {len(sample)} random logs (seed {args.seed}); HTTP status: "
          f"{dict((s, sum(1 for r in results if r['status'] == s)) for s in {r['status'] for r in results})}", "",
          "| stat | MB |", "| --- | --- |",
          *[f"| {k} | {v:.2f} |" for k, v in [("min", min(sizes)), ("median", statistics.median(sizes)),
                                             ("mean", mean), ("p95", q(sizes, 0.95)), ("max", max(sizes))]],
          "", f"- Throughput: median {statistics.median(rate):.1f} KB per second of flight", "",
          "## Projection (mean size x logs/day)", "",
          "| window | logs | GB |", "| --- | --- | --- |",
          f"| 1 day | {per_day:,.0f} | {per_day * mean / 1e3:.1f} |",
          f"| {args.days} days | {len(window):,} | {len(window) * mean / 1e3:.1f} |",
          f"| 14 days (ULOG_RETENTION_DAYS) | {per_day * 14:,.0f} | {per_day * 14 * mean / 1e3:.1f} |", "",
          "## By vehicle class (sample)", "", "| mav_type | n | median MB | mean MB |", "| --- | --- | --- | --- |"]
    by_type: dict[str, list[float]] = {}
    for r in ok:
        by_type.setdefault(r["mav_type"], []).append(r["bytes"] / 1e6)
    for t, v in sorted(by_type.items(), key=lambda kv: -len(kv[1])):
        md.append(f"| {t} | {len(v)} | {statistics.median(v):.2f} | {statistics.mean(v):.2f} |")
    md += ["", "Largest in sample:", ""]
    md += [f"- {r['bytes'] / 1e6:.0f} MB, {r['duration_s']} s, {r['mav_type']}, {r['sys_hw']}"
           for r in sorted(ok, key=lambda r: -r["bytes"])[:5]]

    REPORT.write_text("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
