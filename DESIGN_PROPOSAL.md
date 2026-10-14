# Diseño: Drone Flight Lakehouse

Oct 12, 2026 · @eg

## Resumen y objetivos

Construir, en Docker Compose, un lakehouse local mínimo pero completo: Airflow orquesta la ingesta de logs de vuelos de drones desde una API, los datos aterrizan en RustFS (almacenamiento de objetos compatible con S3) como tablas Apache Iceberg, dbt los transforma vía Trino en capas bronze/silver/gold, y dbt Charts los visualiza.

El proyecto es un juguete con over-engineering **acotado**: seis piezas (Airflow, RustFS, Iceberg, Trino, dbt y dbt Charts) más un Postgres de soporte. Cualquier componente fuera de esa lista requiere una justificación explícita.

Objetivos medibles:

- `docker compose up` levanta toda la plataforma sin pasos manuales más allá de un `.env`.
- Una corrida del DAG lleva un día de vuelos desde la API hasta el dashboard sin intervención.
- Cada capa es reproducible: borrar silver/gold y re-correr dbt da el mismo resultado.
- Todo fallo es visible en la UI de Airflow, con el log de la tarea que falló.

## Alcance y no-objetivos

En alcance:

- Ingesta batch diaria (con backfill por rango de fechas) desde la API REST de logs de vuelo.
- Data lake en RustFS con zona *landing* de archivos crudos y tablas Iceberg para bronze, silver y gold.
- Transformaciones, tests y documentación con dbt (adaptador `dbt-trino`).
- Orquestación y reintentos con Airflow.
- Dashboards como código con dbt Charts.

Fuera de alcance:

- Streaming o tiempo real (Kafka, Flink).
- Despliegue en nube, Kubernetes o alta disponibilidad.
- Stack de observabilidad (Prometheus, Grafana, Loki, Alertmanager) y linaje de datos; los logs de Airflow bastan.
- Servicios extra: Celery/Redis, catálogo REST de Iceberg separado, API simulada, cluster de Trino con workers.
- Autenticación, TLS y control de acceso.
- Datos personales o sensibles.

## Arquitectura general

El dato viaja en línea recta de la API al dashboard: Airflow dispara cada tramo, Trino ejecuta todo el SQL y un catálogo Iceberg JDBC, guardado en Postgres, sabe qué archivos forman cada tabla.

&#91;embedded content: arquitectura · flujo de datos y orquestación\]

Recorrido de un vuelo:

1. `drone_ingest extract` pide el día a la API y guarda el JSON tal cual en landing (RustFS).
2. `drone_ingest load-bronze` lo copia a tablas Iceberg bronze, con metadatos de carga.
3. dbt, ejecutado por Trino, limpia y deduplica hacia silver.
4. dbt agrega silver en marts gold.
5. dbt Charts consulta gold vía Trino y publica los boards.

## Fuente de datos: API de logs de vuelo

La fuente es una API REST que, por fecha, devuelve los vuelos de una flota de drones de distintos tipos, con sus condiciones, sus eventos y su telemetría. El usuario ya tiene un script de ingesta; el contrato de abajo es el supuesto de trabajo y el agente debe ajustar el mapeo si la API real difiere.

No se levanta una API simulada: el pipeline usa la API real. Para pruebas, `ingest/tests/fixtures/` guarda respuestas JSON grabadas con defectos típicos (duplicados, unidades mezcladas, nulos y registros tardíos), que son los que silver debe limpiar.

| Endpoint | Devuelve | Paginación |
| --- | --- | --- |
| `GET /v1/drones` | Catálogo de drones: `drone_id`, `model`, `drone_type`, `manufacturer`, `max_payload_kg`, `firmware_version` | No |
| `GET /v1/flights?date=YYYY-MM-DD` | Vuelos iniciados ese día (UTC) | `page`, `page_size` (máx. 500), `next_page` |
| `GET /v1/flights/{flight_id}/events` | Eventos del vuelo: despegue, aterrizaje, alertas de batería, pérdida de GPS, aborto | No |
| `GET /v1/flights/{flight_id}/telemetry` | Serie de tiempo a 1 Hz: posición, altitud, velocidad, batería | `cursor` |

Ejemplo de registro de vuelo (JSON tal como llega):

