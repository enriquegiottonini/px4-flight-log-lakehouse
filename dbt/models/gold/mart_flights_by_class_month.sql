-- Fleet activity: logs and flight hours per vehicle class and upload month.
select
    cast(date_trunc('month', uploaded_date) as date) as month,
    vehicle_class,
    count(*) as logs,
    cast(coalesce(sum(duration_s), 0) / 3600e0 as double) as flight_hours,
    cast(avg(duration_s) / 60e0 as double) as avg_duration_min,
    count_if(is_crash) as crash_logs
from {{ ref('fct_flight') }}
where {{ real_flights() }}
group by 1, 2
