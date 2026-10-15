-- One row per log: index attributes + telemetry aggregates (for the logs whose ULog was parsed).
with telemetry as (
    select
        log_id,
        min(ts_utc) as flight_started_at,        -- real flight time (GPS), unlike uploaded_date
        count(*) as telemetry_seconds,
        max(alt_m) as max_alt_amsl_m,
        max(alt_m) - min(alt_m) as alt_range_m,  -- climb above the lowest point, a proxy for flight height
        max(h_speed_ms) as max_h_speed_ms,
        avg(h_speed_ms) as avg_h_speed_ms,
        sum(h_speed_ms) as distance_m,           -- 1 Hz rows: speed x 1 s
        min_by(battery_remaining, t_boot_s) filter (where battery_remaining is not null) as battery_start,
        max_by(battery_remaining, t_boot_s) filter (where battery_remaining is not null) as battery_end,
        count(battery_remaining) as battery_seconds
    from {{ ref('stg_telemetry') }}
    group by 1
),

labels as (
    select log_id, count(*) as error_label_count
    from {{ ref('stg_log_error_labels') }}
    group by 1
)

select
    l.log_id,
    l.uploaded_date,
    l.vehicle_uuid,
    l.mav_type,
    l.vehicle_class,
    l.is_simulation,
    l.sys_hw,
    l.airframe_name,
    l.fw_major_minor,
    l.duration_s,
    b.duration_band,
    b.band_order as duration_band_order,
    l.rating,
    l.is_crash,
    coalesce(lb.error_label_count, 0) as error_label_count,
    l.num_logged_errors,
    l.num_logged_warnings,
    l.wind_speed,
    t.log_id is not null as has_telemetry,
    t.flight_started_at,
    t.telemetry_seconds,
    t.max_alt_amsl_m,
    t.alt_range_m,
    t.max_h_speed_ms,
    t.avg_h_speed_ms,
    t.distance_m,
    (t.battery_start - t.battery_end) * 100 as battery_used_pct,
    case when t.battery_seconds >= 60
         then (t.battery_start - t.battery_end) * 100 / (t.battery_seconds / 60.0) end as battery_pct_per_min,
    case when t.distance_m >= 100 and t.battery_seconds >= 60
         then (t.battery_start - t.battery_end) * 100 / (t.distance_m / 1000.0) end as battery_pct_per_km
from {{ ref('stg_logs') }} l
left join telemetry t on l.log_id = t.log_id
left join labels lb on l.log_id = lb.log_id
left join {{ ref('duration_bands') }} b on l.duration_s >= b.min_s and l.duration_s < b.max_s