```json
{
  "flight_id": "f-2026-10-01-000123",
  "drone_id": "dr-0042",
  "drone_type": "quadcopter",
  "mission_type": "inspection",
  "started_at": "2026-10-01T14:03:11Z",
  "ended_at": "2026-10-01T14:41:52Z",
  "status": "completed",
  "site": {"site_id": "hmo-01", "lat": 29.07, "lon": -110.96},
  "altitude": {"max": 120.5, "avg": 88.2, "unit": "m"},
  "distance_m": 6420,
  "max_speed": {"value": 14.1, "unit": "m/s"},
  "battery": {"start_pct": 98, "end_pct": 31},
  "weather": {"wind_speed_mps": 6.3, "gust_mps": 9.8, "temp_c": 34.5, "precipitation": "none", "visibility_km": 10}
}
```

Valores esperados: `drone_type` ∈ {quadcopter, hexacopter, fixed\_wing, vtol}; `status` ∈ {completed, aborted, emergency\_landing, crashed}; `mission_type` ∈ {inspection, mapping, delivery, training}.

## Almacenamiento: RustFS, Parquet e Iceberg

No hay base de datos analítica: los datos viven como archivos en RustFS, las tablas son Iceberg sobre Parquet, y el catálogo Iceberg es de tipo JDBC dentro del mismo Postgres que usa Airflow, así que no hay servicio de catálogo aparte.

