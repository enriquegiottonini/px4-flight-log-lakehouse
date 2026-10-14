# CLAUDE.md: PX4 Flight-Log Lakehouse

This file is the project's **build plan** and the **working rules** for Claude Code.
- Original design: `DESIGN_PROPOSAL.md` (architecture still applies; section 3 here replaces its API contract).
- Assignment: `definition/task.txt`.
- Instructor's reference example: `definition/dash-mysql/`.
- Decision log: `DECISIONS.md` (one entry per decision, format D-NNN).

## 1. Working rules (for Claude)

- Build **phase by phase** (section 7). Never start a phase while any checklist item in the previous one is red.
- When a phase closes: commit + `git tag phase-N`, so the evolution can be inspected with `git diff phase-2 phase-3 -- infrastructure/`.
- **Pin every version** (section 5). If a version breaks, pin the previous one before switching tools, and log it in `DECISIONS.md`.
- Secrets only in `.env` (with a versioned `.env.example`). No credentials in YAML, DAGs or `profiles.yml`.
- Code, docs and comments in English, with `snake_case` table and column names. Presentation material may be in Spanish.
- Before any bulk ULog download (> 2 GB), show the size estimate and ask for confirmation.
- Be polite to PX4: follow the retry and backoff rules of `download_logs.py` (section 3.4), use bounded concurrency and an identifiable User-Agent.
- Must run on an 8 GB RAM machine: Trino with `-Xmx2G`, Airflow with `LocalExecutor`.

## 2. Mapping to the assignment (`task.txt`)

| Assignment requirement | How it is met here |
| --- | --- |
| Data acquisition via an API ("API-Ubuntu" container in the example) | The `drone_ingest` package, inside the Airflow image, consumes the public PX4 Flight Review API (`dbinfo` index + ULog files). See D-001. |
| Storage in a DBMS | Apache Iceberg tables on RustFS (S3), catalogued by **Lakekeeper** (Iceberg REST catalog) whose state lives in **PostgreSQL**; Trino is the SQL engine. |
| Visualization (Dash suggested) | dbt Charts (`dct serve`) over the gold tables via Trino. |
| Containerization (≥ 2 containers) | Docker Compose with ~13 services (section 5). |
| Integration API → DB → visualization | Airflow DAGs chained by *assets*; `infrastructure/scripts/smoke_test.sh` checks the full flow. |
| Class presentation | Script and checklist in Phase 9. |

## 3. Real data source: PX4 Flight Review

PX4 is the most widely used open-source drone autopilot. Flight Review (`review.px4.io`) is where pilots and developers upload public flight logs. The `/browse` page lists them (Uploaded, Type, Airframe, Hardware, Software, Duration, Start Time, Flight Modes), and the official script `app/download_logs.py` documents automated downloading.

**Problem statement for the presentation:** how is the PX4 fleet used in the real world, and how reliable is it? Which vehicle types fly most, in which modes and on which firmware? Which ones report failures or crashes? What does telemetry (altitude, speed, battery drain) say per vehicle type?

### 3.1 Endpoints

| Endpoint | Returns | Notes |
| --- | --- | --- |
| `GET https://review.px4.io/dbinfo` | 302 → `https://cdn.logs.px4.io/dbinfo.json` | **gzipped** JSON, ~32 MB, list of ~476k records (the full history). No pagination or filters: always downloaded in full. **Regenerated once a day (~00:01 UTC)**. Sends `ETag`/`Last-Modified` and answers `If-None-Match` with **304** (no body). |
| `GET https://cdn.logs.px4.io/<log_id>.ulg` (`download_url`) | Binary ULog file: median 6.5 MB, **mean 18 MB**, p95 89 MB, max ~150 MB (Phase 1 sample of 200) | Served by S3/CloudFront. Preferred over `/download`. |
| `GET https://review.px4.io/download?log=<log_id>` | Same ULog through the app | Rate-limited: 503 + `Retry-After`; 403/444 means blocked. Fallback only. |

### 3.2 Index record (as received)

```json
{
  "log_id": "60f0a65f-fea3-46cc-b8db-23ac20adb24c",
  "log_date": "2026-06-12",
  "description": "…", "feedback": "…", "type": "flightreport",
  "wind_speed": -1, "rating": "", "video_url": "",
  "error_labels": [], "source": "webui",
  "duration_s": 204, "mav_type": "Quadrotor", "estimator": "EKF2",
  "sys_autostart_id": 4014, "sys_hw": "AMOVLAB_FLYCORE",
  "ver_sw": "b6527873…", "ver_sw_release": "v1.18.0 64",
  "num_logged_errors": 0, "num_logged_warnings": 0,
  "flight_modes": [2], "flight_mode_durations": [[2, 204]],
  "vehicle_uuid": "0006000000003335…", "vehicle_name": "",
  "airframe_name": "S500 Generic", "airframe_type": "Quadrotor x",
  "download_url": "https://cdn.logs.px4.io/60f0a65f-….ulg"
}
```

### 3.3 Known defects (what silver must clean)

- `airframe_type`: a string in ~74 % of records, an **int** in ~26 % (the `SYS_AUTOSTART` ID when the airframe is unrecognized).
- `wind_speed = -1` means "no data" (~95 %).
- `rating`: empty in ~95 %, with junk values `BRAVO!`/`BRAWO!`/`1`/`none`. Business values are `good`, `great`, `unsatisfactory`, `crash_sw_hw`, `crash_pilot`.
- Empty strings instead of nulls (`vehicle_name`, `vehicle_uuid`, `ver_sw_release`, …).
- `flight_modes` and `error_labels` are IDs. `flight_mode_durations` is a time-ordered list of `[mode_id, seconds]` pairs.
- `mav_type` has 15+ values: `Quadrotor` (68 %), `Hexarotor`, `Fixed Wing`, `VTOL Standard`, …, `unknown type`.
- **`log_date` is the upload date, not the flight date.** One sampled log uploaded 2026-10-13 flew on 2026-01-27. The real flight start exists only inside the ULog (GPS `time_utc_usec`); Flight Review computes it, but the public index doesn't include it. Silver renames the field to `uploaded_date`.
- **Simulated flights:** ~6–7 % of recent logs come from simulators (`sys_hw` contains `SITL`: `PX4_SITL`, `SITL`, `AMOVLAB_SITL`, …). Silver adds `is_simulation`, and gold excludes them by default.
- **`duration_s` overflow:** 25 values > 1 day (up to 1.8e13 s, unsigned counters that wrapped around) and 7,414 values ≤ 0. Values outside 1–86,400 s become null.
- **`flight_mode_durations` overflow:** 1,056 segments with impossible lengths, and 426 logs whose segments add up to more than `duration_s`. Segments > `duration_s` become null.
- **Mode IDs missing from the lookup table:** 7, 9, 11, 16, 31, 32, 42, 63, 72, 73, 80, 112, 187, 192, 255. The seed maps them to `Unknown (<id>)`.
- `airframe_type` int **always** equals `sys_autostart_id`, and `airframe_name` is empty for exactly those 122,768 records.
- `ver_sw_release` `v0.0.x` (5,910 records) means a dev build, so it's treated as unknown. `estimator` contains `unknown (None)`.
- `mav_type` has 24 values, including `VTOL reserved 3/4/5`, `Rocket`, `Submarine` and `Generic`. Classes come from the `mav_type_classes` seed.
- Volume: median **~590 logs/day** (p95 858, max 1,052) over the last 90 days; 314,800 logs since 2025-01-01.

