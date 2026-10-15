-- The most common PX4 warnings/errors, grouped by template (numbers replaced by '#').
select
    m.level,
    m.module,
    m.message_template,
    count(*) as occurrences,
    count(distinct m.log_id) as logs_affected,
    min(m.uploaded_date) as first_seen,
    max(m.uploaded_date) as last_seen
from {{ ref('stg_log_messages') }} m
join {{ ref('stg_logs') }} l on m.log_id = l.log_id
where m.level in ('WARNING', 'ERROR', 'CRITICAL', 'EMERGENCY', 'ALERT') and {{ real_flights('l') }}
group by 1, 2, 3
