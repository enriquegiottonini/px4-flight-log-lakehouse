{#-
  One row per log (latest version), parsed from the raw JSON payload and cleaned (CLAUDE.md 3.3).
  Incremental: each run reads only bronze rows ingested since the last run and MERGEs them by log_id,
  so a re-rated log replaces its previous row.
-#}
{{ config(
    materialized='incremental',
    incremental_strategy='merge',
    unique_key='log_id',
    on_schema_change='append_new_columns'
) }}

with source as (
    select * from {{ source('bronze', 'logs_index_raw') }}
    {% if is_incremental() %}
    where _ingested_at > (select max(_ingested_at) from {{ this }})
    {% endif %}
),

latest as (  -- bronze keeps every version of a record; silver keeps the newest
    select *, row_number() over (partition by log_id order by _ingested_at desc) as version_rank
    from source
),

parsed as (
    select
        log_id,
        log_date as uploaded_date,  -- the index date is the UPLOAD date, not the flight date
        json_extract_scalar(payload, '$.mav_type') as mav_type,
        nullif(trim(json_extract_scalar(payload, '$.sys_hw')), '') as sys_hw,
        try_cast(json_extract_scalar(payload, '$.sys_autostart_id') as integer) as sys_autostart_id,
        -- airframe_type is a string, or the SYS_AUTOSTART id (a number) when PX4 didn't recognize it
        case when starts_with(json_format(json_extract(payload, '$.airframe_type')), '"')
             then nullif(trim(json_extract_scalar(payload, '$.airframe_type')), '') end as airframe_type,
        nullif(trim(json_extract_scalar(payload, '$.airframe_name')), '') as airframe_name,
        nullif(trim(json_extract_scalar(payload, '$.vehicle_uuid')), '') as vehicle_uuid,
        nullif(trim(json_extract_scalar(payload, '$.vehicle_name')), '') as vehicle_name,
        -- wrapped-around uint64 counters and non-positive values are not durations
        case when try_cast(json_extract_scalar(payload, '$.duration_s') as bigint) between 1 and 86400
             then try_cast(json_extract_scalar(payload, '$.duration_s') as bigint) end as duration_s,
        nullif(try_cast(json_extract_scalar(payload, '$.wind_speed') as integer), -1) as wind_speed,
        nullif(trim(json_extract_scalar(payload, '$.rating')), '') as raw_rating,
        nullif(trim(json_extract_scalar(payload, '$.ver_sw')), '') as fw_git_hash,
        nullif(trim(json_extract_scalar(payload, '$.ver_sw_release')), '') as ver_sw_release,
        case when json_extract_scalar(payload, '$.estimator') like 'unknown%' then null
             else json_extract_scalar(payload, '$.estimator') end as estimator,
        try_cast(json_extract_scalar(payload, '$.num_logged_errors') as bigint) as num_logged_errors,
        try_cast(json_extract_scalar(payload, '$.num_logged_warnings') as bigint) as num_logged_warnings,
        json_extract_scalar(payload, '$.source') as upload_source,
        coalesce(json_extract_scalar(payload, '$.video_url'), '') <> '' as has_video,
        cast(json_extract(payload, '$.error_labels') as array(integer)) as error_label_ids,
        cast(json_extract(payload, '$.flight_modes') as array(integer)) as flight_mode_ids,
        cast(json_extract(payload, '$.flight_mode_durations') as array(array(bigint))) as flight_mode_durations,
        payload_hash,
        _change_type as last_change_type,
        _ingested_at
    from latest
    where version_rank = 1
)

select
    p.log_id,
    p.uploaded_date,
    p.mav_type,
    coalesce(c.vehicle_class, 'other') as vehicle_class,
    upper(coalesce(p.sys_hw, '')) like '%SITL%' as is_simulation,
    p.sys_hw,
    p.sys_autostart_id,
    p.airframe_type,
    p.airframe_name,
    p.airframe_type is not null as is_airframe_known,
    p.vehicle_uuid,
    p.vehicle_name,
    p.duration_s,
    p.wind_speed,
    r.rating,
    coalesce(r.is_crash, false) as is_crash,
    p.fw_git_hash,
    p.ver_sw_release,
    -- "v1.15.4 0" -> "1.15"; v0.0.x are developer builds, treated as unknown
    nullif(regexp_extract(p.ver_sw_release, '^v(\d+\.\d+)', 1), '0.0') as fw_major_minor,
    p.estimator,
    p.num_logged_errors,
    p.num_logged_warnings,
    p.upload_source,
    p.has_video,
    p.error_label_ids,
    p.flight_mode_ids,
    p.flight_mode_durations,
    p.payload_hash,
    p.last_change_type,
    p._ingested_at
from parsed p
left join {{ ref('mav_type_classes') }} c on p.mav_type = c.mav_type
left join {{ ref('rating_map') }} r on p.raw_rating = r.raw_rating