ULog defects (from the 3 inspected files; full report in `explore/reports/ulog_inspection.md`):
- **Topics vary by firmware/hardware:** `battery_status`, `vehicle_air_data` or the GPS topics can be missing. The parser emits a null column and counts the gap.
- **Battery stuck at 0** (no sensor): if `max(remaining) == 0`, treat battery as null.
- **Timestamps are µs since boot.** UTC comes from `vehicle_gps_position.time_utc_usec` when a GPS fix exists; otherwise `ts_utc` is null and only `t_boot_s` is kept.
- **A truncated file parses without error** (`pyulog` reports `file_corruption=False`). The only reliable check is downloaded size == `Content-Length`.
- Logged messages carry trailing tabs/whitespace; strip them.

Lookup tables (from `plot_app/config_tables.py`; they become dbt *seeds*):
- `flight_modes`: 0 Manual, 1 Altitude, 2 Position, 3 Mission, 4 Loiter, 5 Return to Land, 6 Position (Slow), 8 Altitude Cruise, 10 Acro, 12 Descend, 13 Terminate, 14 Offboard, 15 Stabilized, 17 Takeoff, 18 Land, 19 Follow Target, 20 Precision Land, 21 Orbit, 22 VTOL Takeoff, 23–30 External 1–8.
- `error_labels`: 1 Other, 2 Vibration, 3 Airframe-design, 4 Sensor-error, 5 Component-failure, 6 Software, 7 Human-error, 8 External-conditions.
- `vtol_modes`: 1 Transition, 2 Fixed-Wing, 3 Multicopter.

### 3.4 Politeness rules (inherited from `download_logs.py`)

