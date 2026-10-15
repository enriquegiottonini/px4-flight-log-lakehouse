"""
### PX4 transform (dbt via Cosmos)

**Triggered by data, not by the clock:** it runs when any bronze asset gets new data, i.e. when `load_index` or `parse_ulogs` finish.

Steps:
- `source_freshness`: a stale index (> 48 h) stops the run before anything is published.
- `seed`: lookup tables.
- `silver` and `gold`: Cosmos task groups. Every dbt model becomes a **run** task followed by a **test** task.
- `docs_generate`: emits the `iceberg://px4/gold` asset.
- `check_charts` → `render_charts` → `upload_reports`: every dbt Charts board must validate and render cleanly, then HTML and PDF copies go to `s3://reports/<run day>/` (Phase 8).

Test severity:
- A test with severity `error` fails its task, and every model downstream is skipped (`upstream_failed`).
- A `warn` test only logs a warning.

dbt runs from `/opt/dbt-venv` (D-008). Cosmos finds the models by running `dbt ls` at parse time; the result is cached.
"""

from __future__ import annotations

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import Asset, dag, task
from cosmos import DbtTaskGroup, ExecutionConfig, ProfileConfig, ProjectConfig, RenderConfig
from cosmos.constants import InvocationMode, LoadMode, TestBehavior

from px4_common import DEFAULT_ARGS, LOG_MESSAGES, LOGS_INDEX, RUN_DAY, START, TELEMETRY

DBT = "/opt/dbt-venv/bin/dbt"
PROJECT = "/opt/dbt"
DCT = "/opt/charts-venv/bin/dct"
GOLD = Asset("iceberg://px4/gold")
REPORTS = Asset("s3://reports")
REPORTS_DIR = "/opt/airflow/work/reports/{{ " + RUN_DAY + " }}"

project = ProjectConfig(dbt_project_path=PROJECT, install_dbt_deps=False)  # the setup job runs dbt deps
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
        # A test that reads several models (relationships: fct_flight -> dim_vehicle) gets its own task that
        # waits for ALL of them. Attached to one parent, it raced the other: new vehicles in fct_flight, a
        # dim_vehicle not rebuilt yet -> 140 false failures (found by the Phase 9 smoke test).
        should_detach_multiple_parents_tests=True,
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

    check = BashOperator(
        task_id="check_charts",
        bash_command=f"cd {PROJECT} && /opt/charts-venv/bin/python /opt/scripts/check_charts.py --dct {DCT}",
        env={"TRINO_USER": "charts"}, append_env=True,
    )
    render = BashOperator(
        task_id="render_charts",
        bash_command=(f"cd {PROJECT} && rm -rf {REPORTS_DIR} && mkdir -p {REPORTS_DIR}"
                      f" && {DCT} render charts/[!_]*.yml --format html --output {REPORTS_DIR}/{{stem}}.html"
                      f" && {DCT} render charts/[!_]*.yml --format pdf --output {REPORTS_DIR}/{{stem}}.pdf"
                      f" && ls -la {REPORTS_DIR}"),
        env={"TRINO_USER": "charts"}, append_env=True,
    )

    @task(outlets=[REPORTS])
    def upload_reports(local_dir: str) -> list[str]:
        """Copy the rendered boards to s3://reports/<day>/ (RustFS) with the stack's S3 keys."""
        import os
        from pathlib import Path

        import boto3
        from botocore.config import Config

        s3 = boto3.client("s3", endpoint_url=os.environ["S3_ENDPOINT"], region_name="us-east-1",
                          aws_access_key_id=os.environ["S3_ACCESS_KEY"],
                          aws_secret_access_key=os.environ["S3_SECRET_KEY"],
                          config=Config(s3={"addressing_style": "path"}))
        day = Path(local_dir).name
        keys = []
        for f in sorted(Path(local_dir).iterdir()):
            content_type = "application/pdf" if f.suffix == ".pdf" else "text/html; charset=utf-8"
            key = f"{day}/{f.name}"
            s3.upload_file(str(f), "reports", key, ExtraArgs={"ContentType": content_type})
            keys.append(f"s3://reports/{key}")
        return keys

    freshness >> seed >> silver >> gold >> docs >> check >> render >> upload_reports(REPORTS_DIR)


px4_transform()
