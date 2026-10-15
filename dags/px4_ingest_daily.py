"""
### PX4 daily ingestion

Index branch:
- `snapshot_index` (conditional GET) → `index_changed` → `load_index`.
- On a **304** (index unchanged since the last load), `index_changed` short-circuits and `load_index` is skipped.
- If PX4 is unreachable, `snapshot_index` retries with backoff and then fails with the error in its log.

ULog branch (runs either way, driven by bronze + `audit.ulog_downloads`):
- `plan_ulogs` for one upload day (default: the day before the run day, UTC).
- `fetch_ulogs` × batches, then `parse_ulogs` × batches, at most 4 at a time.
- Old raw files are deleted by RustFS itself: the lifecycle rule on `landing/px4/ulog/` (1 day, set by `setup`).

Params:
- `day`: (re)process any upload day, e.g. `{"day": "2026-10-10"}`. This replaced the backfill DAG.
- `max_ulogs`: cap downloads; empty means every log of the day, ~9 GB.
- `index_url`: point it at a dead host to watch retries fail.
"""

from __future__ import annotations

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import Param, dag, get_current_context, task

from px4_common import (DEFAULT_ARGS, DEFAULT_MAX_ULOGS, INDEX_URL, INGEST, INGEST_ENV, LOG_MESSAGES, LOGS_INDEX, RUN_DAY,
                        START, TELEMETRY, cli, summary)

# Upload day to process (Jinja expression): the `day` param, or the day before the run day (UTC)
DAY = "(params.day or macros.ds_add(" + RUN_DAY + ", -1))"


@dag(
    dag_id="px4_ingest_daily",
    schedule="0 2 * * *",  # 02:00 America/Hermosillo (UTC-7) = 09:00 UTC: yesterday (UTC) is complete
    start_date=START,
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    params={
        "day": Param(None, type=["null", "string"], format="date",
                     description="upload day to process (empty = the day before the run day)"),
        "max_ulogs": Param(DEFAULT_MAX_ULOGS, type=["null", "integer"], minimum=1, description="cap ULog downloads (empty = all)"),
        "index_url": Param(INDEX_URL, type="string", description="PX4 index endpoint"),
    },
    tags=["px4", "ingest"],
    doc_md=__doc__,
)
def px4_ingest_daily():
    env = {"env": INGEST_ENV, "append_env": True}

    snapshot = BashOperator(task_id="snapshot_index", bash_command=cli("snapshot-index"), **env)

    @task.short_circuit(ignore_downstream_trigger_rules=False)
    def index_changed(snapshot_summary: str) -> str | None:
        """Manifest key if a new snapshot landed; None (falsy) on 304 skips load_index only."""
        s = summary(snapshot_summary)
        return s["manifest_key"] if s["status"] == "downloaded" else None

    load = BashOperator(
        task_id="load_index",
        bash_command=cli("load-index --manifest '{{ ti.xcom_pull(task_ids=\"index_changed\") }}'"),
        outlets=[LOGS_INDEX],
        **env,
    )

    # none_failed: run after load_index whether it ran or was skipped by the 304
    plan = BashOperator(task_id="plan_ulogs", trigger_rule="none_failed",
                        bash_command=cli("plan-ulogs --start {{ " + DAY + " }} --end {{ macros.ds_add(" + DAY + ", 1) }}"),
                        **env)

    @task
    def batch_commands(plan_summary: str, action: str) -> list[str]:
        """One fully rendered command per batch (mapped tasks below)."""
        s, run_id = summary(plan_summary), get_current_context()["run_id"]
        return [f"{INGEST} --run-id '{run_id}' {action} --plan {s['out']} --batch {i}" for i in range(s["batches"])]

    # max_active_tis_per_dagrun: at most 4 batches talk to the PX4 CDN at once (no Airflow pool to create)
    fetch = BashOperator.partial(task_id="fetch_ulogs", max_active_tis_per_dagrun=4, **env).expand(
        bash_command=batch_commands.override(task_id="fetch_commands")(plan.output, "fetch-ulogs"))
    parse = BashOperator.partial(task_id="parse_ulogs", max_active_tis_per_dagrun=4, outlets=[TELEMETRY, LOG_MESSAGES],
                                 **env).expand(
        bash_command=batch_commands.override(task_id="parse_commands")(plan.output, "parse-ulogs"))

    index_changed(snapshot.output) >> load >> plan
    fetch >> parse


px4_ingest_daily()
