-- Current version of each vehicle (from the SCD2 snapshot) plus how many versions it has had.
select
    s.vehicle_uuid,
    s.sys_hw,
    s.mav_type,
    s.vehicle_class,
    s.airframe_type,
    s.airframe_name,
    s.fw_major_minor,
    s.last_uploaded_date,
    s.dbt_valid_from as current_since,
    v.versions
from {{ ref('snap_vehicles') }} s
join (select vehicle_uuid, count(*) as versions from {{ ref('snap_vehicles') }} group by 1) v
    on s.vehicle_uuid = v.vehicle_uuid
where s.dbt_valid_to is null
