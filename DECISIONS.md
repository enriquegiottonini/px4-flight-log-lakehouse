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
  - Keep the last 7 raw snapshots in landing.
  - Make bronze append-only, inserting only records that are new or changed (`payload_hash`, anti-joined by `log_id`).
  - Limit the bootstrap to `log_date >= INDEX_START_DATE`.
  - Use `catchup=False`.
- **Consequences:** bronze grows by ~500 rows/day instead of 476k, keeps each log's metadata history and handles late uploads.

## D-004: Full ULog for every log, raw kept for 1 day (2026-10-13, revised after Phase 1)

- **Context:** telemetry (position, altitude, speed, battery) and logged messages exist only inside ULog files.
  - The Phase 1 measurement (200 HEAD requests) found a mean of **18 MB**, not 8 MB, and ~512 logs/day ≈ **9.3 GB/day**.
  - The development machine has ~13 GiB free.
- **Decision:** download and parse (with `pyulog`) every ULog uploaded in the last day (`ULOG_START_DATE` = today − 1). Downsample to 1 Hz and extract `logged_messages` as events. Keep raw `.ulg` files for **1 day** (`ULOG_RETENTION_DAYS=1`).
- **Consequences:**
  - Landing holds at most ~9–10 GB of raw ULog.
  - `purge_expired_ulogs` runs before each day's downloads, so two days never coexist.
  - The `MIN_FREE_DISK_GB=3` guard aborts a batch that wouldn't fit.
  - Backfill runs one day at a time with purges in between.
  - Parsed telemetry (~40k rows/day) stays in Iceberg permanently.
  - Rejected alternatives: parse-then-delete (no raw copy kept) and sampling (not full coverage).

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
- **Consequences:**
  - Gains: a standard REST catalog shared by Trino and PyIceberg, and a web UI for warehouses, namespaces, tables and snapshots.
  - Costs: three more services (migrate, serve, bootstrap) and a young 0.x dependency.
