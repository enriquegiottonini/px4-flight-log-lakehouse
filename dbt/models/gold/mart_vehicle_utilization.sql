-- How much each vehicle flies, and how long since its last upload.
select
    f.vehicle_uuid,
    v.vehicle_class,
    v.sys_hw,
    count(*) as logs,
    cast(coalesce(sum(f.duration_s), 0) / 3600e0 as double) as flight_hours,
    count_if(f.is_crash) as crash_logs,
    min(f.uploaded_date) as first_upload,
    max(f.uploaded_date) as last_upload,
    cast(date_diff('day', max(f.uploaded_date), current_date) as bigint) as days_since_last_upload
from {{ ref('fct_flight') }} f
join {{ ref('dim_vehicle') }} v on f.vehicle_uuid = v.vehicle_uuid
where {{ real_flights('f') }}
group by 1, 2, 3
