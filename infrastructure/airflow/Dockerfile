# Airflow 3 + two isolated virtualenvs, so neither can break Airflow's pinned dependencies
# (Airflow ships pandas 3 / pyarrow 25; drone_ingest is locked to pandas < 3 / pyarrow 26):
#   /opt/ingest-venv  drone_ingest, installed exactly from ingest/uv.lock (DAGs call its CLI)
#   /opt/dbt-venv     dbt-trino (used from Phase 6)
# Build context: repo root (see /.dockerignore).
ARG AIRFLOW_TAG=3.3.2-python3.12
FROM ghcr.io/astral-sh/uv:0.12.6 AS uv

FROM apache/airflow:${AIRFLOW_TAG}
ARG AIRFLOW_VERSION=3.3.2
ARG PYTHON_VERSION=3.12

# Providers in Airflow's own environment, pinned by Airflow's official constraints file
RUN pip install --no-cache-dir "apache-airflow==${AIRFLOW_VERSION}" "apache-airflow-providers-trino" \
      --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_VERSION}.txt"

USER root
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON=/usr/local/bin/python UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy UV_NO_CACHE=1

# drone_ingest: exact versions from uv.lock, installed as a regular (non-editable) package
COPY ingest/pyproject.toml ingest/uv.lock /opt/drone_ingest/
COPY ingest/src /opt/drone_ingest/src
RUN cd /opt/drone_ingest \
 && UV_PROJECT_ENVIRONMENT=/opt/ingest-venv uv sync --frozen --no-dev --no-editable --compile-bytecode \
 && /opt/ingest-venv/bin/drone-ingest --help > /dev/null

# dbt (Phase 6): adapter + core pinned to the same minor version
RUN uv venv /opt/dbt-venv \
 && uv pip install --python /opt/dbt-venv/bin/python "dbt-trino==1.10.6" "dbt-core==1.10.23" \
 && /opt/dbt-venv/bin/dbt --version

# Work dir for drone_ingest (downloads, plan files). A new named volume mounted here copies this
# directory (ownership included) on first use; .keep makes sure the copy happens.
RUN mkdir -p /opt/airflow/work && touch /opt/airflow/work/.keep && chown -R airflow:root /opt/airflow/work

USER airflow
