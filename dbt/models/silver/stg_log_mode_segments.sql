-- Flight-mode timeline of each log: one row per [mode_id, seconds] pair, in order.
-- Segments longer than the whole flight (wrapped-around counters) get a null duration.
select
    l.log_id,
    s.segment_seq,
    cast(element_at(s.pair, 1) as integer) as mode_id,
    case when element_at(s.pair, 2) between 0 and coalesce(l.duration_s, 86400)
         then element_at(s.pair, 2) end as segment_s
from {{ ref('stg_logs') }} l
cross join unnest(l.flight_mode_durations) with ordinality as s(pair, segment_seq)
