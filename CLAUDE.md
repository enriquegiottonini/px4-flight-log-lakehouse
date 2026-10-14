# CLAUDE.md: PX4 Flight-Log Lakehouse

This file is the project's **build plan** and the **working rules** for Claude Code.
- Original design: `DESIGN_PROPOSAL.md` (architecture still applies; section 3 here replaces its API contract).
- Assignment: `definition/task.txt`.
- Instructor's reference example: `definition/dash-mysql/`.
- Decision log: `DECISIONS.md` (one entry per decision, format D-NNN).

## 1. Working rules (for Claude)

- Build **phase by phase** (section 7). Never start a phase while any checklist item in the previous one is red.
- When a phase closes: commit + `git tag phase-N`, so the evolution can be inspected with `git diff phase-2 phase-3 -- docker-compose.yml`.
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
| Containerization (≥ 2 containers) | Docker Compose with ~12 services (section 5). |
| Integration API → DB → visualization | Airflow DAGs chained by *assets*; `scripts/smoke_test.sh` checks the full flow. |
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
5. **ULogs** are fetched once per `log_id` (anti-join with `audit.ulog_downloads`). Their window is `ULOG_START_DATE` (default today − 1, see D-004), which is independent of the index window. Because `log_date` is the upload date, new `log_id`s always appear under recent dates.

**Disk budget (D-004), measured in Phase 1** (`explore/reports/ulog_sizes.md`): ~512 logs/day × **18 MB mean** ≈ **9.3 GB/day** of raw ULog.
- A 7-day window would be ≈ 65 GB, but the development machine has ~13 GiB free. **Decision (D-004, revised): keep raw ULogs for a 1-day window only.**
- `ULOG_START_DATE` = today − 1 and `ULOG_RETENTION_DAYS=1`: landing holds at most one day of `.ulg` files (~9–10 GB).
- **Purge before fetch:** `purge_expired_ulogs` runs *before* the day's downloads, so two days never coexist (that would be ~18 GB).
- **Free-disk guard:** before each batch, `fetch-ulogs` checks free space on the RustFS volume. It aborts with a clear error if free space minus the batch's summed `Content-Length` would drop below `MIN_FREE_DISK_GB=3`.
- **Backfill** processes one day at a time and purges between days, so the peak never exceeds one day.
- Parsed telemetry lives in Iceberg and is **not** purged: ~40–90 rows per log at 1 Hz ≈ 40k rows/day, so telemetry history keeps growing even though raw files rotate.
- Docker Desktop keeps volumes inside its VM disk image (Settings → Resources → disk limit). It must allow ≥ 20 GB.
- Knobs: `ULOG_START_DATE`, `ULOG_RETENTION_DAYS`, `MIN_FREE_DISK_GB`, `ULOG_MAX_BYTES` (larger logs → `rejected`, reason `too_large`), `MAX_ULOGS_PER_RUN` (empty = all; useful during development).

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
- `lakekeeper-bootstrap` (curl, run once) does two POSTs:
  - `POST /management/v1/bootstrap` with `{"accept-terms-of-use": true}`.
  - `POST /management/v1/warehouse` with `lakekeeper/create-warehouse.json`: warehouse `px4`, `storage-profile` `{type: s3, bucket: lakehouse, endpoint: http://rustfs:9000, region: us-east-1, path-style-access: true, flavor: s3-compat, sts-enabled: false}` and an access-key `storage-credential`.
- Secrets in `.env`: `LAKEKEEPER__PG_ENCRYPTION_KEY`, `LAKEKEEPER__PG_DATABASE_URL_READ` / `_WRITE`.
- No OIDC: auth is disabled (local toy), in line with the proposal's "no auth" non-goal.
- STS / vended credentials are **off** (RustFS STS support is unverified). Trino and PyIceberg use their own static S3 keys. Try `sts-enabled: true` later as a stretch goal.

