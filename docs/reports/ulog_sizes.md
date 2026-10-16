# ULog size sample

- Window: log_date in (2026-10-06, 2026-10-13], 3,582 logs (~512/day)
- Sample: 200 random logs (seed 42); HTTP status: {200: 200}

| stat | MB |
| --- | --- |
| min | 0.16 |
| median | 6.50 |
| mean | 18.08 |
| p95 | 88.59 |
| max | 151.28 |

- Throughput: median 55.6 KB per second of flight

## Projection (mean size x logs/day)

| window | logs | GB |
| --- | --- | --- |
| 1 day | 512 | 9.3 |
| 7 days | 3,582 | 64.8 |
| 14 days (ULOG_RETENTION_DAYS) | 7,164 | 129.5 |

## By vehicle class (sample)

| mav_type | n | median MB | mean MB |
| --- | --- | --- | --- |
| Quadrotor | 138 | 5.53 | 14.72 |
| Fixed Wing | 15 | 5.60 | 17.43 |
| Octorotor | 10 | 19.51 | 36.69 |
| VTOL Standard | 9 | 26.50 | 37.77 |
| Hexarotor | 8 | 31.00 | 48.05 |
| Tiltrotor VTOL | 8 | 3.65 | 8.21 |
| Coaxial helicopter | 5 | 6.40 | 12.51 |
| unknown type | 2 | 12.61 | 12.61 |
| Two-rotor VTOL (Tailsitter) | 2 | 0.88 | 0.88 |
| Quad-rotor VTOL (Tailsitter) | 2 | 35.68 | 35.68 |
| Tricopter | 1 | 5.38 | 5.38 |

Largest in sample:

- 151 MB, 258 s, Hexarotor, PX4_FMU_V6X
- 143 MB, 201 s, Quadrotor, CUAV_X25_EVO
- 141 MB, 200 s, Octorotor, CUAV_FMU_V6X
- 133 MB, 775 s, VTOL Standard, CUAV_X7PRO
- 115 MB, 386 s, Quadrotor, PX4_SITL
