"""drone-ingest command line. Every command prints a JSON summary on stdout; logs go to stderr.

    drone-ingest init-tables
    drone-ingest snapshot-index [--run-id ID]
    drone-ingest load-index     [--run-id ID] [--manifest KEY]
    drone-ingest plan-ulogs     [--out plan.json] [--start YYYY-MM-DD --end YYYY-MM-DD]
    drone-ingest fetch-ulogs    --plan plan.json [--batch N]
    drone-ingest parse-ulogs    --plan plan.json [--batch N]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from drone_ingest import catalog as cat, index, ulog
from drone_ingest.config import get_settings


class _Context(logging.Filter):
    def __init__(self, run_id: str, command: str):
        super().__init__()
        self.run_id, self.command = run_id, command

    def filter(self, record):
        record.run_id, record.command = self.run_id, self.command
        return True


def _setup_logging(run_id: str, command: str) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s run_id=%(run_id)s cmd=%(command)s %(name)s: %(message)s"))
    handler.addFilter(_Context(run_id, command))
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    for noisy in ("botocore", "boto3", "urllib3", "s3transfer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _load_plan(path: str, batch: int | None) -> list[dict]:
    plan = json.loads(Path(path).read_text())
    selected = plan["batches"] if batch is None else [plan["batches"][batch]]
    return [e for b in selected for e in b]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="drone-ingest", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-id", default=f"manual__{datetime.now(timezone.utc):%Y%m%dT%H%M%S}")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-tables", help="create missing bronze/audit tables")
    sub.add_parser("snapshot-index", help="conditional GET of the PX4 index into landing")
    p = sub.add_parser("load-index", help="diff-load the latest landed snapshot into bronze")
    p.add_argument("--manifest", help="landing key of a _manifest.json (default: newest)")
    p = sub.add_parser("plan-ulogs", help="list ULogs to fetch/parse for a log_date window")
    p.add_argument("--start", type=date.fromisoformat)
    p.add_argument("--end", type=date.fromisoformat, help="exclusive")
    p.add_argument("--out", help="plan file (default: WORK_DIR/<run id>/plan.json)")
    for name in ("fetch-ulogs", "parse-ulogs"):
        p = sub.add_parser(name)
        p.add_argument("--plan", required=True)
        p.add_argument("--batch", type=int, help="batch index (default: all batches)")
    args = parser.parse_args(argv)

    _setup_logging(args.run_id, args.command)
    settings = get_settings()
    catalog = cat.get_catalog(settings)
    cat.ensure_tables(catalog)

    if args.command == "init-tables":
        result = {"tables": sorted(cat.TABLES)}
    elif args.command == "snapshot-index":
        result = index.snapshot_index(settings, catalog, args.run_id)
    elif args.command == "load-index":
        result = index.load_index(settings, catalog, args.run_id, args.manifest)
    elif args.command == "plan-ulogs":
        entries = ulog.plan_ulogs(settings, catalog, args.start, args.end)
        plan = {"run_id": args.run_id, "entries": len(entries),
                "window": [str(args.start or settings.ulog_start_date), str(args.end or settings.ulog_end_date)],
                "batches": ulog.batches(entries, settings.ulog_batch_size)}
        out = Path(args.out or Path(settings.work_dir) / index.safe_id(args.run_id) / "plan.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(plan, indent=1))
        result = {k: plan[k] for k in ("entries", "window")} | {"batches": len(plan["batches"]), "out": str(out)}
    elif args.command == "fetch-ulogs":
        result = ulog.fetch_ulogs(settings, catalog, _load_plan(args.plan, args.batch), args.run_id)
    elif args.command == "parse-ulogs":
        result = ulog.parse_ulogs(settings, catalog, _load_plan(args.plan, args.batch), args.run_id)
    print(json.dumps({"command": args.command, "run_id": args.run_id, **result}, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