`trino/catalog/iceberg.properties` (replaces the proposal's JDBC block; verify names against Trino 483):

```properties
connector.name=iceberg
iceberg.catalog.type=rest
iceberg.rest-catalog.uri=http://lakekeeper:8181/catalog
iceberg.rest-catalog.warehouse=px4
iceberg.rest-catalog.vended-credentials-enabled=false
iceberg.file-format=PARQUET
iceberg.compression-codec=ZSTD
fs.native-s3.enabled=true
s3.endpoint=http://rustfs:9000
s3.path-style-access=true
s3.region=us-east-1
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
| `postgres` | `postgres:17` | 5432 | Phase 2 |
| `rustfs` | `rustfs/rustfs:1.0.1` | 9000 API, 9001 console | Phase 2 |
| `rustfs-init` | `amazon/aws-cli` (creates buckets) | — | Phase 2 |
| `lakekeeper-migrate` | `quay.io/lakekeeper/catalog:v0.14.0` (`migrate`) | — | Phase 3 |
| `lakekeeper` | `quay.io/lakekeeper/catalog:v0.14.0` (`serve`) | 8181 (REST + UI) | Phase 3 |
| `lakekeeper-bootstrap` | `curlimages/curl` (bootstrap + warehouse) | — | Phase 3 |
| `trino` | `trinodb/trino:483` | 8085 | Phase 3 |
| `airflow-init`, `airflow-apiserver`, `airflow-scheduler`, `airflow-dag-processor` | build `airflow/Dockerfile` from `apache/airflow:3.3.2-python3.12` | 8080 | Phase 5 |
| `charts` | build `charts/Dockerfile` (`dbt-charts[trino]==0.9.1`) | 8088 | Phase 8 |

Python versions (checked on PyPI on 2026-10-13): `apache-airflow==3.3.2`, `astronomer-cosmos==1.15.1`, `dbt-trino==1.10.6`, `pyiceberg==0.12.0`, `pyulog==1.2.4`, `dbt-charts==0.9.1` (needs Python 3.10–3.13).

## 6. Data model (for the "database design" part of the presentation)

**Landing (RustFS, immutable):**
- `s3://landing/px4/index/snapshot_date=YYYY-MM-DD/run_id=<id>/dbinfo.json.gz` and `_manifest.json`
- `s3://landing/px4/ulog/log_date=YYYY-MM-DD/<log_id>.ulg`

**Bronze (Iceberg, written with PyIceberg):**
- `bronze.logs_index_raw`: `log_id`, `log_date`, `payload` (JSON string), `payload_hash`, `_change_type` (insert/update), `_snapshot_etag`, `_run_id`, `_source_file`, `_ingested_at`. Append-only (only new or changed records), partitioned by `month(log_date)`. Re-running the same snapshot inserts 0 rows because the hashes already match.
- `bronze.telemetry_raw`: `log_id`, `t_boot_s`, `ts_utc` (nullable: needs a GPS fix), `lat`, `lon`, `alt_m`, `vx`, `vy`, `vz`, `battery_remaining`, `battery_voltage_v`, `battery_current_a`, `nav_state`, `arming_state`, plus metadata. Partitioned by `_log_date` (the upload date, always present). Built from `vehicle_global_position`, `vehicle_local_position`, `battery_status` and `vehicle_status`, averaged per second.
- `bronze.log_messages_raw`: `log_id`, `ts`, `level`, `message`.
- `bronze.rejected_records`: `entity`, `log_id`, `reason`, `raw`, `_run_id`.
- `audit.index_snapshots`: `etag`, `last_modified`, `bytes`, `records`, `inserted`, `updated`, `run_id`, `fetched_at`. The latest row supplies `If-None-Match`.
- `audit.ingestion_runs`: entity, date, run_id, read, loaded, rejected, bytes, duration.
- `audit.ulog_downloads`: `log_id`, `status`, `bytes`, `sha256`, `downloaded_at`, `parsed_at`.

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
| `phase-3` | + `lakekeeper-migrate`, `lakekeeper`, `lakekeeper-bootstrap`, `trino` |
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
**Introduces:** Docker Compose basics (services, the internal network with service-name DNS, named volumes, `healthcheck` + `depends_on`, `.env`), S3-compatible storage, buckets, *path-style* addressing, "init" services that exit (`service_completed_successfully`), one Postgres with two databases (script in `postgres/init/`).
- [ ] `docker-compose.yml`, `.env.example`, `Makefile` (`up`, `down`, `reset`, `ps`, `logs`).
- [ ] Healthchecks on `postgres` and `rustfs`; `rustfs-init` creates `landing`, `lakehouse` and `reports`.
- [ ] Buckets survive `make down && make up` and disappear with `make reset`.
```bash
make up && docker compose ps
open http://localhost:9001                                     # RustFS console
docker compose run --rm rustfs-init aws --endpoint-url http://rustfs:9000 s3 ls
docker compose exec postgres psql -U $POSTGRES_USER -l          # airflow and lakekeeper dbs
docker network ls; docker volume ls                            # network and volumes created by compose
docker compose exec postgres getent hosts rustfs               # internal DNS: services reach each other by name
```

### Phase 3: Iceberg + Lakekeeper + Trino
**Introduces:**
- A table format (metadata JSON + manifests + Parquet), snapshots and time travel.
- What a **catalog** is: the atomic pointer from `namespace.table` to the current `metadata.json`.
- The Iceberg **REST catalog spec**, with Lakekeeper as its server: warehouses, projects, namespaces and the management API vs. the catalog API.
- Trino as an engine with no storage of its own.

Checklist:
- [ ] `lakekeeper-migrate` → `lakekeeper` (healthcheck `/home/nonroot/lakekeeper healthcheck`) → `lakekeeper-bootstrap` creates warehouse `px4` on `s3://lakehouse/`.
- [ ] `trino/etc/` (`config.properties`, `jvm.config` with `-Xmx2G`) and the REST `trino/catalog/iceberg.properties` from section 5. Verify property names against Trino 483.
- [ ] Re-running `lakekeeper-bootstrap` is harmless: an "already bootstrapped" / "warehouse exists" response is treated as success.
- [ ] `CREATE SCHEMA` for `bronze`, `silver`, `gold` and `audit`.
- [ ] `CREATE TABLE iceberg.bronze.smoke` creates files visible in RustFS.
- [ ] `SELECT` still works after restarting everything.
```bash
docker compose exec trino trino --catalog iceberg
  CREATE TABLE bronze.smoke (id int, ts timestamp(6)) WITH (partitioning = ARRAY['day(ts)']);
  INSERT INTO bronze.smoke VALUES (1, now()), (2, now());
  SELECT * FROM bronze."smoke$snapshots";          -- snapshot history
  SELECT * FROM bronze.smoke FOR VERSION AS OF <snapshot_id>;   -- time travel
open http://localhost:8181/ui                       # Lakekeeper UI: warehouse → namespaces → tables → snapshots
curl -s localhost:8181/management/v1/warehouse | jq             # warehouses + storage profile
curl -s "localhost:8181/catalog/v1/config?warehouse=px4" | jq   # REST config handshake that Trino/PyIceberg perform
curl -s localhost:8181/catalog/v1/<prefix>/namespaces | jq      # prefix comes from the config response
open http://localhost:8085                          # Trino query UI
```

### Phase 4: Ingestion (`drone_ingest`)
**Introduces:** ELT, an immutable landing zone, manifests, idempotency, PyIceberg `RestCatalog` against Lakekeeper (same warehouse `px4` as Trino), ULog parsing.
- CLI:
  - `drone-ingest snapshot-index --run-id`: conditional GET of `dbinfo` (`If-None-Match` with the last ETag) with retries (section 3.4). On 304, exits with "no changes" and Airflow skips the downstream tasks. On 200, writes the gz + `_manifest.json` (etag, bytes, records, sha256) to landing and prunes snapshots beyond `INDEX_SNAPSHOT_RETENTION`.
  - `drone-ingest load-index --run-id`: computes `payload_hash` per record, anti-joins against bronze's latest hash per `log_id`, and appends only new or changed rows (bootstrap limited to `log_date >= INDEX_START_DATE`). Invalid records go to `rejected_records`.
  - `drone-ingest plan-ulogs --run-id`: window `log_id`s without `status='parsed'` in `audit.ulog_downloads` → a list in batches of 50.
  - `drone-ingest fetch-ulogs --batch <file>`: streaming download with concurrency 4. Rejects as `size_mismatch` when the downloaded bytes ≠ `Content-Length` (pyulog can't detect truncation), and records the sha256.
  - `drone-ingest parse-ulogs --batch <file>`: pyulog → 1 Hz → `bronze.telemetry_raw` + `bronze.log_messages_raw`. A corrupt log is rejected without stopping the batch.
- [ ] `pytest` green against the fixtures (no network).
- [ ] Loading the same snapshot twice inserts 0 rows the second time.
- [ ] A fixture with one edited `rating` produces exactly one `_change_type='update'` row.
- [ ] A second `snapshot-index` the same day receives 304 and downloads 0 bytes.
- [ ] Running `fetch-ulogs` twice doesn't download again.
- [ ] With `MIN_FREE_DISK_GB` set above the real free space, `fetch-ulogs` aborts before downloading anything.
- [ ] Trino sees the tables PyIceberg wrote. **This is the first risk to validate.**
```bash
cd ingest && uv sync && uv run pytest -q
uv run drone-ingest snapshot-index --run-id manual_1
uv run drone-ingest load-index --run-id manual_1
uv run drone-ingest snapshot-index --run-id manual_2      # same day → 304, nothing downloaded
curl -sSI https://cdn.logs.px4.io/dbinfo.json | grep -iE 'etag|last-modified'
docker compose exec trino trino --execute "select log_date, count(*) from iceberg.bronze.logs_index_raw group by 1 order by 1 desc limit 10"
uv run python -c "from pyiceberg.catalog.rest import RestCatalog; …; print(cat.load_table('bronze.logs_index_raw').scan().to_arrow().num_rows)"
# Lakekeeper UI: the new table and one snapshot per load-index run
```

### Phase 5: Orchestration with Airflow 3
**Introduces:** DAGs, tasks, operators, `LocalExecutor`, pools, retries with backoff, *dynamic task mapping* (one mapped task per ULog batch), *assets* (data-aware scheduling), `AIRFLOW_CONN_*` connections.
- [ ] `airflow/Dockerfile`: Airflow 3.3.2 + `drone_ingest` + a dbt virtualenv at `/opt/dbt-venv`.
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
- [ ] `scripts/smoke_test.sh`: from a clean clone, `cp .env.example .env && make up`, trigger ingestion with `MAX_ULOGS_PER_RUN=20`, wait for the transform, check gold counts and that the report exists. Must exit 0.
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
├── definition/              # assignment + instructor example (do not modify)
├── docker-compose.yml  .env.example  Makefile
├── explore/                 # Phase 1 profiling scripts
├── postgres/init/           # creates the airflow and lakekeeper databases
├── lakekeeper/create-warehouse.json
├── trino/{etc,catalog}/
├── ingest/                  # drone_ingest package (pyproject, src/, tests/fixtures/)
├── airflow/{Dockerfile,dags/}
├── dbt/{models/{sources,silver,gold},seeds,snapshots,macros,tests,charts}/
├── charts/Dockerfile
└── scripts/smoke_test.sh
```

## 9. Watched risks

- **Lakekeeper is 0.x**: pinned to `v0.14.0` (released 2026-10-07), with `v0.13.6` as the fallback. Check that Trino 483 and PyIceberg 0.12 both talk to it in Phase 3 (Trino) and at the start of Phase 4 (PyIceberg writes, Trino reads).
- **RustFS + Lakekeeper STS**: unverified, so vended credentials stay off and clients use static keys.
- **Disk usage from full ULog**: ~9.3 GB/day against ~13 GiB free. Mitigated by the 1-day raw window, purge-before-fetch and the `MIN_FREE_DISK_GB` guard (D-004). Free up disk if a heavy upload day gets close to the limit.
- **RustFS 1.0.x and dbt Charts 0.9.x are young**: versions pinned; standard S3 API only.
- **ULog topic schema drift across firmware versions**: the parser tolerates missing fields (null column + a count in audit).
- **Being blocked by PX4 (403/444)**: abort the run, no retries.
