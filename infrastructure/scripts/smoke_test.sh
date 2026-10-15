#!/usr/bin/env bash
# End-to-end smoke test: stack up -> daily ingestion (capped) -> asset-triggered dbt transform
# -> gold tables and published reports checked. Exit code 0 = the whole pipeline works.
#
#   infrastructure/scripts/smoke_test.sh            # against this checkout's stack
#   SMOKE_MAX_ULOGS=5 infrastructure/scripts/smoke_test.sh
#
# From a clean clone (fresh volumes, your stack's data untouched; see README "Smoke test").
# It needs internet: the PX4 index (~32 MB) and SMOKE_MAX_ULOGS ULog files.
set -euo pipefail
cd "$(dirname "$0")/../.."  # repo root

MAX_ULOGS=${SMOKE_MAX_ULOGS:-20}
TIMEOUT=${SMOKE_TIMEOUT:-1500}  # seconds for each wait
START=$(date +%s)
REPORTS_LIST=$(mktemp)  # report keys published by the transform run
trap 'rm -f "$REPORTS_LIST"' EXIT

step() { printf '\n==> %s\n' "$*"; }

step "1/5 .env (generated with random secrets if missing)"
if [[ ! -f .env ]]; then
  make env
  # Unpausing px4_ingest_daily on a fresh database immediately runs its latest missed 02:00 slot with the
  # DEFAULT cap; empty would mean a full day of ULogs (~9 GB). Cap it like the smoke run.
  sed -i.bak "s/^PX4_MAX_ULOGS_PER_RUN=.*/PX4_MAX_ULOGS_PER_RUN=$MAX_ULOGS/" .env && rm -f .env.bak
fi
if ! grep -qE '^PX4_MAX_ULOGS_PER_RUN=[0-9]+' .env; then
  echo "Refusing to run: PX4_MAX_ULOGS_PER_RUN is empty in .env, so the scheduled run that unpausing"
  echo "px4_ingest_daily can start would download a full day of ULogs (~9 GB). Set a number first."
  exit 1
fi

step "2/5 make up (6 services healthy, 2 one-shot jobs exited 0: 8 containers)"
make up
containers=$(docker compose ps -a -q | wc -l | tr -d ' ')
echo "    containers: $containers"
(( containers == 8 )) || { echo "SMOKE TEST FAILED: expected 8 containers, got $containers"; docker compose ps -a; exit 1; }

step "3/5 unpause px4_ingest_daily + px4_transform, trigger ingestion (max_ulogs=$MAX_ULOGS)"
step "4/5 wait for ingestion, then for the asset-triggered transform (dbt + charts + reports)"
python3 -u - "$MAX_ULOGS" "$TIMEOUT" "$REPORTS_LIST" <<'PY'
import json, sys, time, urllib.parse, urllib.request

API, MAX_ULOGS, TIMEOUT, REPORTS_LIST = "http://localhost:8080/api/v2", int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]

def call(path, method="GET", body=None):
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)

def runs(dag):
    return call(f"/dags/{dag}/dagRuns?limit=50&order_by=-run_after")["dag_runs"]

def failed_tasks(dag, run_id):
    tis = call(f"/dags/{dag}/dagRuns/{urllib.parse.quote(run_id, safe='')}/taskInstances?limit=300")["task_instances"]
    return sorted({t["task_id"] for t in tis if t["state"] in ("failed", "upstream_failed")})

def wait(what, done, timeout=TIMEOUT):
    t0 = time.time()
    while time.time() - t0 < timeout:
        result = done()
        if result is not None:
            return result
        time.sleep(10)
    sys.exit(f"SMOKE TEST FAILED: timed out after {timeout}s waiting for {what}")

for dag in ("px4_ingest_daily", "px4_transform"):
    wait(f"{dag} to be parsed", lambda dag=dag: True if call(f"/dags?dag_id_pattern={dag}")["total_entries"] else None)
    call(f"/dags/{dag}", "PATCH", {"is_paused": False})

run = call("/dags/px4_ingest_daily/dagRuns", "POST", {"logical_date": None, "conf": {"max_ulogs": MAX_ULOGS}})
ingest_id = run["dag_run_id"]
print(f"    ingestion run {ingest_id}")

def ingest_done():
    r = next(x for x in runs("px4_ingest_daily") if x["dag_run_id"] == ingest_id)
    if r["state"] == "failed":
        sys.exit(f"SMOKE TEST FAILED: ingestion failed in {failed_tasks('px4_ingest_daily', ingest_id)}")
    return r if r["state"] == "success" else None

