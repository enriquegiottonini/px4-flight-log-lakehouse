"""
### PX4 transform (dbt via Cosmos)

**Triggered by data, not by the clock:** it runs when any bronze asset gets new data, i.e. when `load_index`, `parse_ulogs` or `backfill_day` finish.

Steps:
- `source_freshness`: a stale index (> 48 h) stops the run before anything is published.
- `seed`: lookup tables.
- `silver` and `gold`: Cosmos task groups. Every dbt model becomes a **run** task followed by a **test** task.
- `docs_generate`: emits the `iceberg://px4/gold` asset.

Test severity:
- A test with severity `error` fails its task, and every model downstream is skipped (`upstream_failed`).
- A `warn` test only logs a warning.

dbt runs from `/opt/dbt-venv` (D-008). Cosmos finds the models by running `dbt ls` at parse time; the result is cached.
"""

from __future__ import annotations

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import Asset, dag
from cosmos import DbtTaskGroup, ExecutionConfig, ProfileConfig, ProjectConfig, RenderConfig
from cosmos.constants import InvocationMode, LoadMode, TestBehavior

from px4_common import DEFAULT_ARGS, LOG_MESSAGES, LOGS_INDEX, START, TELEMETRY

DBT = "/opt/dbt-venv/bin/dbt"
PROJECT = "/opt/dbt"
GOLD = Asset("iceberg://px4/gold")  # dashboards (Phase 8) can schedule on this

project = ProjectConfig(dbt_project_path=PROJECT, install_dbt_deps=False)  # airflow-init runs dbt deps
profile = ProfileConfig(profile_name="px4_lakehouse", target_name="dev", profiles_yml_filepath=f"{PROJECT}/profiles.yml")
# SUBPROCESS: dbt is a separate binary in its own venv; Cosmos' default in-process runner can't use it
execution = ExecutionConfig(dbt_executable_path=DBT, invocation_mode=InvocationMode.SUBPROCESS)


def layer(tag: str) -> RenderConfig:
    return RenderConfig(
        select=[f"tag:{tag}"],
        load_method=LoadMode.DBT_LS,
        dbt_executable_path=DBT,
        invocation_mode=InvocationMode.SUBPROCESS,  # render-time `dbt ls` has its own setting
        test_behavior=TestBehavior.AFTER_EACH,  # <model>.run then <model>.test
        emit_datasets=False,                    # one layer-level asset (GOLD) instead of one per model
    )


@dag(
    dag_id="px4_transform",
    schedule=(LOGS_INDEX | TELEMETRY | LOG_MESSAGES),  # any of them updated -> run
    start_date=START,
    catchup=False,
    max_active_runs=1,       # never two runs writing the same tables
    max_active_tasks=4,      # each dbt task is a ~200 MB process (8 GB laptop budget)
    default_args={**DEFAULT_ARGS, "retries": 0},  # dbt failures are deterministic: don't retry
    tags=["px4", "transform", "dbt"],
    doc_md=__doc__,
)
def px4_transform():
    freshness = BashOperator(task_id="source_freshness", bash_command=f"cd {PROJECT} && {DBT} source freshness")
    seed = BashOperator(task_id="seed", bash_command=f"cd {PROJECT} && {DBT} seed")
    silver = DbtTaskGroup(group_id="silver", project_config=project, profile_config=profile,
                          execution_config=execution, render_config=layer("silver"))
    gold = DbtTaskGroup(group_id="gold", project_config=project, profile_config=profile,
                        execution_config=execution, render_config=layer("gold"))
    docs = BashOperator(task_id="docs_generate", bash_command=f"cd {PROJECT} && {DBT} docs generate --static",
                        outlets=[GOLD])

    freshness >> seed >> silver >> gold >> docs


px4_transform()