| Pieza | Elección | Rol |
| --- | --- | --- |
| Object storage | [RustFS](https://docs.rustfs.com/de/installation/container/docker) (`rustfs/rustfs`), API S3 en 9000 y consola en 9001; buckets `landing`, `lakehouse`, `reports` | Guarda archivos crudos y archivos de datos/metadata de Iceberg; reemplaza a MinIO |
| Formato de archivo | Parquet, compresión zstd | Almacenamiento columnar de cada tabla |
| Formato de tabla | Apache Iceberg, spec v2 | Esquema, snapshots, transacciones, time travel |
| Catálogo | Iceberg JDBC catalog en Postgres (base `iceberg`), nombre de catálogo `drones` | Mapea `namespace.tabla` al snapshot vigente; lo comparten Trino y PyIceberg (`SqlCatalog`) |

Organización:

- `s3://landing/drone_api/<entidad>/ingest_date=YYYY-MM-DD/run_id=<airflow_run_id>/part-NNNN.json.gz` — respuesta de la API tal cual, inmutable, una carpeta por corrida.
- `s3://lakehouse/` — warehouse del catálogo, con namespaces `bronze`, `silver`, `gold` y `audit`.
- Particionado Iceberg: vuelos y eventos por `day(started_at)`; telemetría por `day(ts)`.
- Mantenimiento: una tarea semanal corre `expire_snapshots` (retener 7 días) y `optimize` vía Trino.

RustFS es joven (serie 1.0 en beta): se fija un tag concreto y solo se usa la API S3 estándar con *path-style*, para que cambiar a otro almacenamiento S3 compatible no toque el resto del diseño.

## Ingesta

La ingesta tiene dos pasos separados: *extract* baja la API a la zona landing sin tocar los datos, y *load* convierte esos archivos en filas de tablas bronze Iceberg. Separarlos permite reprocesar bronze desde landing sin volver a llamar a la API.

El script existente del usuario se empaqueta como paquete Python `drone_ingest` con un CLI:

```bash
drone-ingest extract --entity flights --date 2026-10-01 --run-id <id>
drone-ingest load-bronze --entity flights --date 2026-10-01 --run-id <id>
```

Reglas del *extract*:

- Pagina hasta agotar `next_page`; escribe NDJSON gzip, un archivo por página, en la ruta de landing de la sección anterior.
- Reintentos con backoff exponencial (5 intentos) ante 5xx, timeouts y 429; respeta `Retry-After`.
- Escribe un `_manifest.json` al final con conteo de registros, páginas y checksum; sin manifest, la corrida se considera incompleta.
- Eventos y telemetría se piden por cada `flight_id` del día, con concurrencia limitada (8 peticiones a la vez).

Reglas del *load-bronze*:

- Escribe con PyIceberg (SqlCatalog contra el Postgres del catálogo) en `bronze.flights_raw`, `bronze.flight_events_raw`, `bronze.telemetry_raw`, `bronze.drones_raw`.
- Cada fila guarda el JSON original en `payload` (string) más metadatos: `_ingest_date`, `_run_id`, `_source_file`, `_ingested_at`, y las llaves mínimas para particionar (`flight_id`, `started_at`).
- Idempotente: sobrescribe la partición `_ingest_date` completa, así que re-correr un día no duplica.
- Registros que no son JSON válido o no traen `flight_id` van a `bronze.rejected_records` con el motivo; no detienen la corrida.
- Cada corrida inserta una fila en `audit.ingestion_runs` (entidad, fecha, run\_id, registros leídos, cargados, rechazados, duración).

Bronze no limpia ni deduplica: es la verdad cruda, versionada por Iceberg.

## Orquestación con Airflow

Airflow 3.x decide cuándo y en qué orden corre cada paso; no mueve datos él mismo. Se usa `LocalExecutor` con metadata en Postgres (sin Celery ni Redis), y [Astronomer Cosmos](https://github.com/astronomer/astronomer-cosmos) para que cada modelo dbt aparezca como su propia tarea.

| DAG | Disparo | Tareas principales |
| --- | --- | --- |
| `drone_ingest_daily` | Diario 02:00 America/Hermosillo, `catchup=True` desde la fecha de inicio | `api_healthcheck` → `extract_drones` y `extract_flights` → `extract_events` y `extract_telemetry` → `validate_manifests` → `load_bronze` (mapeado por entidad) → publica assets `bronze.*` |
| `drone_transform` | Assets de bronze actualizados (data-aware scheduling) | `dbt source freshness` → `dbt seed` → grupo Cosmos silver (run + test por modelo) → grupo Cosmos gold → `dbt docs generate` → `render_charts`; los domingos, además, `lakehouse_maintenance` |
| `drone_backfill` | Manual, parámetros `start_date` y `end_date` | Reutiliza las tareas de ingesta por fecha y dispara `drone_transform` al final |

Políticas comunes:

- `retries=3`, backoff exponencial desde 2 minutos; `max_active_runs=1` en transformación para no escribir la misma tabla en paralelo.
- Pool `api_pool` (8 slots) limita la concurrencia contra la API.
- Logging: los logs de cada tarea quedan en un volumen local y se ven en la UI de Airflow; `drone_ingest` y dbt escriben a stdout con nivel, `run_id` y entidad en cada línea. No hay stack de monitoreo aparte.
- Conexiones y secretos por variables de entorno (`AIRFLOW_CONN_*`), nunca en el código de los DAGs.
- dbt corre en un virtualenv propio dentro de la imagen de Airflow para no mezclar dependencias.

## Transformación con dbt

dbt (adaptador `dbt-trino`, catálogo `iceberg`) convierte bronze en silver y gold usando solo SQL; Trino ejecuta las queries y escribe tablas Iceberg de vuelta en RustFS. Bronze lo escribe la ingesta, así que en dbt aparece como `source`, no como modelo.

| Capa | Modelo | Materialización | Qué hace |
| --- | --- | --- | --- |
| silver | `stg_flights` | incremental, `merge` por `flight_id` | Parsea `payload`, castea timestamps a UTC, normaliza unidades (ft → m, km/h → m/s), deduplica quedándose con el `_ingested_at` más reciente |
| silver | `stg_flight_events` | incremental, `merge` por `event_id` | Parsea eventos, normaliza `severity`, descarta eventos fuera de la ventana del vuelo |
| silver | `stg_telemetry` | incremental, `append` por día | Parsea muestras 1 Hz, descarta coordenadas imposibles |
| silver | `snap_drones` | snapshot dbt (SCD tipo 2) | Historial de firmware y atributos de cada dron |
| silver | `dim_drone`, `dim_site`, `dim_date` | table | Dimensiones conformadas; `dim_date` generada con macro |
| silver | `fct_flight` | incremental, `merge` | Un registro por vuelo con llaves a dimensiones y métricas derivadas: duración, consumo de batería por minuto, banda de viento |
| silver | `fct_telemetry_1min` | incremental | Telemetría reducida a 1 minuto (promedio, máx.) |
| gold | `mart_flight_hours_by_type_month` | table | Horas de vuelo y número de vuelos por tipo de dron y mes |
| gold | `mart_altitude_by_wind_band` | table | Altitud media y máxima por banda de viento y tipo de dron |
| gold | `mart_flight_outcomes_daily` | table | Vuelos completados, abortados, aterrizajes de emergencia y accidentes por día |
| gold | `mart_battery_efficiency` | table | Batería consumida por km y por minuto, por modelo y temperatura |
| gold | `mart_drone_utilization` | table | Horas de uso por dron y días desde el último vuelo |

Calidad de datos:

- Tests genéricos: `unique` y `not_null` en llaves, `accepted_values` en `drone_type`, `status`, `mission_type`, `relationships` de hechos a dimensiones.
- Rangos con `dbt-expectations`: altitud 0–500 m, batería 0–100 %, `ended_at >= started_at`, velocidad 0–50 m/s.
- `source freshness` sobre `_ingested_at`: aviso a las 26 h, error a las 48 h.
- Contratos de modelo (`contract: enforced`) en todos los modelos gold: tipos y columnas fijos para que los dashboards no se rompan en silencio.
- Tests con severidad `error` detienen el DAG; los de severidad `warn` solo alertan.

Convenciones: seeds para catálogos pequeños (`wind_bands.csv`, `drone_type_specs.csv`); macro `generate_schema_name` para que cada capa caiga en su namespace (`silver`, `gold`) sin prefijos; `dbt docs` generado en cada corrida dentro de target/ (se abre localmente, sin servicio aparte).

## Motor de consultas: Trino

Trino es el único motor SQL del lakehouse: no guarda datos, lee y escribe tablas Iceberg a través del catálogo JDBC. Corre como un solo nodo (el coordinador también ejecuta trabajo), sin autenticación ni TLS; los clientes solo se identifican por nombre de usuario (`dbt`, `airflow`, `charts`) para distinguirlos en la UI de consultas.

Catálogo `iceberg` (`trino/catalog/iceberg.properties`):

```properties
connector.name=iceberg
iceberg.catalog.type=jdbc
iceberg.jdbc-catalog.catalog-name=drones
iceberg.jdbc-catalog.driver-class=org.postgresql.Driver
iceberg.jdbc-catalog.connection-url=jdbc:postgresql://postgres:5432/iceberg
iceberg.jdbc-catalog.connection-user=${ENV:ICEBERG_DB_USER}
iceberg.jdbc-catalog.connection-password=${ENV:ICEBERG_DB_PASSWORD}
iceberg.jdbc-catalog.default-warehouse-dir=s3://lakehouse/
iceberg.file-format=PARQUET
iceberg.compression-codec=ZSTD
fs.native-s3.enabled=true
s3.endpoint=http://rustfs:9000
s3.path-style-access=true
s3.region=us-east-1
s3.aws-access-key=${ENV:S3_ACCESS_KEY}
s3.aws-secret-key=${ENV:S3_SECRET_KEY}
```

- PyIceberg debe usar el mismo `catalog-name` (`drones`) y la misma base, o Trino no verá las tablas bronze.
- Los nombres exactos de las propiedades se verifican contra la versión de Trino fijada, porque algunos cambian entre versiones.

## Visualización con dbt Charts

Los dashboards son archivos YAML versionados junto a los modelos dbt, compilados y servidos con [dbt Charts](https://pypi.org/project/dbt-charts/) (paquete `dbt-charts`, CLI `dct`). Consultan solo tablas gold vía Trino con el usuario `charts`. El paquete está en fase alpha (última versión estable 0.9.1, del 2 de octubre de 2026), así que se fija la versión exacta.

- Instalación: `pip install "dbt-charts[trino]==0.9.1"` (requiere Python 3.10–3.13).
- Ubicación: `dbt/charts/*.yml`, dentro del proyecto dbt, para que `ref()` resuelva los modelos gold y `dct impact <columna>` muestre qué boards rompe un cambio.
- Servicio `charts`: contenedor con `dct serve --host 0.0.0.0` como vista previa en vivo.
- Reportes estáticos: la tarea `render_charts` del DAG corre `dct render <board> --format html` y `--format pdf` y sube el resultado a `s3://reports/<fecha>/`.
- CI: `dct validate --strict` en cada cambio, sin necesidad de conectarse a Trino.

Boards iniciales:

| Board | Preguntas que responde | Modelos gold |
| --- | --- | --- |
| `fleet_overview.yml` | Vuelos y horas de vuelo por día; KPIs de la flota | `mart_flight_outcomes_daily`, `mart_flight_hours_by_type_month` |
| `flight_conditions.yml` | Cómo cambian altitud y desenlace con viento y temperatura | `mart_altitude_by_wind_band`, `mart_battery_efficiency` |
| `drone_health.yml` | Qué drones vuelan más, cuáles tienen más incidentes | `mart_drone_utilization`, `mart_flight_outcomes_daily` |
| `pipeline_health.yml` | Registros cargados y rechazados por corrida | `mart_pipeline_runs (vista gold sobre audit.ingestion_runs y resultados de dbt)` |

Esqueleto de board (formato documentado por dbt Charts; filtro por rango de fechas y tipo de dron):

```yaml
title: "Fleet overview"

variables:
  date_range:
    input: daterange
    default: ["2026-09-01", "2026-09-30"]
  drone_type:
    input: multiselect
    options:
      static: ["quadcopter", "hexacopter", "fixed_wing", "vtol"]

queries:
  q_hours:
    source: trino
    sql: |
      SELECT month, drone_type, flight_hours
      FROM {{ ref('mart_flight_hours_by_type_month') }}
      WHERE {{ filter_date_range('month', date_range) }}
        AND {{ filter('drone_type', drone_type) }}

charts:
  hours_trend:
    title: "Horas de vuelo por tipo de dron"
    query: q_hours
    type: line
    x: month
    y: flight_hours
    color: drone_type

rows:
  - title: "Uso de la flota"
    cols: [hours_trend]
```

Toda agregación vive en el SQL de gold o de la query del board, nunca en la capa del chart.

## Docker Compose

Un solo `docker-compose.yml`, sin profiles, con nueve servicios (cuatro son de Airflow). Todas las imágenes van con tag fijo definido en `.env`; el agente elige la versión estable vigente al implementar y la deja anotada.

| Servicio | Puerto host | Depende de |
| --- | --- | --- |
| `postgres` (bases `airflow` e `iceberg`) | 5432 | — |
| `rustfs` | 9000 API, 9001 consola | — |
| `rustfs-init` (cliente S3 que crea los buckets `landing`, `lakehouse`, `reports`) | — | rustfs |
| `trino` | 8085 | postgres, rustfs-init |
| `airflow-init` (migración y usuario admin) | — | postgres |
| `airflow-apiserver` | 8080 (UI) | airflow-init |
| `airflow-scheduler`, `airflow-dag-processor` | — | airflow-init |
| `charts` (`dct serve`) | 8088 | trino |

Reglas:

- Cada servicio tiene `healthcheck`; los `depends_on` usan `condition: service_healthy` o `service_completed_successfully` para los init.
- Una sola red; volúmenes nombrados para `rustfs-data`, `postgres-data` y `airflow-logs`.
- Secretos solo en `.env` (con `.env.example` en el repo); nada de credenciales en YAML versionado.
- Debe correr en una máquina con 8 GB de RAM.
- Un `Makefile` envuelve lo común: `make up`, `make down`, `make reset` (borra volúmenes), `make backfill START=… END=…`, `make test`.

## Estructura del repositorio

Un monorepo; cada carpeta de primer nivel corresponde a una pieza de la arquitectura.

```text
drone-lakehouse/
├── docker-compose.yml
├── .env.example
├── Makefile
├── README.md
├── ingest/                    # paquete drone_ingest (script del usuario)
│   ├── pyproject.toml
│   ├── src/drone_ingest/
│   │   ├── cli.py
│   │   ├── extract.py
│   │   ├── load_bronze.py
│   │   └── schemas.py         # modelos pydantic del contrato
│   └── tests/fixtures/        # respuestas JSON grabadas
├── airflow/
│   ├── Dockerfile             # Airflow + drone_ingest + venv de dbt
│   └── dags/
├── dbt/
│   ├── dbt_project.yml
│   ├── profiles.yml           # lee credenciales de env vars
│   ├── models/{sources,silver,gold}/
│   ├── snapshots/
│   ├── seeds/
│   ├── macros/
│   ├── tests/
│   └── charts/                # boards de dbt Charts
├── trino/
│   ├── etc/                   # config.properties, jvm.config
│   └── catalog/iceberg.properties
└── scripts/
    └── smoke_test.sh          # prueba de extremo a extremo
```

## Plan de implementación

Se construye en cinco fases; cada una termina solo cuando pasan sus criterios, y ninguna fase empieza con la anterior en rojo.

1. **Cimientos del lakehouse**: `postgres`, `rustfs`, `rustfs-init`, `trino` con el catálogo JDBC.
   - [ ] `CREATE TABLE iceberg.bronze.smoke` desde Trino crea archivos visibles en la consola de RustFS.
   - [ ] Un `SELECT` sobre esa tabla funciona tras reiniciar todos los contenedores.
2. **Ingesta**: paquete `drone_ingest` con `extract` y `load-bronze`.
   - [ ] Un día completo llega a landing con `_manifest.json` y a las cuatro tablas bronze, visibles desde Trino.
   - [ ] Re-correr el mismo día deja el mismo número de filas en bronze.
   - [ ] Los registros corruptos de los fixtures aparecen en `bronze.rejected_records`.
   - [ ] Pruebas unitarias del paquete en verde (`pytest`).
3. **Orquestación**: Airflow con `LocalExecutor`, DAGs `drone_ingest_daily` y `drone_backfill`.
   - [ ] Catchup de 7 días termina en verde sin intervención.
   - [ ] Una API caída produce reintentos y luego un fallo con log legible en la UI.
4. **Transformación**: proyecto dbt completo, DAG `drone_transform` con Cosmos.
   - [ ] `dbt build` en verde sobre los 7 días.
   - [ ] Duplicados y unidades mezcladas no llegan a silver (verificado con tests).
   - [ ] Borrar silver y gold y re-correr produce los mismos conteos.
5. **Visualización**: cuatro boards de dbt Charts y tarea `render_charts`.
   - [ ] `dct validate --strict` sin errores.
   - [ ] Los boards cargan en `localhost:8088` y los PDF aparecen en `s3://reports/`.

Definición de terminado global: desde un clon limpio, `cp .env.example .env && make up && ./scripts/smoke_test.sh` ingiere un día, transforma, renderiza un board y termina con código 0.

## Decisiones, supuestos y preguntas abiertas

| Decisión | Elegido | Descartado | Por qué |
| --- | --- | --- | --- |
| Alcance | Seis piezas: Airflow, RustFS, Iceberg, Trino, dbt, dbt Charts | Observabilidad, linaje, Celery, SSO | Over-engineering acotado: lo justo para un lakehouse real |
| Patrón | ELT | ETL | Cargar crudo y transformar dentro del lakehouse permite reprocesar sin la API |
| Procesamiento | Batch diario | Streaming | La fuente es una API por fecha |
| Object storage | RustFS | MinIO | MinIO dejó de ser una opción comunitaria viable; RustFS es S3 compatible y Apache 2.0 |
| Formato de tabla | Iceberg | Delta Lake | Soporte nativo en Trino y PyIceberg |
| Catálogo | JDBC en Postgres | REST (Lakekeeper), Hive Metastore | Cero servicios extra: reutiliza el Postgres de Airflow |
| Executor de Airflow | LocalExecutor | Celery + Redis | Una sola máquina; Celery no aporta aquí |
| Visualización | dbt Charts | Superset, Metabase | Dashboards como código junto a los modelos |

Supuestos (confirmar con el usuario):

- "Login" en la petición original se interpretó como *logging*; queda cubierto por los logs de tareas en Airflow.
- El "día" de una corrida es día UTC; los dashboards muestran hora America/Hermosillo.

Preguntas abiertas:

- [ ] ¿Cómo autentica la API real (API key, OAuth) y qué límites de tasa tiene?
- [ ] ¿El contrato real coincide con el de la sección de fuente? Si no, ajustar `schemas.py` y `stg_*`.
- [ ] Confirmar que PyIceberg (`SqlCatalog`) y Trino comparten tablas sin problemas en el catálogo JDBC con la versión elegida; es lo primero que valida la fase 2.
- [ ] RustFS y dbt Charts son proyectos jóvenes: si una versión rompe algo, fijar la anterior antes de cambiar de herramienta.

## Fuentes

- [dbt-charts en PyPI](https://pypi.org/project/dbt-charts/0.7.1/): CLI `dct`, formato de boards, extra `trino`, historial de versiones.
- [RustFS, instalación con Docker](https://docs.rustfs.com/de/installation/container/docker): imagen, puertos y variables de credenciales.
- [Astronomer Cosmos](https://github.com/astronomer/astronomer-cosmos): ejecución de modelos dbt como tareas de Airflow.

