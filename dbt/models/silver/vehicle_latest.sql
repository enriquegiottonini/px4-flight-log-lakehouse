-- Current attributes of each vehicle = those of its most recent log. Input of the snap_vehicles snapshot.
select
    vehicle_uuid,
    sys_hw,
    mav_type,
    vehicle_class,
    airframe_type,
    airframe_name,
    fw_major_minor,
    uploaded_date as last_uploaded_date
from (
    select *, row_number() over (partition by vehicle_uuid order by uploaded_date desc, _ingested_at desc, log_id) as rn
    from {{ ref('stg_logs') }}
    where vehicle_uuid is not null
)
where rn = 1
