"""Shared pieces of the PX4 DAGs.

Airflow only decides what runs when. The work is done by the drone_ingest CLI, installed in its
own virtualenv in the image (/opt/ingest-venv), so its dependencies never clash with Airflow's.
Each CLI command prints one JSON summary line last; BashOperator pushes that line to XCom.
"""

from __future__ import annotations

import json
import os
from datetime import timedelta

import pendulum
from airflow.sdk import Asset, Variable

INGEST = "/opt/ingest-venv/bin/drone-ingest"
TZ = "America/Hermosillo"
START = pendulum.datetime(2026, 10, 1, tz=TZ)
INDEX_URL = "https://review.px4.io/dbinfo"

# Data-aware scheduling: the transform DAG (Phase 7) runs when these tables get new data
LOGS_INDEX = Asset("iceberg://px4/bronze/logs_index_raw")
TELEMETRY = Asset("iceberg://px4/bronze/telemetry_raw")
LOG_MESSAGES = Asset("iceberg://px4/bronze/log_messages_raw")

# Container default (PX4_MAX_ULOGS_PER_RUN in .env), shown as the param default in the trigger form.
# Params always set the CLI env, so the default must come from here or it would override the cap.
DEFAULT_MAX_ULOGS = int(v) if (v := os.environ.get("MAX_ULOGS_PER_RUN", "").strip()) else None

# The run's day (UTC) as a Jinja expression. Airflow 3 manual runs have no logical date: `ds` and
# `logical_date` are missing from their context. dag_run.run_after (due/trigger time) always exists.
RUN_DAY = "(dag_run.logical_date or dag_run.run_after) | ds"

# Per-run knobs from DAG params -> environment of the CLI (container env is kept: append_env)
INGEST_ENV = {
    "INDEX_URL": "{{ params.index_url }}",
    "MAX_ULOGS_PER_RUN": "{{ params.max_ulogs if params.max_ulogs is not none else '' }}",
}


def _retry_delay() -> timedelta:
    """Base delay for exponential retries. An Airflow Variable, so a test can shorten it from
    the UI or CLI (airflow variables set px4_retry_delay_seconds 5) without a restart."""
    try:
        return timedelta(seconds=int(Variable.get("px4_retry_delay_seconds", default=120)))
    except Exception:  # Variable store unreachable while parsing: use the default
        return timedelta(seconds=120)


DEFAULT_ARGS = {
    "owner": "px4",
    "retries": 3,
    "retry_delay": _retry_delay(),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=30),
}


def cli(command: str) -> str:
    """Templated bash command for one drone-ingest subcommand."""
    return f"{INGEST} --run-id '{{{{ run_id }}}}' {command}"


def summary(xcom_line: str) -> dict:
    return json.loads(xcom_line)