- 503 → wait `Retry-After`, or `30·2^attempt` s (max 300).
- 403/444 → **abort the whole run** (we've been blocked).
- 404 → skip the log and record it as rejected.
- Other errors → retry, up to 5 attempts.
- Stream downloads in chunks; never re-download what is already in landing (idempotent by `log_id`).

### 3.5 Quick exploration (no Docker)

```bash
curl -sSL https://review.px4.io/dbinfo -o dbinfo.json.gz        # follows the 302
python -c "import gzip,json;d=json.load(gzip.open('dbinfo.json.gz'));print(len(d), d[0].keys())"
curl -sSI https://cdn.logs.px4.io/<log_id>.ulg | grep -i content-length
pip install pyulog==1.2.4 && ulog_info <file>.ulg && ulog_messages <file>.ulg
```

## 4. Changes to `DESIGN_PROPOSAL.md` after reviewing the source

| Topic | Original proposal | Now | Decision |
| --- | --- | --- | --- |
| Ingestion container | — (implicit in Airflow) | `drone_ingest` lives in the Airflow image; the assignment's "API-Ubuntu" is only the example | D-001 |
| API contract | Date-paginated REST (`/v1/flights`, `/events`, `/telemetry`, `/drones`) | Full `dbinfo` index + one ULog per log | D-002 |
| Ingestion semantics | One API day per run, `catchup=True` | The full index is re-published daily, so ingestion is a **diff**, not a re-load (see "Daily index diff" below). `catchup=False`. | D-003 |
| Telemetry | 1 Hz API | **Full ULog for every log in the window**, parsed with `pyulog` and downsampled to 1 Hz | D-004 |
| Events | `/events` | `logged_messages` inside the ULog (level + text) | D-004 |
| Drone catalog | `/v1/drones` | Derived from `vehicle_uuid` + `sys_hw` + `airframe_*` + `ver_sw_release`, with SCD2 via a snapshot | D-005 |
| Weather / battery in the index | Assumed | Not present. `wind_speed` is almost always empty; battery comes only from ULog. Marts that depended on them are dropped. | D-002 |
| Iceberg catalog | JDBC catalog inside Postgres (Lakekeeper explicitly discarded) | **Lakekeeper** REST catalog (`v0.14.0`; fallback `v0.13.6`) backed by a `lakekeeper` Postgres db. Gives a standard REST API that Trino, PyIceberg and any other engine share, a web UI at `:8181/ui`, and warehouse/namespace management. Costs: +3 services (migrate, serve, bootstrap) and a young 0.x project. | D-007 |
| Fixtures | Invented JSON | Real `dbinfo` excerpt (200 records) + 3 small real ULogs + synthetic corrupt cases | D-006 |
| Open questions | Auth / rate limits | Resolved: no auth; rate limit only on `/download`; we use the CDN | — |

**Daily index diff (D-003).** Each daily file is yesterday's file plus ~500–600 new logs, and occasionally an edited one (e.g. a `rating` added later):
1. **Conditional GET**: send the last stored ETag (`audit.index_snapshots`) as `If-None-Match`. A 304 ends the run as "no new data" and downloads 0 bytes.
2. **Landing keeps the raw gz** for audit, but only the last `INDEX_SNAPSHOT_RETENTION=7` snapshots (~225 MB).
3. **Bronze is append-only and stores only changes**: compute `payload_hash = sha256(canonical JSON)` per record and anti-join against bronze's latest hash per `log_id`. Insert rows that are **new** (`_change_type='insert'`) or **changed** (`_change_type='update'`). Bronze grows by ~500 rows/day instead of 476k, and keeps each log's metadata history.
4. **First run (bootstrap)** inserts only records with `log_date >= INDEX_START_DATE` (default `2025-01-01`, ~200k rows, a few seconds). Widening the window later just re-diffs.
5. **ULogs** are fetched once per `log_id` (anti-join with `audit.ulog_downloads`). Their window is **one full UTC day of uploads, `[ULOG_START_DATE, ULOG_END_DATE)`**, default `[today − 1, today)` (D-004). It's independent of the index window. Because `log_date` is the upload date, new `log_id`s always appear under recent dates.

**Disk budget (D-004), measured in Phase 1** (`explore/reports/ulog_sizes.md`): ~512 logs/day × **18 MB mean** ≈ **9.3 GB/day** of raw ULog.
- A 7-day window would be ≈ 65 GB, but the development machine has ~13 GiB free. **Decision (D-004, revised): keep raw ULogs for a 1-day window only.**
- Window `[today − 1, today)` and `ULOG_RETENTION_DAYS=1`: landing holds at most one day of `.ulg` files (~9–10 GB). With `log_date >= today − 1`, today's partial uploads would also be fetched, so ~1.4 days would coexist.
- **Purge before fetch:** `purge_expired_ulogs` runs *before* the day's downloads, so two days never coexist (that would be ~18 GB).
- **Free-disk guard:** before each batch, `fetch-ulogs` checks free space on the RustFS volume. It aborts with a clear error if free space minus the batch's summed `Content-Length` would drop below `MIN_FREE_DISK_GB=3`.
- **Backfill** processes one day at a time and purges between days, so the peak never exceeds one day.
- Parsed telemetry lives in Iceberg and is **not** purged: ~40–90 rows per log at 1 Hz ≈ 40k rows/day, so telemetry history keeps growing even though raw files rotate.
- Docker Desktop keeps volumes inside its VM disk image (Settings → Resources → disk limit). It must allow ≥ 20 GB.
- Knobs: `ULOG_START_DATE`, `ULOG_END_DATE`, `ULOG_RETENTION_DAYS`, `MIN_FREE_DISK_GB`, `ULOG_MAX_BYTES` (larger logs → `rejected`, reason `too_large`), `MAX_ULOGS_PER_RUN` (empty = all; useful during development).

## 5. Architecture and services

```text
 PX4 Flight Review (dbinfo.json.gz, *.ulg)
          │  HTTP (drone_ingest, inside Airflow)
          ▼
 ┌────────────── Airflow 3 (apiserver, scheduler, dag-processor) ──────────────┐
 │ px4_ingest_daily ──asset bronze.*──▶ px4_transform (Cosmos: dbt silver/gold)  │
 └───────┬───────────────────────────────────────┬─────────────────────────────┘
         │ S3 (boto3) / PyIceberg                │ SQL (dbt-trino)
         ▼                                       ▼
 RustFS (S3) ◀────── Parquet / metadata files ───── Trino (1 node) ◀── dbt Charts (dct serve)
   landing/ lakehouse/ reports/                      │
         ▲                                           │ Iceberg REST (http://lakekeeper:8181/catalog)
         │            PyIceberg RestCatalog ───────▶ Lakekeeper (warehouse "px4" → s3://lakehouse/)
         │                                           │
         └──────────── PostgreSQL (dbs: airflow, lakekeeper) ◀┘
```

**Catalog wiring (Lakekeeper):**
- `lakekeeper-migrate` (`migrate`) creates the schema in the `lakekeeper` db, then `lakekeeper` (`serve`, port 8181) starts.
- `lakekeeper-bootstrap` (curl image, run once: `infrastructure/lakekeeper/bootstrap.sh`) does two POSTs:
  - `POST /management/v1/bootstrap` with `{"accept-terms-of-use": true}` → `204`. A later call → `400 CatalogAlreadyBootstrapped`, treated as success.
  - `POST /management/v1/warehouse` → `201`, skipped if `px4` already exists. Body: warehouse `px4`, `storage-profile` `{type: s3, bucket: lakehouse, endpoint: http://rustfs.localhost:9000, region: us-east-1, path-style-access: true, flavor: s3-compat, sts-enabled: true, sts-endpoint: <same>, remote-signing-enabled: false}` and an access-key `storage-credential`.
  - The JSON is built in the script from env vars, so no S3 secret is committed. `project-id` is deprecated in v0.14 and omitted (the default project is used).
  - Lakekeeper validates the storage on creation (writes and deletes a test object), so a `201` proves Lakekeeper → RustFS works.
- `trino-init` (Trino CLI, run once: `infrastructure/trino/init/init-schemas.sql`) creates `bronze`, `silver`, `gold` and `audit` with **explicit locations** `s3://lakehouse/<layer>`. Otherwise Lakekeeper defaults every namespace to the warehouse root, and tables from all layers would end up side by side.
- Secrets in `.env`: `LAKEKEEPER_ENCRYPTION_KEY` (→ `LAKEKEEPER__PG_ENCRYPTION_KEY`; keep it stable, it decrypts the stored S3 keys) and `LAKEKEEPER_DB_PASSWORD` (→ `LAKEKEEPER__PG_DATABASE_URL_READ` / `_WRITE`).
- No OIDC: auth is disabled (local toy), in line with the proposal's "no auth" non-goal.
  - The startup log warning is filtered with `RUST_LOG=info,lakekeeper::service::authn=error`.
  - The web UI's red banner ("Authentication is OFF") can't be hidden: the server injects `__lkauth='false'` into the page, and the banner shows whenever auth isn't configured.
- **STS / vended credentials are on** (D-007, revised), so the web UI's **LoQE** (Local Query Engine, DuckDB-WASM in the browser) can read tables, e.g. the table PREVIEW tab:
  - RustFS supports STS `AssumeRole`. Lakekeeper vends short-lived keys + session token, scoped to the table's prefix.
  - **Endpoint `http://rustfs.localhost:9000`** works in both places: containers resolve it through a compose network alias on `rustfs`, and browsers (Chrome/Firefox) resolve `*.localhost` to 127.0.0.1 → published port 9000.
  - **CORS:** `rustfs-init` puts a read-only (GET/HEAD) CORS rule on `s3://lakehouse` for `http://localhost:8181` / `http://127.0.0.1:8181`.
  - Trino doesn't ask for vended credentials (`vended-credentials-enabled=false`): it keeps its own keys and `http://rustfs:9000`. PyIceberg can do either.

`infrastructure/trino/catalog/iceberg.properties` (replaces the proposal's JDBC block; names verified against Trino 483, which uses **`fs.s3.enabled`**, not `fs.native-s3.enabled`):

```properties
connector.name=iceberg
iceberg.catalog.type=rest
iceberg.rest-catalog.uri=http://lakekeeper:8181/catalog
iceberg.rest-catalog.warehouse=px4
iceberg.rest-catalog.vended-credentials-enabled=false
iceberg.file-format=PARQUET
iceberg.compression-codec=ZSTD
fs.s3.enabled=true
s3.endpoint=http://rustfs:9000
s3.region=us-east-1
s3.path-style-access=true
s3.aws-access-key=${ENV:S3_ACCESS_KEY}
s3.aws-secret-key=${ENV:S3_SECRET_KEY}
```

PyIceberg (inside `drone_ingest`):

```python
from pyiceberg.catalog.rest import RestCatalog
catalog = RestCatalog("px4", uri="http://lakekeeper:8181/catalog", warehouse="px4",
                      **{"s3.endpoint": "http://rustfs:9000", "s3.path-style-access": "true",
                         "s3.access-key-id": ..., "s3.secret-access-key": ..., "s3.region": "us-east-1"})
```

| Service | Image (pinned tag in `.env`) | Host port | Introduced in |
| --- | --- | --- | --- |
| `postgres` | `postgres:17.11` | 5432 | Phase 2 |
| `rustfs` | `rustfs/rustfs:1.0.1` | 9000 API, 9001 console | Phase 2 |
| `rustfs-init` | `amazon/aws-cli:2.37.13` (creates buckets) | — | Phase 2 |
| `lakekeeper-migrate` | `quay.io/lakekeeper/catalog:v0.14.0` (`migrate`) | — | Phase 3 |
| `lakekeeper` | `quay.io/lakekeeper/catalog:v0.14.0` (`serve`) | 8181 (REST + UI) | Phase 3 |
| `lakekeeper-bootstrap` | `curlimages/curl:8.22.0` (bootstrap + warehouse) | — | Phase 3 |
| `trino` | `trinodb/trino:483` (`mem_limit: 3g`, heap 2 GB) | 8085 | Phase 3 |
| `trino-init` | `trinodb/trino:483` (CLI; creates the schemas) | — | Phase 3 |
| `airflow-init`, `airflow-apiserver`, `airflow-scheduler`, `airflow-dag-processor` | build `infrastructure/airflow/Dockerfile` from `apache/airflow:3.3.2-python3.12` | 8080 | Phase 5 |
| `charts` | build `infrastructure/charts/Dockerfile` (`dbt-charts[trino]==0.9.1`) | 8088 | Phase 8 |

Python versions (checked on PyPI on 2026-10-13): `apache-airflow==3.3.2`, `astronomer-cosmos==1.15.1`, `dbt-trino==1.10.6`, `pyiceberg==0.12.0`, `pyulog==1.2.4`, `dbt-charts==0.9.1` (needs Python 3.10–3.13).

## 6. Data model (for the "database design" part of the presentation)

**Landing (RustFS, immutable):**
- `s3://landing/px4/index/snapshot_date=YYYY-MM-DD/run_id=<id>/dbinfo.json.gz` and `_manifest.json`
- `s3://landing/px4/ulog/log_date=YYYY-MM-DD/<log_id>.ulg`

**Bronze (Iceberg, written with PyIceberg):**
- `bronze.logs_index_raw`: `log_id`, `log_date`, `payload` (JSON string), `payload_hash`, `_change_type` (insert/update), `_snapshot_etag`, `_run_id`, `_source_file`, `_ingested_at`. Append-only (only new or changed records), partitioned by `month(log_date)`. Re-running the same snapshot inserts 0 rows because the hashes already match.
- `bronze.telemetry_raw`: `log_id`, `t_boot_s`, `ts_utc` (nullable: needs a GPS fix), `lat`, `lon`, `alt_m`, `vx`, `vy`, `vz`, `battery_remaining`, `battery_voltage_v`, `battery_current_a`, `nav_state`, `arming_state`, plus metadata. Partitioned by `_log_date` (the upload date, always present). Built from `vehicle_global_position`, `vehicle_local_position`, `battery_status` and `vehicle_status`, averaged per second.
- `bronze.log_messages_raw`: `log_id`, `ts`, `level`, `message`.
- `bronze.rejected_records`: `entity`, `log_id`, `reason` (`missing_<field>` / `invalid_<field>` / `not_an_object` / `duplicate_log_id_in_snapshot`), `detail`, `raw`, `_run_id`, `_rejected_at`.
- `audit.index_snapshots`: `etag`, `last_modified`, `bytes`, `records`, `sha256`, `landing_key`, `run_id`, `fetched_at`.
- `If-None-Match` uses the ETag of the newest snapshot that was **successfully loaded** (from `audit.ingestion_runs`), not just downloaded. A run that downloaded but failed to load is therefore retried next time.
- `audit.ingestion_runs`: entity, date, run_id, read, loaded, rejected, bytes, duration.
- `audit.ulog_downloads`: append-only event log (`log_id`, `log_date`, `status`, `reason`, `bytes`, `sha256`, `landing_key`, `telemetry_rows`, `message_rows`, `run_id`, `event_at`). A log's current status is its latest event:
  - `downloaded`: landed, needs parsing.
  - `parsed`: terminal.
  - `rejected`: terminal (`not_found`, `too_large`, `invalid_ulog_header`, `parse_error`).
  - `failed`: retried next run (`size_mismatch`).

**Silver (dbt):**
- `stg_logs`: dedups by `log_id`, keeping the latest `_ingested_at`. Renames `log_date` → `uploaded_date`, adds `is_simulation` (SITL), and nulls `duration_s` outside 1–86,400 s. Casts types and converts empty strings and sentinels to nulls. Splits `airframe_type` into `airframe_type` / `sys_autostart_fallback`. Normalizes `rating` via the `rating_map` seed. Parses `ver_sw_release` into `fw_major_minor`. Groups `mav_type` into `vehicle_class` (multirotor, fixed_wing, vtol, rover, other).
- `stg_log_mode_segments`: UNNESTs `flight_mode_durations` with ordinality.
- `stg_log_error_labels`: UNNESTs `error_labels`.
- `stg_telemetry`: drops impossible coordinates (0,0 or out of range), absurd altitudes, and battery outside 0–1.
- `stg_log_messages`
- `snap_vehicles`: SCD2 by `vehicle_uuid` (hardware, airframe, firmware).
- `dim_vehicle`, `dim_flight_mode`, `dim_error_label`, `dim_date`.
- `fct_flight` (one row per log, with `flight_started_at` from GPS UTC when available, and aggregated telemetry: max altitude, max speed, battery %/min), `fct_mode_segment`, `fct_telemetry_1min`.

**Gold (tables with `contract: enforced`):**
- `mart_flights_by_class_month`: logs and flight hours by `vehicle_class` and month.
- `mart_flight_mode_usage`: % of time per mode and class.
- `mart_reliability_daily`: crash ratings, error labels and logged errors per day.
- `mart_firmware_adoption`: share of each `fw_major_minor` per month.
- `mart_flight_envelope`: max/avg altitude and speed per class (telemetry).
- `mart_battery_efficiency`: battery % per minute and per km, by class and duration band.
- `mart_vehicle_utilization`: flights, hours and days since last log per vehicle.
- `mart_top_log_messages`: most frequent error messages.
- `mart_pipeline_runs`: over `audit.*`.

**Seeds:** `flight_modes.csv`, `error_labels.csv`, `vtol_modes.csv`, `rating_map.csv`, `mav_type_classes.csv`, `duration_bands.csv`.

## 7. Phased plan

Each phase lists **what is introduced**, a **checklist** (build + understand) and **examples to explore**.

Evolution of `docker compose config --services`:

| Tag | Services |
| --- | --- |
| `phase-2` | `postgres`, `rustfs`, `rustfs-init` |
| `phase-3` | + `lakekeeper-migrate`, `lakekeeper`, `lakekeeper-bootstrap`, `trino`, `trino-init` |
| `phase-5` | + 4 Airflow services |
| `phase-8` | + `charts` |

### Phase 1: Explore the source (no Docker)
**Introduces:** the real API contract, the ULog format and `pyulog`. Fixtures are produced here.
- [x] `explore/fetch_index.py`: conditional GET of the index. The second run gets a 304 (0 bytes) through the 302 redirect.
- [x] `explore/profile_dbinfo.py` → `explore/reports/dbinfo_profile.md`: per-field counts, types, sentinels and distributions. New defects were added to section 3.3.
- [x] `explore/ulog_sizes.py` → `explore/reports/ulog_sizes.md`: `HEAD` on 200 recent logs. The mean is 18 MB, not 8, so the section 4 budget is updated (decision pending).
- [x] `explore/inspect_ulog.py` → `explore/reports/ulog_inspection.md`: 3 small real ULogs (quad, fixed wing, VTOL). Field names are confirmed; topic gaps, boot-relative timestamps and undetectable truncation are recorded in section 3.3.
- [x] `explore/make_fixtures.py` → `ingest/tests/fixtures/` (4.3 MB): 200 stratified index records, next-day snapshot (5 inserts + 1 update), corrupt records, a truncated gzip, 3 ULogs plus 2 broken ones, and `expected.json`. See its README.

Findings that change later phases:
- `log_date` is the **upload** date; the flight time comes from ULog GPS.
- Raw ULog volume is ~9 GB/day.
- SITL logs must be flagged.
- `fetch-ulogs` must verify size == `Content-Length`.

```bash
cd explore && uv sync
uv run python fetch_index.py        # run twice: 200 then 304
uv run python profile_dbinfo.py     # → reports/dbinfo_profile.md
uv run python ulog_sizes.py         # HEAD only, no bodies
uv run python inspect_ulog.py       # downloads 3 small ULogs (~4 MB)
uv run python make_fixtures.py
uv run ulog_info data/ulogs/<id>.ulg          # topics, duration, parameters
uv run ulog_messages data/ulogs/<id>.ulg      # logged_messages → future events table
uv run ulog2csv -m battery_status data/ulogs/<id>.ulg -o /tmp/csv
```

### Phase 2: Object storage (Postgres + RustFS)
**Introduces:** Docker Compose basics (services, the internal network with service-name DNS, named volumes, `healthcheck` + `depends_on`, `.env`), S3-compatible storage, buckets, *path-style* addressing, "init" services that exit (`service_completed_successfully`), one Postgres with two databases (script in `infrastructure/postgres/init/`).
- [x] `infrastructure/docker-compose.yml` plus root `Makefile` and `.env.example`. `COMPOSE_FILE` in `.env` lets plain `docker compose …` work from the repo root (`make` targets: `env`, `up`, `down`, `reset`, `ps`, `logs`, `config`, `psql`, `s3`).
- [x] Healthchecks:
  - `postgres` runs a real query against the `lakekeeper` db, so it's only healthy after the init script ran.
  - `rustfs` checks `/health`.
- [x] `rustfs-init` creates `landing`, `lakehouse` and `reports`, and is idempotent on re-runs.
- [x] `infrastructure/postgres/init/` creates an `airflow` and a `lakekeeper` role, each owning its own database. `CONNECT` is revoked from `PUBLIC`, so one service's role is denied on the other's database.
- [x] `make up` waits for init jobs: `up --wait` doesn't cover them, so `infrastructure/scripts/wait-init.sh` fails if one exits non-zero. Later phases add their jobs to `INIT_JOBS` in the Makefile.
- [x] Data survives `make down && make up` and disappears with `make reset`, after which buckets and roles are recreated.
- Footprint: Postgres ~25 MiB and RustFS ~100 MiB of RAM; the stack is up in ~20 s.

Gotchas found:
- The RustFS console lives at `/rustfs/console/`; `/` returns 403.
- The AWS CLI needs `addressing_style = path` (`infrastructure/rustfs/aws-config`), because `<bucket>.rustfs` doesn't resolve on the compose network.
- `infrastructure/postgres/init/` only runs on an empty volume: changing passwords in `.env` later needs `ALTER ROLE` or `make reset`.

```bash
make env && make up                     # .env with random secrets, then start and wait
make ps                                 # includes the finished rustfs-init job
open http://localhost:9001/rustfs/console/   # log in with S3_ACCESS_KEY / S3_SECRET_KEY from .env
make s3 ARGS="ls"                       # AWS CLI against RustFS (path-style)
make s3 ARGS="ls --recursive s3://landing"
make psql                               # \l lists airflow and lakekeeper with their owners
make logs S=rustfs
docker network ls; docker volume ls     # px4-lakehouse_default, px4-lakehouse_{postgres,rustfs}-data
docker compose exec postgres getent hosts rustfs   # internal DNS: services reach each other by name
make down && make up                    # data kept; `make reset` deletes it
```

### Phase 3: Iceberg + Lakekeeper + Trino
**Introduces:**
- A table format (metadata JSON + manifests + Parquet), snapshots and time travel.
- What a **catalog** is: the atomic pointer from `namespace.table` to the current `metadata.json`.
- The Iceberg **REST catalog spec**, with Lakekeeper as its server: warehouses, projects, namespaces and the management API vs. the catalog API.
- Trino as an engine with no storage of its own.

Checklist:
- [x] `lakekeeper-migrate` → `lakekeeper` (healthcheck `/home/nonroot/lakekeeper healthcheck`) → `lakekeeper-bootstrap` creates warehouse `px4` on `s3://lakehouse/`.
- [x] `infrastructure/trino/etc/` (`config.properties` with 1 GB query memory caps, `jvm.config` with `-Xmx2G`) and the REST `iceberg.properties` from section 5. Property names were verified against Trino 483, which caught `fs.s3.enabled`.
- [x] Re-running `lakekeeper-bootstrap` is harmless: `CatalogAlreadyBootstrapped` and an existing warehouse both count as success.
- [x] `trino-init` creates `bronze`, `silver`, `gold` and `audit`, each with an explicit `s3://lakehouse/<layer>` location (idempotent).
- [x] `CREATE TABLE iceberg.bronze.smoke` + 2 inserts → files at `s3://lakehouse/bronze/smoke-<uuid>/{data/ts_day=…/*.parquet, metadata/*.metadata.json, *.avro}`, plus 3 snapshots, and time travel returns the first batch only.
- [x] `SELECT` still works after `make down && make up` (7 rows, 3 snapshots).
- [x] Lakekeeper UI → `px4 › bronze › smoke` → **PREVIEW** shows the rows: DuckDB-WASM in the browser reads the Parquet files from RustFS with vended STS credentials.
- Footprint: Trino ~830 MiB of RAM at idle (limit 3 GiB), Lakekeeper ~30 MiB. A cold start from `make reset` takes ~20 s. `INIT_JOBS` is now `rustfs-init lakekeeper-migrate lakekeeper-bootstrap trino-init`.

Gotchas found:
- Trino 483 needs `fs.s3.enabled`. The `fs.native-s3.enabled` from the proposal doesn't exist in this version.
- Without explicit schema locations, every Lakekeeper namespace gets the warehouse root as its location.
- `CREATE SCHEMA IF NOT EXISTS` never changes an existing location, so `make reset` after editing `init-schemas.sql`. The same goes for the warehouse storage profile in `bootstrap.sh` (create-only).
- The Trino image's `jvm.config` uses 80 % of available RAM, so it's overridden with `-Xmx2G` and a container limit.
- The Trino image ships a HEALTHCHECK, so `trino-init` (same image, CLI only) must disable it.
- The empty create-table snapshot has no `added-records` key: use `element_at(summary, 'added-records')`, because `summary['added-records']` errors on missing keys.

```bash
make up
make trino                               # interactive SQL on the iceberg catalog (\q to quit)
make trino SQL="show schemas"
  CREATE TABLE bronze.smoke (id integer, name varchar, ts timestamp(6) with time zone)
    WITH (partitioning = ARRAY['day(ts)']);
  INSERT INTO bronze.smoke SELECT nationkey, name, current_timestamp FROM tpch.tiny.nation;
  SELECT snapshot_id, operation, element_at(summary, 'total-records') FROM bronze."smoke$snapshots";
  SELECT * FROM bronze.smoke FOR VERSION AS OF <snapshot_id>;   -- time travel
  SELECT * FROM bronze."smoke$files";                            -- Parquet files behind the table
  SHOW CREATE SCHEMA bronze;                                     -- location = s3://lakehouse/bronze/
make s3 ARGS="ls --recursive s3://lakehouse/bronze/"             # data/ + metadata/ per table
open http://localhost:8181/ui/                     # Lakekeeper UI: warehouse → namespaces → tables → snapshots
curl -s localhost:8181/management/v1/warehouse | jq             # warehouse + storage profile (secret not returned)
curl -s "localhost:8181/catalog/v1/config?warehouse=px4" | jq   # REST config handshake; overrides.prefix = warehouse id
curl -s localhost:8181/catalog/v1/<prefix>/namespaces | jq      # Iceberg REST API, as Trino/PyIceberg see it
make psql DB=lakekeeper                                         # \dt: Lakekeeper's own tables (the catalog state)
open http://localhost:8085/ui/                     # Trino query UI (any user name, no password)
```

### Phase 4: Ingestion (`drone_ingest`)
**Introduces:** ELT, an immutable landing zone, manifests, idempotency, PyIceberg `RestCatalog` against Lakekeeper (same warehouse `px4` as Trino), ULog parsing.

Package `ingest/src/drone_ingest/`:
- `config.py`: settings from env vars. On the host, the repo-root `.env` is loaded and localhost ports are used; in containers, set `S3_ENDPOINT` / `CATALOG_URI`.
- `http.py`: polite client following PX4's retry rules (section 3.4).
- `storage.py`: boto3 for landing.
- `catalog.py`: the 7 table definitions and an `append` that retries on `CommitFailedException`, because Phase 5's parallel tasks will race.
- `schemas.py`: pydantic contract for index records.
- `index.py`, `ulog.py`: the commands below. Pure functions (diff, parse, checks) are kept separate from I/O so they're unit-testable.
- `audit.py`, `cli.py`.

CLI commands (each prints a JSON summary on stdout; logs go to stderr with `run_id=` / `cmd=`):
- `drone-ingest init-tables`: creates the missing bronze/audit tables (every command does this too).
- `drone-ingest snapshot-index`: conditional GET (section 3.4 retries). On 304 it records `not_modified` and stops. On 200 it checks the gzip/JSON, lands `dbinfo.json.gz`, then `_manifest.json` last (etag, bytes, records, sha256), and prunes snapshots beyond `INDEX_SNAPSHOT_RETENTION`.
- `drone-ingest load-index [--manifest KEY]`: verifies sha256 against the manifest, validates records, diffs them against bronze's latest hash per `log_id`, and appends only `insert`/`update` rows. Rejects go to `bronze.rejected_records`.
- `drone-ingest plan-ulogs [--start --end] --out plan.json`: log ids uploaded in the window that are not yet `parsed`/`rejected`, in batches of `ULOG_BATCH_SIZE`.
- `drone-ingest fetch-ulogs --plan plan.json [--batch N]`: HEADs every file (404 → `not_found`, > `ULOG_MAX_BYTES` → `too_large`), runs the disk guard over the batch, then downloads with concurrency `ULOG_CONCURRENCY`. A size ≠ `Content-Length` is retried once, then marked `failed`. Files land at `px4/ulog/log_date=…/<id>.ulg`.
- `drone-ingest parse-ulogs --plan plan.json [--batch N]`: pyulog → 1 Hz telemetry (means; last value for states) plus logged messages, with UTC from GPS `time_utc_usec` when there's a fix. One append per table per batch; a broken file is rejected without stopping the batch.
- `drone-ingest purge-ulogs`: deletes landed `log_date=` folders older than today − `ULOG_RETENTION_DAYS`. Run it **before** fetching.

Checklist:
- [x] `pytest` green against the fixtures (no network, no services): 20 tests, `make test`.
- [x] **Trino sees the tables PyIceberg wrote** (first risk): all 7 tables, with `month(log_date)` partitioning and ZSTD.
- [x] Bootstrap on the real index: 477,079 read, 314,800 inserted (`log_date >= 2025-01-01`), 162,279 out of window, 0 rejected, in 12 s.
- [x] Loading the same snapshot twice inserts 0 rows the second time (314,800 unchanged).
- [x] A fixture with one edited `rating` produces exactly one `_change_type='update'` row (unit test with the next-day snapshot: 5 inserts, 1 update, 199 unchanged).
- [x] A second `snapshot-index` the same day receives 304 and downloads 0 bytes (`not_modified` in `audit.ingestion_runs`).
- [x] With `MIN_FREE_DISK_GB` above the real free space, `fetch-ulogs` exits 1 with `DiskGuardError` before downloading anything (0 files, 0 audit events).
- [x] 20 real ULogs (368 MB): fetched in 14 s, and fetching again skips all 20. Parsed in 5 s: 3,035 telemetry rows and 10,922 messages; parsing again → 0.
- [x] Corrupt fixture records land in `bronze.rejected_records` with all 8 reasons, read back in Trino (test rows then removed with Trino `DELETE`).
- [x] `purge-ulogs` deletes only folders older than the cutoff.
- Footprint:
  - `load-index` peaks at **~2.6 GB of RAM** on the bootstrap and ~2 GB on a daily run, because the whole 477k-record index is parsed into Python objects. Size the Airflow container accordingly in Phase 5, or switch to a streaming JSON parser.
  - `parse-ulogs` stays at ~240 MB per batch of 20.

Findings and gotchas:
- PyIceberg 0.12 needs the **`pyiceberg-core`** extra to write `month()`-partitioned tables (`NotInstalledError` otherwise).
- PyIceberg asks Lakekeeper for **vended credentials** by default, so writes use STS keys and the `rustfs.localhost` endpoint. macOS resolves `*.localhost` to 127.0.0.1, and containers resolve the compose alias.
- Fetch must use the **current** status from `audit.ulog_downloads`, not the status saved in the plan file. A stale plan once produced 20 redundant audit events; those rows are still in the dev data.
- One real log produced **10,624 ERROR messages**, mostly unique strings (embedded numbers), so silver/gold must normalize messages into templates before counting "top messages".
- Of the 20 logs uploaded on 2026-10-13, flight dates (GPS UTC) go back to 2025-05-08: `log_date` really is the upload date.
- ~59 % of telemetry rows have `ts_utc` (logs without a GPS fix have only `t_boot_s`).

```bash
make test                                   # unit tests
cd ingest && uv sync
uv run drone-ingest snapshot-index          # 200 + landed, or 304 if already loaded
uv run drone-ingest load-index              # diff vs bronze → inserted / updated / unchanged
uv run drone-ingest snapshot-index          # again: 304, 0 bytes
MAX_ULOGS_PER_RUN=20 uv run drone-ingest plan-ulogs --out plan.json   # yesterday's uploads, capped
uv run drone-ingest fetch-ulogs --plan plan.json
uv run drone-ingest parse-ulogs --plan plan.json
uv run drone-ingest purge-ulogs
MIN_FREE_DISK_GB=100000 uv run drone-ingest fetch-ulogs --plan plan.json   # disk guard: aborts, exit 1
make trino SQL="SELECT entity, run_id, status, read, inserted, updated, rejected FROM audit.ingestion_runs ORDER BY started_at"
make trino SQL="SELECT count(DISTINCT log_id), count(*), count(ts_utc) FROM bronze.telemetry_raw"
make s3 ARGS="ls --recursive s3://landing/px4/"
# Lakekeeper UI → px4 › bronze › telemetry_raw › PREVIEW (DuckDB in the browser)
```

### Phase 5: Orchestration with Airflow 3
**Introduces:** DAGs, tasks, operators, `LocalExecutor`, pools, retries with backoff, *dynamic task mapping* (one mapped task per ULog batch), *assets* (data-aware scheduling), `AIRFLOW_CONN_*` connections.
- [ ] `infrastructure/airflow/Dockerfile` (build context = repo root; DAGs mounted from `dags/`): Airflow 3.3.2 + `drone_ingest` + a dbt virtualenv at `/opt/dbt-venv`.
- [ ] Services `airflow-init`, `airflow-apiserver`, `airflow-scheduler` and `airflow-dag-processor`.
- [ ] DAG `px4_ingest_daily` (02:00 America/Hermosillo, `catchup=False`): `api_healthcheck` → `snapshot_index` (a `ShortCircuitOperator` on 304 skips the rest) → `validate_manifest` → `load_index` → `purge_expired_ulogs` → `plan_ulogs` → `fetch_ulogs.expand(batch)` (pool `px4_pool`, 4 slots) → `parse_ulogs.expand(batch)` → emits `bronze.*` assets.
- [ ] DAG `px4_backfill` (manual, `start_date`/`end_date`): the same ULog flow, **one `log_date` at a time with a purge between days**, so raw files never exceed one day.
- [ ] DAG `px4_maintenance` (weekly): `expire_snapshots` + `optimize` via Trino, plus orphan-file cleanup.
- [ ] Pointing the API URL at a nonexistent host produces retries, then a failure with a readable log in the UI.
```bash
open http://localhost:8080
docker compose exec airflow-scheduler airflow dags list
docker compose exec airflow-scheduler airflow tasks test px4_ingest_daily snapshot_index 2026-10-13
docker compose exec airflow-scheduler airflow dags trigger px4_backfill -c '{"start_date":"2026-10-06","end_date":"2026-10-12"}'
docker stats                                   # watch RAM (target: < 8 GB)
```

### Phase 6: Transformation with dbt
**Introduces:** `source` vs. `model`, materializations (`table`, `incremental` with `merge`), seeds, snapshots (SCD2), generic tests and `dbt-expectations`, contracts, `generate_schema_name`, docs.
- [ ] `dbt/` project with a `profiles.yml` that reads env vars, and the models from section 6.
- [ ] `dbt build` green.
- [ ] No dirty `rating`, `wind_speed=-1` or int `airframe_type` reaches silver (enforced by tests).
- [ ] Dropping silver and gold and re-running gives identical counts.
- [ ] `source freshness` on `_ingested_at`: warn at 26 h, error at 48 h.
```bash
docker compose exec airflow-scheduler bash -c 'cd /opt/dbt && /opt/dbt-venv/bin/dbt debug'
dbt seed && dbt build -s +stg_logs     # one model plus its parents
dbt ls -s tag:gold; dbt compile -s fct_flight && cat target/compiled/…/fct_flight.sql
dbt docs generate                      # open target/index.html locally
select * from iceberg.silver."stg_logs$history";   -- each dbt run = a new snapshot
```

### Phase 7: dbt inside Airflow (Cosmos)
**Introduces:** one dbt model = one Airflow task; a DAG triggered by assets.
- [ ] DAG `px4_transform`, triggered by the `bronze.*` assets. Runs `source freshness` → `seed` → silver group → gold group → `docs generate` → `render_charts`, with `max_active_runs=1`.
- [ ] A test with `error` severity stops the DAG; one with `warn` doesn't.
```bash
# In the UI: Assets → bronze.logs_index_raw → see the consuming DAG
# px4_transform Graph view: each model is a run+test task
```

### Phase 8: Visualization with dbt Charts
**Introduces:** dashboards as code (YAML next to the models), `ref()` in queries, offline validation, static rendering.
- [ ] `charts` service (`dct serve --host 0.0.0.0`, port 8088, Trino user `charts`).
- [ ] Boards in `dbt/charts/`:
  - `fleet_overview.yml`: logs and hours per day and class; KPIs.
  - `flight_behavior.yml`: flight modes; altitude and speed envelope.
  - `reliability.yml`: crashes, error labels, top messages and firmware adoption.
  - `pipeline_health.yml`: runs, rejects, bytes downloaded.
- [ ] `dct validate --strict` passes.
- [ ] `render_charts` uploads HTML and PDF to `s3://reports/<date>/`.
```bash
docker compose exec charts dct validate --strict
open http://localhost:8088
docker compose exec charts dct impact stg_logs.vehicle_class   # which boards a change would break
```

### Phase 9: Integration and presentation
- [ ] `infrastructure/scripts/smoke_test.sh`: from a clean clone, `cp .env.example .env && make up`, trigger ingestion with `MAX_ULOGS_PER_RUN=20`, wait for the transform, check gold counts and that the report exists. Must exit 0.
- [ ] `README.md` with startup steps, ports and the diagram.
- [ ] Presentation script (~7 min), mapped to `task.txt`:
  - [ ] Problem statement (section 3).
  - [ ] API: `dbinfo` + ULog, volume and defects.
  - [ ] Architecture and the role of each container (section 5).
  - [ ] DB design: landing → bronze → silver → gold (section 6), with a diagram of `fct_flight` and its dimensions.
  - [ ] Live demo: trigger the DAG → files in RustFS → `SELECT` in Trino → refreshed board.
- [ ] Demo plan B: preloaded data + screenshots, in case the classroom network fails.

## 8. Repository layout

```text
.
├── CLAUDE.md  DECISIONS.md  DESIGN_PROPOSAL.md  README.md
├── Makefile  .env.example       # entry points: `make up`; .env sets COMPOSE_FILE and secrets
├── definition/                  # assignment + instructor example (do not modify)
├── infrastructure/              # everything that runs the platform (no business logic)
│   ├── docker-compose.yml       # relative paths resolve from this folder
│   ├── postgres/init/           # creates the airflow and lakekeeper roles + databases
│   ├── rustfs/                  # bucket init script + AWS CLI path-style config
│   ├── lakekeeper/bootstrap.sh  # bootstrap + warehouse px4 (JSON built from env vars)
│   ├── trino/{etc,catalog,init}/  # server config, catalogs (iceberg, tpch), schema init SQL
│   ├── airflow/Dockerfile       # Airflow + drone_ingest + dbt venv (build context: repo root)
│   ├── charts/Dockerfile
│   └── scripts/{wait-init.sh,smoke_test.sh}
├── explore/                     # Phase 1 profiling scripts and reports
├── ingest/                      # drone_ingest package: src/drone_ingest/{config,http,storage,catalog,schemas,index,ulog,audit,cli}.py, tests/
├── dags/                        # Airflow DAGs (mounted into the Airflow containers)
└── dbt/{models/{sources,silver,gold},seeds,snapshots,macros,tests,charts}/
```

Rule: files that configure, build or run services go in `infrastructure/`. Code that moves or transforms data (`ingest/`, `dags/`, `dbt/`) stays at the root.

## 9. Watched risks

- **Lakekeeper is 0.x**: pinned to `v0.14.0` (released 2026-10-07), with `v0.13.6` as the fallback. Trino 483 ↔ Lakekeeper is verified (Phase 3). PyIceberg 0.12 writing tables that Trino reads is verified (Phase 4).
- **RustFS + Lakekeeper STS**: verified (Phase 3). The browser path depends on `*.localhost` resolving to 127.0.0.1, which Chrome and Firefox do. Other browsers may need a `/etc/hosts` entry `127.0.0.1 rustfs.localhost`.
- **Disk usage from full ULog**: ~9.3 GB/day against ~13 GiB free. Mitigated by the 1-day raw window, purge-before-fetch and the `MIN_FREE_DISK_GB` guard (D-004). Free up disk if a heavy upload day gets close to the limit.
- **RustFS 1.0.x and dbt Charts 0.9.x are young**: versions pinned; standard S3 API only.
- **ULog topic schema drift across firmware versions**: the parser tolerates missing fields (null column + a count in audit).
- **Being blocked by PX4 (403/444)**: abort the run, no retries.
