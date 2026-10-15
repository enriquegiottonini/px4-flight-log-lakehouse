-- Daily quality signals: crash ratings, pilot error labels, and errors PX4 logged itself.
select
    uploaded_date,
    count(*) as logs,
    count_if(is_crash) as crash_logs,
    count_if(rating = 'unsatisfactory') as unsatisfactory_logs,
    count_if(error_label_count > 0) as logs_with_error_labels,
    count_if(num_logged_errors > 0) as logs_with_logged_errors,
    cast(coalesce(sum(num_logged_errors), 0) as bigint) as logged_errors,
    cast(count_if(num_logged_errors > 0) / cast(count(*) as double) as double) as share_logs_with_errors
from {{ ref('fct_flight') }}
where {{ real_flights() }}
group by 1
