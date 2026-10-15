{#-
  1 Hz telemetry with impossible values nulled (not dropped: other columns of the same second stay usable).
  Incremental append: a log is parsed once (terminal status), so new rows never duplicate old ones.
-#}
{{ config(materialized='incremental', incremental_strategy='append') }}

with source as (
    select * from {{ source('bronze', 'telemetry_raw') }}
    {% if is_incremental() %}
    where _ingested_at > (
        -- coalesce: on an EMPTY target max() is NULL and `x > NULL` is never true, so nothing would
        -- ever be inserted (a first run before any data arrived left stg_telemetry empty for good)
        select coalesce(max(_ingested_at), timestamp '1970-01-01 00:00:00 UTC') from {{ this }})
    {% endif %}
),

battery as (  -- a battery stuck at 0 for the whole log means "no battery sensor"
    select log_id, max(battery_remaining) as max_remaining
    from source
    group by 1
)

select
    t.log_id,
    t.t_boot_s,
    t.ts_utc,
    t._log_date as uploaded_date,
    case when t.lat between -90 and 90 and t.lon between -180 and 180 and not (t.lat = 0 and t.lon = 0)
         then t.lat end as lat,
    case when t.lat between -90 and 90 and t.lon between -180 and 180 and not (t.lat = 0 and t.lon = 0)
         then t.lon end as lon,
    case when t.alt_m between -500 and 20000 then t.alt_m end as alt_m,  -- metres above sea level
    case when sqrt(t.vx * t.vx + t.vy * t.vy) <= 150 then sqrt(t.vx * t.vx + t.vy * t.vy) end as h_speed_ms,
    case when abs(t.vz) <= 100 then t.vz end as vz_ms,  -- NED frame: positive = descending
    case when b.max_remaining > 0 and t.battery_remaining between 0 and 1 then t.battery_remaining end as battery_remaining,
    case when t.battery_voltage_v > 0 then t.battery_voltage_v end as battery_voltage_v,
    t.battery_current_a,
    t.nav_state,
    t.arming_state,
    t._ingested_at
from source t
join battery b on t.log_id = b.log_id
