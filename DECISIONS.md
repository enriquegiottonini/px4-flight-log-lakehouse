# Decision log

One entry per decision. Format: context → decision → consequences. Newer decisions supersede older ones and `DESIGN_PROPOSAL.md`.

## D-001: Ingestion runs inside the Airflow image (2026-10-13)

- **Context:** `task.txt` mentions an "API-Ubuntu" container for data acquisition. That container belongs to the instructor's reference example, not to the requirements.
- **Decision:** the `drone_ingest` package is installed in the Airflow image and runs as Airflow tasks. There is no separate Ubuntu container.
- **Consequences:** one service fewer. The presentation explains that the Airflow workers play the API-consumer role.

## D-002: Use the real PX4 Flight Review API contract (2026-10-13)

- **Context:** the proposal assumed a date-paginated REST API (`/v1/flights`, `/events`, `/telemetry`, `/drones`) with weather and battery fields. The real source has none of that.
- **Decision:** the source is the `dbinfo` index (`https://review.px4.io/dbinfo` → `https://cdn.logs.px4.io/dbinfo.json`, gzipped JSON, ~32 MB, ~476k records, 26 fields) plus one binary ULog per log (`download_url`).
- **Consequences:** marts that depended on weather or battery data in the index are dropped. Battery and altitude come only from ULog, and the gold layer is redesigned around fleet mix, flight modes, reliability and firmware.

## D-003: Daily index diff instead of a per-date API pull (2026-10-13)

- **Context:** the index is one full file, regenerated daily (~00:01 UTC). It supports `ETag` / `If-None-Match` → 304.
- **Decision:**
  - Download with a conditional GET; a 304 ends the run.
  - Keep the last 7 raw snapshots in landing. (Phase 10: a RustFS lifecycle rule expires them after 7 days, D-010.)
  - Make bronze append-only, inserting only records that are new or changed (`payload_hash`, anti-joined by `log_id`).
  - Limit the bootstrap to `log_date >= INDEX_START_DATE`.
  - Use `catchup=False`.
- **Consequences:** bronze grows by ~500 rows/day instead of 476k, keeps each log's metadata history and handles late uploads.

## D-004: Full ULog for every log, raw kept for 1 day (2026-10-13, revised after Phase 1)

- **Context:** telemetry (position, altitude, speed, battery) and logged messages exist only inside ULog files.
  - The Phase 1 measurement (200 HEAD requests) found a mean of **18 MB**, not 8 MB, and ~512 logs/day ≈ **9.3 GB/day**.
  - The development machine has ~13 GiB free.
