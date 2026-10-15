# PX4 flight-log lakehouse

A local lakehouse, in Docker Compose, built on the **public PX4 Flight Review logs** (review.px4.io):
- **Airflow** downloads the daily log index and the flight logs (ULog).
- The data lands in **RustFS** (S3) as **Apache Iceberg** tables, catalogued by **Lakekeeper**.
- **dbt** builds silver and gold layers on **Trino**.
- **dbt Charts** serves dashboards and publishes HTML/PDF reports.

Everything runs on one laptop (8 GB RAM for Docker), and every step is visible in the Airflow UI.

> Class project: *prototipo con Docker, API y bases de datos* (`definition/task.txt`). Build log and per-phase details: [CLAUDE.md](CLAUDE.md). Decisions: [DECISIONS.md](DECISIONS.md). Original design: [DESIGN_PROPOSAL.md](DESIGN_PROPOSAL.md). Class presentation: [presentation/](presentation/).

## Architecture

```text
 PX4 Flight Review (dbinfo.json.gz index, *.ulg flight logs)
          │ HTTP (conditional GET, polite retries)
          ▼
 ┌──────────── Airflow 3 (standalone, LocalExecutor) ────────────────────────────┐
 │ px4_ingest_daily ─(bronze assets)─▶ px4_transform: dbt silver → gold (Cosmos)   │
 │   drone_ingest CLI (own venv)          → check_charts → render → s3://reports   │
 └──────┬──────────────────────────────────────────┬──────────────────────────────┘
        │ S3 + PyIceberg                           │ SQL (dbt-trino)
        ▼                                          ▼
 RustFS (S3) ◀──── Parquet + Iceberg metadata ──── Trino ◀──── dbt Charts (dct serve)
 landing/ lakehouse/ reports/                       │ Iceberg REST
        ▲                                           ▼
        └──────────── PostgreSQL ◀────────────── Lakekeeper (catalog, warehouse px4)
```

**8 containers:** 6 services and 2 one-shot jobs. `make up` waits until the services are healthy and the jobs have exited 0.

