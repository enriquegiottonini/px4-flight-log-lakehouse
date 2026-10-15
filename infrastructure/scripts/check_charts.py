"""Quality gate for the dbt Charts boards (Phase 8). Exit code 0 = every board is publishable.

1. `dct validate --strict --json` on every board: any error, and any warning except
   WARN-DBT-QUERY-COLUMNS-INDETERMINATE, fails. dbt Charts 0.9.1 raises that warning for every
   query with a filter macro or variable (templated SQL can't be analyzed offline), and its
   query-level `ignore:` doesn't suppress it in `validate`. Queries without them DO get the
   offline column-vs-model check (ERR-DBT-MODEL-COLUMN-MISSING).
2. `dct render --format text` on every board: runs every query against Trino, so a query the
   offline check had to skip is still verified. Any ERR- code, or a WARN- code that doesn't depend on
   how much data there is, fails. Data-dependent warnings (an empty chart in a young environment) are
   reported but don't block: the smoke test asserts the data itself.

    python check_charts.py [--dct /opt/charts-venv/bin/dct] [--project-dir /opt/dbt]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

UNCHECKABLE_OFFLINE = {"WARN-DBT-QUERY-COLUMNS-INDETERMINATE"}
# Depend on the data volume, not on the board's correctness (seen on a fresh clone with ~40 parsed logs)
DATA_DEPENDENT = {"WARN-QUERY-RETURNED-ZERO-ROWS", "WARN-Y-ENCODING-MOSTLY-NULL", "WARN-BAR-GROUPED-SERIES-COINCIDE"}
CODE = re.compile(r"\b((?:WARN|ERR)-[A-Z0-9-]+)")


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dct", default="/opt/charts-venv/bin/dct")
    ap.add_argument("--project-dir", default="/opt/dbt", type=Path)
    args = ap.parse_args()

    boards = sorted(p for p in (args.project_dir / "charts").glob("*.yml") if not p.name.startswith("_"))
    if not boards:
        print("no boards found under charts/")
        return 1
    failed = False
    for board in boards:
        rel = str(board.relative_to(args.project_dir))
        v = run([args.dct, "validate", "--strict", "--json", rel], args.project_dir)
        report = json.loads(v.stdout)
        findings = report.get("errors", []) + report.get("warnings", [])
        blocking = [f for f in findings if f.get("code") not in UNCHECKABLE_OFFLINE]
        skipped = len(findings) - len(blocking)

        r = run([args.dct, "render", rel, "--format", "text"], args.project_dir)
        render_codes = sorted(set(CODE.findall(r.stdout + r.stderr)))
        render_blocking = [c for c in render_codes if c not in DATA_DEPENDENT]
        render_notes = [c for c in render_codes if c in DATA_DEPENDENT]

        ok = not blocking and not render_blocking and r.returncode == 0
        failed |= not ok
        print(f"{'OK  ' if ok else 'FAIL'} {rel}: {len(findings) - skipped} validate findings, "
              f"{skipped} queries checked by execution only, render codes: {render_blocking or 'none'}"
              + (f" (data-dependent, not blocking: {render_notes})" if render_notes else ""))
        for f in blocking:
            print(f"      {f.get('code')}: {f.get('message', '')[:200]}")
        if r.returncode != 0:
            print("      render failed:", (r.stderr or r.stdout).strip().splitlines()[-1:])
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
