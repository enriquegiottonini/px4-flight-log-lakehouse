-- Error labels pilots attached to their logs: one row per (log, label).
select
    l.log_id,
    t.error_label_id
from {{ ref('stg_logs') }} l
cross join unnest(l.error_label_ids) as t(error_label_id)
