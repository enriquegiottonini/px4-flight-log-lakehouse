-- Which PX4 release line (major.minor) the uploaded logs ran, per month.
with monthly as (
    select
        cast(date_trunc('month', uploaded_date) as date) as month,
        coalesce(fw_major_minor, 'unknown') as fw_major_minor,
        count(*) as logs
    from {{ ref('fct_flight') }}
    where {{ real_flights() }}
    group by 1, 2
)
select
    month,
    fw_major_minor,
    logs,
    cast(logs / cast(sum(logs) over (partition by month) as double) as double) as share_of_month
from monthly
