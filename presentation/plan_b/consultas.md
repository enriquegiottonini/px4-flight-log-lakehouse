# Plan B: resultados de consultas (Trino)

Capturados el 2026-10-15 04:26 UTC con `make trino`, para mostrar sin red si el stack no levanta.
Los dashboards equivalentes están en los PDF de esta carpeta.

### Filas por capa (bronze → silver → gold)

```sql
SELECT 'bronze.logs_index_raw' AS tabla, count(*) AS filas FROM iceberg.bronze.logs_index_raw UNION ALL SELECT 'bronze.telemetry_raw', count(*) FROM iceberg.bronze.telemetry_raw UNION ALL SELECT 'silver.stg_logs', count(*) FROM iceberg.silver.stg_logs UNION ALL SELECT 'silver.fct_flight', count(*) FROM iceberg.silver.fct_flight UNION ALL SELECT 'silver.fct_mode_segment', count(*) FROM iceberg.silver.fct_mode_segment UNION ALL SELECT 'gold.mart_flights_by_class_month', count(*) FROM iceberg.gold.mart_flights_by_class_month
```

| tabla                                |  filas |
| ------------------------------------ | ------:|
| gold.mart\_flights\_by\_class\_month |    132 |
| silver.fct\_flight                   | 315402 |
| silver.fct\_mode\_segment            | 947512 |
| silver.stg\_logs                     | 315402 |
| bronze.telemetry\_raw                |  10297 |
| bronze.logs\_index\_raw              | 315402 |

### Logs y horas de vuelo por clase de vehículo (sin simuladores)

```sql
SELECT vehicle_class, sum(logs) AS logs, round(sum(flight_hours)) AS horas, sum(crash_logs) AS choques FROM iceberg.gold.mart_flights_by_class_month GROUP BY 1 ORDER BY 2 DESC
```

| vehicle_class |   logs |   horas | choques |
| ------------- | ------:| -------:| -------:|
| multirotor    | 235355 | 11552.0 |      79 |
| vtol          |  25142 |  2215.0 |       0 |
| fixed\_wing   |  16554 |  1563.0 |       0 |
| other         |   6521 |   258.0 |      12 |
| helicopter    |   5769 |   309.0 |       0 |
| rover         |   1414 |   118.0 |       0 |

### Modos de vuelo de los multirrotores

```sql
SELECT mode_name, round(hours) AS horas, round(100 * share_of_class_time, 1) AS pct_del_tiempo FROM iceberg.gold.mart_flight_mode_usage WHERE vehicle_class = 'multirotor' ORDER BY hours DESC LIMIT 6
```

| mode_name  |  horas | pct_del_tiempo |
| ---------- | ------:| --------------:|
| Position   | 4512.0 |           39.5 |
| Offboard   | 1547.0 |           13.6 |
| Mission    | 1408.0 |           12.3 |
| Loiter     |  984.0 |            8.6 |
| Stabilized |  979.0 |            8.6 |
| Altitude   |  784.0 |            6.9 |

### Versión de firmware en septiembre 2026

```sql
SELECT fw_major_minor, logs, round(100 * share_of_month, 1) AS pct FROM iceberg.gold.mart_firmware_adoption WHERE month = date '2026-09-01' ORDER BY logs DESC LIMIT 6
```

| fw_major_minor | logs |  pct |
| -------------- | ----:| ----:|
| 1.17           | 3943 | 27.4 |
| 1.16           | 2814 | 19.6 |
| 1.15           | 2491 | 17.3 |
| 1.14           | 1922 | 13.4 |
| 1.13           |  877 |  6.1 |
| 1.18           |  554 |  3.9 |

### Mensajes de PX4 más extendidos (por logs afectados)

```sql
SELECT level, module, substr(message_template, 1, 70) AS mensaje, logs_affected AS logs FROM iceberg.gold.mart_top_log_messages ORDER BY logs_affected DESC, occurrences DESC LIMIT 6
```

| level   | module                      | mensaje                                                                   | logs |
| ------- | --------------------------- | ------------------------------------------------------------------------- | ----:|
| WARNING | health\_and\_arming\_checks | \[health\_and\_arming\_checks\] Preflight Fail: Flight termination active |   33 |
| WARNING | health\_and\_arming\_checks | \[health\_and\_arming\_checks\] Preflight Fail: Kill switch engaged       |   27 |
| WARNING | commander                   | \[commander\] Kill engaged                                                |   26 |
| WARNING | failsafe                    | \[failsafe\] Failsafe activated                                           |   13 |
| WARNING | commander                   | \[commander\] Disarming denied: not landed                                |    8 |
| WARNING | health\_and\_arming\_checks | \[health\_and\_arming\_checks\] Preflight Fail: Attitude failure \(roll\) |    6 |

### Time travel: snapshots de una tabla Iceberg

```sql
SELECT committed_at, operation, element_at(summary, 'added-records') AS filas_agregadas FROM iceberg.silver."stg_telemetry$snapshots" ORDER BY committed_at
```

| committed_at                | operation | filas_agregadas |
| --------------------------- | --------- | --------------- |
| 2026-10-14 23:40:24.990 UTC | append    | 9955            |
| 2026-10-15 01:19:51.261 UTC | append    | 94              |
| 2026-10-15 02:17:54.747 UTC | append    | 248             |
