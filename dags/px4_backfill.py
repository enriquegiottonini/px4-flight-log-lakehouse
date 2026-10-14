"""
### PX4 ULog backfill

Fetches and parses the ULogs uploaded between `start_date` and `end_date` (both inclusive).
- **One day at a time:** the mapped `backfill_day` tasks run one after another (`max_active_tis_per_dagrun=1`).
- Each day runs `drone-ingest run-ulogs`: purge → plan → fetch + parse every batch → purge.
- Raw files of past days are deleted right after parsing, so landing never holds more than one day (D-004).

The index must already contain those days (`px4_ingest_daily` loads it).
- Budget ~9 GB of downloads per day.
- `max_ulogs` caps each day.
"""

from __future__ import annotations

from datetime import date, timedelta

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import Param, dag, get_current_context, task

from px4_common import DEFAULT_ARGS, DEFAULT_MAX_ULOGS, INDEX_URL, INGEST, INGEST_ENV, LOG_MESSAGES, START, TELEMETRY


@dag(
    dag_id="px4_backfill",
    schedule=None,  # manual only
    start_date=START,
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    params={
        "start_date": Param(type="string", format="date", description="first upload day (inclusive)"),
        "end_date": Param(type="string", format="date", description="last upload day (inclusive)"),
        "max_ulogs": Param(DEFAULT_MAX_ULOGS, type=["null", "integer"], minimum=1, description="cap per day (empty = all)"),
        "index_url": Param(INDEX_URL, type="string"),
    },
    tags=["px4", "ingest", "backfill"],
    doc_md=__doc__,
)
def px4_backfill():
    @task
    def day_commands() -> list[str]:
        ctx = get_current_context()
        start, end = (date.fromisoformat(ctx["params"][k]) for k in ("start_date", "end_date"))
        if end < start:
            raise ValueError(f"end_date {end} is before start_date {start}")
        days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
        return [f"{INGEST} --run-id '{ctx['run_id']}' run-ulogs --start {d} --end {d + timedelta(days=1)}"
                for d in days]

    BashOperator.partial(
        task_id="backfill_day",
        pool="px4_pool",
        max_active_tis_per_dagrun=1,  # strictly one day at a time
        outlets=[TELEMETRY, LOG_MESSAGES],
        env=INGEST_ENV,
        append_env=True,
    ).expand(bash_command=day_commands())


px4_backfill()
