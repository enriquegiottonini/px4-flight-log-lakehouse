-- Calendar from the first PX4 upload to today (macro: macros/date_spine.sql).
with days as (
    {{ date_spine("date '2016-12-01'", "current_date") }}
)
select
    date_day,
    year(date_day) as year,
    month(date_day) as month,
    date_trunc('month', date_day) as month_start,
    week(date_day) as iso_week,
    day_of_week(date_day) as day_of_week,  -- 1 = Monday
    day_of_week(date_day) in (6, 7) as is_weekend
from days
