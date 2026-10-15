-- How each vehicle class spends its time across flight modes.
with mode_time as (
    select vehicle_class, mode_name, sum(segment_s) as seconds, count(distinct log_id) as logs_using_mode
    from {{ ref('fct_mode_segment') }}
    where {{ real_flights() }} and segment_s is not null
    group by 1, 2
)
select
    vehicle_class,
    mode_name,
    cast(seconds / 3600e0 as double) as hours,
    -- cast BEFORE dividing: bigint / bigint is integer division in Trino (the share would truncate to 0)
    cast(seconds as double) / sum(seconds) over (partition by vehicle_class) as share_of_class_time,
    logs_using_mode
from mode_time
