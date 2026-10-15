-- How high and fast each vehicle class flies (only logs with parsed telemetry).
select
    vehicle_class,
    count(*) as flights_with_telemetry,
    cast(avg(alt_range_m) as double) as avg_alt_range_m,
    cast(approx_percentile(alt_range_m, 0.95) as double) as p95_alt_range_m,
    cast(avg(max_h_speed_ms) as double) as avg_max_h_speed_ms,
    cast(approx_percentile(max_h_speed_ms, 0.95) as double) as p95_max_h_speed_ms,
    cast(avg(distance_m) / 1000e0 as double) as avg_distance_km
from {{ ref('fct_flight') }}
where has_telemetry and {{ real_flights() }}
group by 1