| Container | Role | Host port |
| --- | --- | --- |
| `postgres` | Databases for Airflow and Lakekeeper (one role each) | 5432 |
| `rustfs` | S3 object storage: `landing` (raw API files), `lakehouse` (Iceberg), `reports` | 9000 API, 9001 [console](http://localhost:9001/rustfs/console/) |
| `lakekeeper-migrate` | One-shot: creates/upgrades Lakekeeper's tables in Postgres | — |
| `lakekeeper` | Iceberg REST catalog + [web UI](http://localhost:8181/ui/) (table previews run DuckDB in the browser) | 8181 |
| `setup` | One-shot, idempotent ([setup.py](infrastructure/setup/setup.py)): buckets, lifecycle rules, CORS, warehouse with soft delete, namespaces, dbt packages | — |
| `trino` | The SQL engine for dbt, dashboards and you ([UI](http://localhost:8085/ui/)) | 8085 |
| `airflow` | All of Airflow (`airflow standalone`): UI/API, scheduler, DAG processor, triggerer ([UI](http://localhost:8080), no login) | 8080 |
| `charts` | dbt Charts live dashboards ([fleet overview](http://localhost:8088/fleet_overview/)) | 8088 |

Start order: postgres → lakekeeper-migrate → lakekeeper → setup (+ rustfs) → trino → airflow, charts. An `aws` CLI container runs only on demand (`make s3`, `make lifecycle`).

Every port is bound to `127.0.0.1`. There is no authentication (local toy stack, by design).

## Quick start

Requirements:
- Docker Desktop with **≥ 8 GB RAM** and **≥ 20 GB disk** (Settings → Resources).
- `make`.
- Internet access for the PX4 API.
- `uv`, optional: only for the host-side unit tests.

```bash
make env      # .env with random secrets (never commit it)
make up       # builds the Airflow image the first time (~5 min), then waits until everything is healthy
```

Then open http://localhost:8080. All DAGs start **paused**, so nothing downloads until you choose:

1. **Set a download cap first.** `PX4_MAX_ULOGS_PER_RUN` in `.env` (e.g. `25`), then `make up`. Empty means every log of the day (~500 files, ~9 GB, D-004).
2. **Unpause `px4_transform`.** It runs by itself whenever bronze gets new data.
3. **Unpause `px4_ingest_daily`, or trigger it with `{"max_ulogs": 20}`.** Unpausing immediately runs the latest missed 02:00 slot. Any other upload day: `{"day": "2026-10-10", "max_ulogs": 20}`.

About 3 minutes later, the boards at http://localhost:8088 show the new data, and `s3://reports/<day>/` holds the HTML/PDF reports.

## Pipeline

| DAG | When | What |
| --- | --- | --- |
| `px4_ingest_daily` | 02:00 America/Hermosillo | Conditional GET of the index (a 304 skips the load) → diff-load new/changed records into `bronze.logs_index_raw` → fetch + parse one upload day's ULogs (yesterday, or the `day` param) into `bronze.telemetry_raw` / `bronze.log_messages_raw` |
| `px4_transform` | when a bronze asset updates | `source freshness` → seeds → silver models (each = run + test task) → gold marts (enforced contracts) → docs → dashboard check → HTML/PDF render → upload to `s3://reports` |
| `px4_maintenance` | Sundays 03:00 | `optimize`, `expire_snapshots(7d)` and `remove_orphan_files(7d)` on every Iceberg table |

Data layers (CLAUDE.md section 6):
- **landing:** raw index snapshots and `.ulg` files.
- **bronze:** raw records, append-only, with audit columns.
- **silver:** cleaned and typed staging tables, an SCD2 vehicle snapshot, dimensions and facts (`fct_flight`, …).
- **gold:** 9 marts with enforced contracts, read by the dashboards.

## Native features, configured once

The `setup` job configures what a person would otherwise set by hand in each tool, so no DAG has to do it:

| Feature | Tool | Replaces | See it |
| --- | --- | --- | --- |
| **Lifecycle rules:** `landing/px4/ulog/` expires after 1 day, `landing/px4/index/` after 7, `reports/` after 30 | RustFS | a purge task and snapshot pruning in our code | `make lifecycle` |
| **Soft delete:** a dropped table stays recoverable for 7 days (also after `DROP SCHEMA … CASCADE`) | Lakekeeper | backups | Lakekeeper UI → namespace → **Deleted** → Restore |
| **Table history:** each dbt run replaces gold tables *in place* (`on_table_exists: replace`), so every run is a new Iceberg snapshot of the same table | dbt-trino + Iceberg | drop-and-recreate (history lost every run) | `SELECT * FROM gold."mart_flights_by_class_month$snapshots"`; Lakekeeper UI → table → **Versioning** |

Two more you can turn on by hand, live:
- **Table protection** (Lakekeeper UI → table → Settings → protection): `DROP TABLE` is then refused, also through `DROP SCHEMA … CASCADE`, while dbt's `CREATE OR REPLACE` keeps working.
- **Time travel:** `SELECT … FROM gold.mart_flights_by_class_month FOR VERSION AS OF <snapshot_id>`.

```bash
make trino SQL="DROP TABLE gold.mart_flight_envelope"   # oops
# Lakekeeper UI → px4 → gold → Deleted → Restore; then:
make trino SQL="SELECT count(*) FROM gold.mart_flight_envelope"
```

## Common commands

```bash
make help                      # every target
make ps | make logs S=trino    # status / follow one service's logs
make trino SQL="SELECT vehicle_class, sum(logs) FROM gold.mart_flights_by_class_month GROUP BY 1"
make airflow ARGS="dags list"
make dbt ARGS="build -s +fct_flight"
make charts-check              # validate + render every dashboard (the publish gate)
make s3 ARGS="ls --recursive s3://reports/"
make lifecycle                 # the RustFS rules that expire old files
make test                      # drone_ingest unit tests (fixtures only, no network)
make down                      # stop, keep data · make reset: stop and DELETE all data
```

## Configuration (`.env`)

| Variable | Default | Meaning |
| --- | --- | --- |
| `PX4_INDEX_START_DATE` | `2025-01-01` | Bronze ignores index records uploaded before this date |
| `PX4_MAX_ULOGS_PER_RUN` | empty (all) | Cap on ULog downloads per run/day; set it on a small disk |
| `*_TAG` | pinned | Image versions (CLAUDE.md section 5) |
| secrets | generated by `make env` | Postgres roles, S3 keys, Lakekeeper encryption key, Airflow Fernet/JWT keys |

## Smoke test

`infrastructure/scripts/smoke_test.sh` checks the whole flow:
- `make up`;
- exactly 8 containers;
- a capped ingestion run (`SMOKE_MAX_ULOGS`, default 20), waiting for every asset-triggered transform run to succeed;
- gold tables are non-empty, silver caught up with bronze, and all 8 reports are in `s3://reports/<day>/`.

It exits 0 when everything works.

**From a clean clone, without touching your stack's data:** `make down` first (your volumes are kept; the ports must be free), then:

```bash
git clone <repo> /tmp/px4-smoke && cd /tmp/px4-smoke
make env && sed -i '' 's/^PX4_MAX_ULOGS_PER_RUN=.*/PX4_MAX_ULOGS_PER_RUN=20/' .env
echo 'COMPOSE_PROJECT_NAME=px4-smoke' >> .env      # separate containers and empty volumes
infrastructure/scripts/smoke_test.sh
docker compose down -v                              # delete only the smoke project's volumes
```

Then `make up` in your checkout. The script refuses to run when `PX4_MAX_ULOGS_PER_RUN` is empty, because unpausing the daily DAG on a fresh database would download a full day.

## Troubleshooting

- **Every port times out:** Docker Desktop may be *paused* (whale menu → Resume).
- **Disk:** raw ULogs are ~9 GB/day. RustFS's lifecycle rule deletes them after a day (its scanner works in the background, not at an exact time). The `MIN_FREE_DISK_GB` guard aborts a download that wouldn't fit, and `PX4_MAX_ULOGS_PER_RUN` caps it. `docker builder prune` reclaims build cache.
- **Lakekeeper UI "Data not readable in the browser":** the in-browser DuckDB reads S3 through `rustfs.localhost:9000`. Chrome and Firefox resolve `*.localhost` by themselves; other browsers need `127.0.0.1 rustfs.localhost` in `/etc/hosts`. The red "Authentication is OFF" banner is expected.
- **A DAG doesn't appear:** `make airflow ARGS="dags list-import-errors"`.
- More gotchas, per phase: the *Findings and gotchas* lists in [CLAUDE.md](CLAUDE.md).
