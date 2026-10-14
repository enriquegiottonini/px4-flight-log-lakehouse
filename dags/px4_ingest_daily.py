"""
### PX4 daily ingestion

Index branch:
- `api_healthcheck` → `snapshot_index` (conditional GET) → `index_changed` → `load_index`.
- On a **304** (index unchanged since the last load), `index_changed` short-circuits and `load_index` is skipped.

ULog branch (runs either way, driven by bronze + `audit.ulog_downloads`):
- `purge_expired_ulogs` first (D-004), then `plan_ulogs` for the uploads of the day before the run day (UTC).
- `fetch_ulogs` × batches (pool `px4_pool`), then `parse_ulogs` × batches.

Params:
- `index_url`: point it at a dead host to watch retries fail.
- `max_ulogs`: cap downloads; the default is every log of the day, ~9 GB.
"""

from __future__ import annotations

import json

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import Param, dag, get_current_context, task

from px4_common import (DEFAULT_ARGS, DEFAULT_MAX_ULOGS, INDEX_URL, INGEST, INGEST_ENV, LOG_MESSAGES, LOGS_INDEX, RUN_DAY, START,
                        TELEMETRY, cli, summary)


@dag(
    dag_id="px4_ingest_daily",
    schedule="0 2 * * *",  # 02:00 America/Hermosillo (UTC-7) = 09:00 UTC: yesterday (UTC) is complete
    start_date=START,
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    params={
        "index_url": Param(INDEX_URL, type="string", description="PX4 index endpoint"),
        "max_ulogs": Param(DEFAULT_MAX_ULOGS, type=["null", "integer"], minimum=1, description="cap ULog downloads (empty = all)"),
    },
    tags=["px4", "ingest"],
    doc_md=__doc__,
)
def px4_ingest_daily():
    env = {"env": INGEST_ENV, "append_env": True}

    healthcheck = BashOperator(task_id="api_healthcheck", bash_command=cli("healthcheck"), **env)
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
    purge = BashOperator(task_id="purge_expired_ulogs", bash_command=cli("purge-ulogs --today {{ " + RUN_DAY + " }}"),
                         trigger_rule="none_failed", **env)
    plan = BashOperator(task_id="plan_ulogs",
                        bash_command=cli("plan-ulogs --start {{ macros.ds_add(" + RUN_DAY + ", -1) }} --end {{ " + RUN_DAY + " }}"),
                        **env)

    @task
    def batch_commands(plan_summary: str, action: str) -> list[str]:
        """One fully rendered command per batch (mapped tasks below)."""
        s, run_id = summary(plan_summary), get_current_context()["run_id"]
        return [f"{INGEST} --run-id '{run_id}' {action} --plan {s['out']} --batch {i}" for i in range(s["batches"])]

    fetch = BashOperator.partial(task_id="fetch_ulogs", pool="px4_pool", **env).expand(
        bash_command=batch_commands.override(task_id="fetch_commands")(plan.output, "fetch-ulogs"))
    parse = BashOperator.partial(task_id="parse_ulogs", pool="px4_pool", outlets=[TELEMETRY, LOG_MESSAGES],
                                 **env).expand(
        bash_command=batch_commands.override(task_id="parse_commands")(plan.output, "parse-ulogs"))

    healthcheck >> snapshot
    index_changed(snapshot.output) >> load >> purge >> plan
    fetch >> parse


px4_ingest_daily()