ingest = wait("the ingestion run", ingest_done)
print(f"    ingestion succeeded ({ingest['start_date'][11:19]} -> {ingest['end_date'][11:19]} UTC)")

# load_index and parse_ulogs each update bronze assets. Airflow collapses events that arrive while a transform
# run is queued, and lists as "consumed" only the events that existed when the run was created, so neither
# "runs created after the ingestion" nor "runs that consumed our events" is reliable (both hung on a clean
# clone). What guarantees our data was processed: a transform run that STARTED after the ingestion's last
# task ENDED (every bronze write happens in a task; dbt reads bronze when it runs) finished, and nothing is
# still queued/running. Not the DAG run's end_date: Airflow stamps it after the last task, and an idle
# px4_transform can start in between (seen: 134 ms earlier). Step 5 then checks silver caught up with bronze.
tis = call(f"/dags/px4_ingest_daily/dagRuns/{urllib.parse.quote(ingest_id, safe='')}/taskInstances?limit=300")["task_instances"]
last_write = max(t["end_date"] for t in tis if t["end_date"])

def transforms_done():
    rs = [r for r in runs("px4_transform") if r["run_type"] == "asset_triggered"
          and (r["end_date"] or "9") >= ingest["start_date"]]  # every run that worked during/after our ingestion
    if any(r["state"] in ("queued", "running") for r in rs):
        return None
    if not any((r["start_date"] or "") >= last_write for r in rs):
        return None
    return rs

rs = wait("the asset-triggered transform", transforms_done)
for r in rs:
    print(f"    transform {r['dag_run_id']}: {r['state']}")
for r in rs:  # every run must pass: a failure followed by a success still means a flaky DAG
    if r["state"] != "success":
        sys.exit(f"SMOKE TEST FAILED: transform {r['dag_run_id']} failed in {failed_tasks('px4_transform', r['dag_run_id'])}")
latest = rs[0]
keys = call(f"/dags/px4_transform/dagRuns/{urllib.parse.quote(latest['dag_run_id'], safe='')}"
            "/taskInstances/upload_reports/xcomEntries/return_value")["value"]
if isinstance(keys, str):
    keys = json.loads(keys.replace("'", '"'))
open(REPORTS_LIST, "w").write("".join(k + "\n" for k in keys))
print(f"    reports published: {len(keys)}")
PY

step "5/5 check gold tables and the published reports"
X() { docker compose exec -T trino trino --output-format TSV --execute "$1" 2>/dev/null; }
read -r flights telemetry_flights months boards < <(X "SELECT
  (SELECT count(*) FROM iceberg.silver.fct_flight),
  (SELECT count(*) FROM iceberg.silver.fct_flight WHERE has_telemetry),
  (SELECT count(*) FROM iceberg.gold.mart_flights_by_class_month),
  (SELECT count(*) FROM iceberg.gold.mart_pipeline_runs)" | tr '\t' ' ')
echo "    fct_flight rows: $flights | with telemetry: $telemetry_flights | class-month rows: $months | pipeline runs: $boards"
(( flights > 0 && telemetry_flights > 0 && months > 0 && boards > 0 )) || { echo "SMOKE TEST FAILED: empty gold/silver tables"; exit 1; }
# Silver must have caught up with bronze (an incremental model that stops inserting fails here)
read -r b_tel s_tel b_msg s_msg < <(X "SELECT
  (SELECT count(*) FROM iceberg.bronze.telemetry_raw), (SELECT count(*) FROM iceberg.silver.stg_telemetry),
  (SELECT count(*) FROM iceberg.bronze.log_messages_raw), (SELECT count(*) FROM iceberg.silver.stg_log_messages)" | tr '\t' ' ')
echo "    telemetry bronze/silver: $b_tel/$s_tel | messages bronze/silver: $b_msg/$s_msg"
(( b_tel == s_tel && b_msg == s_msg && s_tel > 0 )) || { echo "SMOKE TEST FAILED: silver is behind bronze"; exit 1; }

day_prefix=$(head -1 "$REPORTS_LIST" | sed -E 's#s3://reports/([^/]+)/.*#\1#')
listed=$(docker compose run --rm aws s3 ls "s3://reports/$day_prefix/" 2>/dev/null \
         | grep -cE '\.(html|pdf)$' || true)
expected=$(wc -l < "$REPORTS_LIST" | tr -d ' ')
echo "    s3://reports/$day_prefix/: $listed files (expected $expected)"
(( listed == expected && listed >= 8 )) || { echo "SMOKE TEST FAILED: reports missing in s3://reports/$day_prefix/"; exit 1; }

echo
echo "SMOKE TEST PASSED in $(( $(date +%s) - START ))s"
