-- Telemetry reduced to one row per log and minute of flight (charts don't need 1 Hz).
select
    log_id,
    cast(t_boot_s / 60 as integer) as minute_of_log,
    min(ts_utc) as minute_started_at,
    avg(alt_m) as avg_alt_m,
    max(alt_m) as max_alt_m,
    avg(h_speed_ms) as avg_h_speed_ms,
    max(h_speed_ms) as max_h_speed_ms,
    avg(battery_remaining) as avg_battery_remaining,
    count(*) as seconds
from {{ ref('stg_telemetry') }}
group by 1, 2
