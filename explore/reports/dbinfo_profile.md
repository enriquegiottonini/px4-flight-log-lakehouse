# PX4 index profile

- Records: **477,079**
- ETag: `"1c9a6350c1eefb62e7e34d95a9f5d3a0-4"`, Last-Modified: Wed, 14 Oct 2026 00:03:24 GMT
- Compressed size: 32.6 MB

## Fields

| field | python types | empty "" / [] | missing key | distinct |
| --- | --- | --- | --- | --- |
| `airframe_name` | str 477,079 | 122,768 (25.7 %) | 0 | 56 |
| `airframe_type` | str 354,311, int 122,768 | 0 (0.0 %) | 0 | 851 |
| `description` | str 477,079 | 411,934 (86.3 %) | 0 | 34,386 |
| `download_url` | str 477,079 | 0 (0.0 %) | 0 | 477,079 |
| `duration_s` | int 477,079 | 0 (0.0 %) | 0 | 3,830 |
| `error_labels` | list 477,079 | 475,817 (99.7 %) | 0 | 100 |
| `estimator` | str 477,079 | 0 (0.0 %) | 0 | 7 |
| `feedback` | str 477,079 | 439,076 (92.0 %) | 0 | 6,684 |
| `flight_mode_durations` | list 477,079 | 9,242 (1.9 %) | 0 | 181,268 |
| `flight_modes` | list 477,079 | 9,242 (1.9 %) | 0 | 2,986 |
| `log_date` | str 477,079 | 0 (0.0 %) | 0 | 3,263 |
| `log_id` | str 477,079 | 0 (0.0 %) | 0 | 477,079 |
| `mav_type` | str 477,079 | 0 (0.0 %) | 0 | 24 |
| `num_logged_errors` | int 477,079 | 0 (0.0 %) | 0 | 1,945 |
| `num_logged_warnings` | int 477,079 | 0 (0.0 %) | 0 | 1,959 |
| `rating` | str 477,079 | 454,085 (95.2 %) | 0 | 10 |
| `source` | str 477,079 | 0 (0.0 %) | 0 | 11 |
| `sys_autostart_id` | int 477,079 | 0 (0.0 %) | 0 | 881 |
| `sys_hw` | str 477,079 | 2,432 (0.5 %) | 0 | 731 |
| `type` | str 477,079 | 0 (0.0 %) | 0 | 1 |
| `vehicle_name` | str 477,079 | 455,190 (95.4 %) | 0 | 434 |
| `vehicle_uuid` | str 477,079 | 45,089 (9.5 %) | 0 | 38,092 |
| `ver_sw` | str 477,079 | 2,242 (0.5 %) | 0 | 14,178 |
| `ver_sw_release` | str 477,079 | 1,994 (0.4 %) | 0 | 1,136 |
| `video_url` | str 477,079 | 476,911 (100.0 %) | 0 | 124 |
| `wind_speed` | int 477,079 | 0 (0.0 %) | 0 | 5 |

## Keys

- Duplicate `log_id`s: 0
- `log_id` not a UUID: 0
- `download_url` == `https://cdn.logs.px4.io/<log_id>.ulg`: 477,079 (100.0 %)

## Sentinels and dirty values

### `wind_speed`

| value | count | share |
| --- | --- | --- |
| -1 | 453,751 | 95.1 % |
| 0 | 18,349 | 3.8 % |
| 5 | 4,107 | 0.9 % |
| 8 | 470 | 0.1 % |
| 10 | 402 | 0.1 % |

### `rating`

| value | count | share |
| --- | --- | --- |
| `''` | 454,085 | 95.2 % |
| `'good'` | 18,329 | 3.8 % |
| `'great'` | 2,903 | 0.6 % |
| `'unsatisfactory'` | 1,020 | 0.2 % |
| `'crash_sw_hw'` | 402 | 0.1 % |
| `'crash_pilot'` | 188 | 0.0 % |
| `'BRAVO!'` | 148 | 0.0 % |
| `'none'` | 2 | 0.0 % |
| `'BRAWO!'` | 1 | 0.0 % |
| `'1'` | 1 | 0.0 % |

### `airframe_type`

- Types: {'str': 354311, 'int': 122768}
- int values equal to `sys_autostart_id`: 122,768 of 122,768
- Top int values: [(4011, 27648), (10016, 6676), (0, 4506), (10015, 4102), (15001, 4036)]

### `ver_sw_release`

- Empty: 1,994 (0.4 %)
- Parseable as `vX.Y.Z`: 475,085 (99.6 %)
- Unparseable non-empty examples: []
- Top major.minor:

| release | count |
| --- | --- |
| v1.15 | 106,643 |
| v1.14 | 103,231 |
| v1.16 | 65,961 |
| v1.13 | 63,623 |
| v1.12 | 30,234 |
| v1.17 | 28,937 |
| v1.11 | 15,741 |
| v1.8 | 8,416 |
| v1.7 | 7,287 |
| v0.0 | 5,910 |

## Categorical distributions

### `mav_type`