- **Decision:** download and parse (with `pyulog`) every ULog uploaded during **one full UTC day**, the window `[ULOG_START_DATE, ULOG_END_DATE)` = `[today − 1, today)`. `log_date` is the upload date, so yesterday is complete once the day ends. Downsample to 1 Hz and extract `logged_messages` as events. Keep raw `.ulg` files for **1 day** (`ULOG_RETENTION_DAYS=1`).
- **Consequences:**
  - Landing holds at most ~9–10 GB of raw ULog.
  - `purge_expired_ulogs` runs before each day's downloads, so two days never coexist.
  - The `MIN_FREE_DISK_GB=3` guard aborts a batch that wouldn't fit.
  - Backfill runs one day at a time with purges in between.
  - Parsed telemetry (~40k rows/day) stays in Iceberg permanently.
  - Rejected alternatives: parse-then-delete (no raw copy kept) and sampling (not full coverage).
  - Phase 5: `PX4_MAX_ULOGS_PER_RUN` in `.env` caps downloads per run or day (empty = all, the D-004 default), for machines that can't hold a full day. `load-index` streams the index (`ijson`), using ~470 MB of RAM instead of ~2.6 GB.
  - **Revised in Phase 10 (D-010):** the 1-day retention is a RustFS lifecycle rule on `landing/px4/ulog/`, so `ULOG_RETENTION_DAYS`, `purge_expired_ulogs` and the backfill DAG are gone. Expiry is asynchronous (S3 semantics: an object becomes eligible a day after upload, and RustFS's scanner deletes it in the background), so two days can briefly coexist; the disk guard and the cap remain the safety net. Re-running a day is the `day` param of `px4_ingest_daily`.

## D-005: Vehicle catalog derived from the index (2026-10-13)

- **Context:** there is no drone catalog endpoint.
- **Decision:** build vehicles from `vehicle_uuid` + `sys_hw` + `airframe_*` + `ver_sw_release`, tracked with a dbt snapshot (SCD2).
- **Consequences:** logs without a `vehicle_uuid` (older uploads) have no vehicle dimension row.

## D-006: Fixtures from real data (2026-10-13)

- **Context:** the proposal planned invented JSON fixtures.
- **Decision:** fixtures are a 200-record excerpt of the real `dbinfo` + 3 small real ULogs + synthetic corrupt cases (invalid JSON, missing `log_id`, a truncated ULog, an edited `rating`).
- **Consequences:** tests exercise the real defects (mixed `airframe_type`, `wind_speed=-1`, dirty `rating`) and need no network.

## D-007: Lakekeeper as the Iceberg catalog (2026-10-13)

- **Context:** the proposal chose a JDBC catalog in Postgres and explicitly discarded Lakekeeper to avoid extra services.
- **Decision:** use Lakekeeper (`quay.io/lakekeeper/catalog:v0.14.0`, fallback `v0.13.6`) as an Iceberg REST catalog:
  - Its state lives in a `lakekeeper` Postgres database.
  - Warehouse `px4` on `s3://lakehouse/`.
  - No auth.
  - STS / vended credentials **on** (revised 2026-10-13, after Phase 3): RustFS supports STS `AssumeRole`, and the Lakekeeper web UI's DuckDB-WASM query engine (LoQE) can only read data with vended credentials. The warehouse endpoint is `http://rustfs.localhost:9000` (a compose network alias, and `*.localhost` → 127.0.0.1 in browsers), and `s3://lakehouse` gets a read-only CORS rule for the UI origin. Trino keeps its own static keys and `http://rustfs:9000`.
  - The UI's "Authentication is OFF" banner stays: it's shown whenever no OIDC provider is configured. Only the matching startup log line is filtered.
  - Phase 5: PyIceberg sends `client-managed` delegation and uses its own S3 endpoint and keys, like Trino. The warehouse endpoint `rustfs.localhost` is for browsers only, because curl-based S3 clients map `*.localhost` to loopback inside containers.
- **Consequences:**
  - Gains: a standard REST catalog shared by Trino and PyIceberg, and a web UI for warehouses, namespaces, tables and snapshots.
  - Costs: three more services (migrate, serve, bootstrap) and a young 0.x dependency. Phase 10 folded the bootstrap into the `setup` job (D-010): two containers remain.

## D-008: drone_ingest runs in its own virtualenv, called through its CLI (2026-10-14)

- **Context:** the Airflow 3.3.2 image ships pandas 3.0.5 / pyarrow 25 / pydantic 2.13, while `drone_ingest` is locked to pandas < 3 / pyarrow 26 (`uv.lock`).
- **Decision:**
  - Install `drone_ingest` into `/opt/ingest-venv` exactly from `uv.lock`.
  - DAGs call its CLI with `BashOperator`. Each command's final JSON summary line becomes the task's XCom.
  - dbt gets its own venv (`/opt/dbt-venv`) for the same reason.
- **Consequences:**
  - Airflow's own dependencies are never touched.
  - The same CLI runs on the host (`uv run drone-ingest …`) and in Airflow.
  - Tasks share files (plan files, downloads) through the `airflow-work` volume, which works because LocalExecutor runs every task in the scheduler container.

## D-009: dbt Charts inside the Airflow image, gated by execution (2026-10-15)

- **Context:** the plan had a separate `infrastructure/charts/Dockerfile`. Disk on the development machine is tight (the Airflow image alone is 4+ GB). Also, dbt Charts 0.9.1 can't statically check queries that use filter macros or variables, has no non-executing check for Trino, and `validate` ignores the query-level `ignore:` for that warning.
- **Decision:**
  - Install `dbt-charts[trino,server]==0.9.1` in a third venv of the Airflow image (`/opt/charts-venv`), with dbt-core/dbt-trino pinned like `/opt/dbt-venv`. The `charts` service runs that image with `dct serve`; `px4_transform` renders and uploads the reports.
  - Board queries alias every `ref()` and qualify every column, so boards without filters get the offline column-vs-model check.
  - `infrastructure/scripts/check_charts.py` is the publish gate: strict validation minus the one known limitation, plus executing every query with `dct render --format text`.
- **Consequences:**
  - No second image (+0.67 GB on the existing one).
  - One gate covers both kinds of boards, verified to fail on a broken column.
  - Filtered queries are verified by execution rather than statically, until a later dbt Charts version can analyze them.

## D-010: Simpler stack, native features instead of custom jobs (2026-10-15)

- **Context:** after Phase 9 the stack had 13 containers (8 services + 5 one-shot jobs). Some of our code did what the tools already do natively: purging old ULogs and pruning index snapshots (RustFS lifecycle), and four setup jobs each configured one thing once.
- **Decision:**
  - **8 containers.** Airflow runs as one container (`airflow standalone`: api-server, scheduler, dag-processor and triggerer; it migrates its own database). One idempotent `setup` job ([setup.py](infrastructure/setup/setup.py), Airflow image) replaces `rustfs-init`, `lakekeeper-bootstrap`, `trino-init` and `airflow-init`. `lakekeeper-migrate` stays: the distroless image's `serve` can't migrate.
  - **RustFS lifecycle rules** replace our purge code: `landing/px4/ulog/` 1 day, `landing/px4/index/` 7 days, `reports/` 30 days. Verified that the scanner physically deletes expired objects (a past-date rule removed its object within seconds).
  - **Lakekeeper soft delete** (7 days) on the warehouse: dropped tables are listed and restorable (UI → namespace → Deleted → Restore, or `POST …/deleted-tabulars/undrop` with `{"targets":[{"type":"table","id":…}]}`).
  - **dbt replaces tables in place** (`+on_table_exists: replace` → `CREATE OR REPLACE TABLE`), so every run is a new Iceberg snapshot of the same table: time travel across runs, and no dropped tables piling up in the soft-delete list. A project macro restores dbt-core's seed behavior (truncate + insert) over dbt-trino's always-drop, for the same reason.
  - **Removed:** the backfill DAG (now the `day` param of `px4_ingest_daily`), the `api_healthcheck` task (`snapshot_index` already retries and logs the failure), `audit.index_snapshots`, and the `px4_pool` pool (`max_active_tis_per_dagrun=4` instead).
  - **Not automated: protection.** Protecting the `gold` namespace protects nothing: Trino refuses to drop a non-empty schema by itself, and `DROP SCHEMA … CASCADE` drops the tables before Lakekeeper checks the namespace. *Table* protection works (DROP refused, including via CASCADE; `CREATE OR REPLACE` still allowed), but gold tables don't exist yet when `setup` runs on a clean clone. It stays a hands-on demo in the Lakekeeper UI.
- **Consequences:**
  - Fewer containers, less code (`drone_ingest` lost its purge, prune and healthcheck code), and `make up` needs no extra wait script: every one-shot job is a dependency of a service, so `docker compose up --wait` checks its exit code.
  - Each dbt build still soft-deletes 4 temporary objects in `silver` (three `__dbt_tmp` views of the incremental models and the snapshot's temp table). They expire by themselves after 7 days.
  - Airflow's processes share one container: a crash restarts all of them. Acceptable for a single-laptop prototype.
  - The Airflow image bakes in `drone_ingest`, so `make up` builds (cached) on every start. Without that, the containers silently kept the pre-Phase 10 package (CLAUDE.md, Phase 10 finding 8).