| mav_type | count | share |
| --- | --- | --- |
| Quadrotor | 325,190 | 68.2 % |
| Hexarotor | 37,649 | 7.9 % |
| Fixed Wing | 28,480 | 6.0 % |
| VTOL Standard | 25,747 | 5.4 % |
| Octorotor | 19,159 | 4.0 % |
| Tiltrotor VTOL | 11,209 | 2.3 % |
| unknown type | 6,195 | 1.3 % |
| Coaxial helicopter | 4,551 | 1.0 % |
| Normal helicopter with tail rotor | 4,511 | 0.9 % |
| Two-rotor VTOL (Tailsitter) | 4,054 | 0.8 % |
| Quad-rotor VTOL (Tailsitter) | 3,126 | 0.7 % |
| Ground Rover | 2,791 | 0.6 % |
| Generic | 1,712 | 0.4 % |
| Tricopter | 1,610 | 0.3 % |
| Surface Vessel, Boat, Ship | 381 | 0.1 % |
| VTOL reserved 4 | 275 | 0.1 % |
| VTOL Tailsitter | 122 | 0.0 % |
| Submarine | 99 | 0.0 % |
| Rocket | 73 | 0.0 % |
| Airship, controlled | 71 | 0.0 % |
| Free balloon, uncontrolled | 48 | 0.0 % |
| VTOL reserved 3 | 23 | 0.0 % |
| Ground installation | 2 | 0.0 % |
| VTOL reserved 5 | 1 | 0.0 % |

### `source`

| source | count |
| --- | --- |
| `'webui'` | 464,356 |
| `'QGroundControl'` | 11,462 |
| `'auto'` | 967 |
| `'auto-upload'` | 207 |
| `'api'` | 50 |
| `'automation'` | 21 |
| `'lazypx4'` | 11 |
| `'codex'` | 2 |

### `type`

| type | count |
| --- | --- |
| `'flightreport'` | 477,079 |

### `estimator`

| estimator | count |
| --- | --- |
| `'EKF2'` | 473,615 |
| `'Q'` | 2,367 |
| `'LPE'` | 617 |
| `'INAV'` | 409 |
| `'unknown (None)'` | 69 |
| `'unknown (5)'` | 1 |
| `'unknown (4)'` | 1 |

## Flight modes

- Logs with no modes: 9,242
- Malformed `flight_mode_durations` pairs: 0
- Mode IDs missing from the lookup table: [7, 9, 11, 16, 31, 32, 42, 63, 72, 73, 80, 112, 187, 192, 255]

| id | name | logs using it | total hours |
| --- | --- | --- | --- |
| 2 | Position | 223,560 | 1,344,781,819,148 |
| 15 | Stabilized | 146,837 | 406,343,544,055 |
| 1 | Altitude | 105,487 | 95,351,435,361 |
| 4 | Loiter | 87,280 | 171,407,947,081 |
| 14 | Offboard | 81,375 | 117,566,145,357 |
| 0 | Manual | 79,705 | 333,851,965,167 |
| 3 | Mission | 76,562 | 74,738,656,680 |
| 5 | Return to Land | 54,714 | 18,016,824,424 |
| 18 | Land | 45,477 | 84,555,414,834 |
| 17 | Takeoff | 30,538 | 49,496,559,409 |
| 12 | Descend | 9,161 | 5,123,656,855 |
| 10 | Acro | 6,137 | 8,967,235,523 |
| 23 | External 1 | 3,216 | 26,903,457,238 |
| 13 | Terminate | 2,574 | 487,131 |
| 6 | Position (Slow) | 1,396 | 51 |

## Error labels

- Logs with at least one label: 1,262

| id | name | logs |
| --- | --- | --- |
| 2 | Vibration | 529 |
| 4 | Sensor-error | 342 |
| 1 | Other | 243 |
| 6 | Software | 219 |
| 3 | Airframe-design | 211 |
| 7 | Human-error | 181 |
| 8 | External-conditions | 172 |
| 5 | Component-failure | 167 |

## Numeric fields

| field | min | median | p95 | max | <= 0 |
| --- | --- | --- | --- | --- | --- |
| `duration_s` | 0 | 81 | 764 | 18446744073684 | 7414 |
| `num_logged_errors` | 0 | 0 | 4 | 381204 | 380808 |
| `num_logged_warnings` | 0 | 2 | 35 | 226275 | 157823 |

## `log_date`

- Range: 2016-12-09 -> 2026-10-13
- Logs/day over the last 90 full days: median 591, p95 858, max 1052
- Logs with `log_date >= 2025-01-01` (default INDEX_START_DATE): 314,800

| year | logs |
| --- | --- |
| 2016 | 77 |
| 2017 | 6,234 |
| 2018 | 11,856 |
| 2019 | 5,980 |
| 2020 | 4,150 |
| 2021 | 2,065 |
| 2022 | 1,801 |
| 2023 | 7,078 |
| 2024 | 123,038 |
| 2025 | 163,457 |
| 2026 | 151,343 |

Last 14 days:

| log_date | logs |
| --- | --- |
| 2026-10-13 | 548 |
| 2026-10-12 | 629 |
| 2026-10-11 | 269 |
| 2026-10-10 | 446 |
| 2026-10-09 | 546 |
| 2026-10-08 | 729 |
| 2026-10-07 | 415 |
| 2026-10-06 | 412 |
| 2026-10-05 | 416 |
| 2026-10-04 | 239 |
| 2026-10-03 | 218 |
| 2026-10-02 | 258 |
| 2026-10-01 | 294 |
| 2026-09-30 | 417 |

## Vehicles

- Distinct non-empty `vehicle_uuid`: 38,091
- Logs without `vehicle_uuid`: 45,089
- Logs per vehicle: median 3, max 3,373
- Distinct `sys_hw`: 731; top: [('PX4_FMU_V6C', 78987), ('PX4_FMU_V5', 60220), ('PX4_FMU_V6X', 59564), ('PX4_SITL', 35638), ('CUAV_X7PRO', 27179), ('PX4_FMU_V3', 18128)]
