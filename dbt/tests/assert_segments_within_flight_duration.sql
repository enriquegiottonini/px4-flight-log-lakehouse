-- Singular test: no mode segment may be longer than its flight (they're nulled in stg_log_mode_segments).
select s.log_id, s.segment_seq, s.segment_s, l.duration_s
from {{ ref('stg_log_mode_segments') }} s
join {{ ref('stg_logs') }} l on s.log_id = l.log_id
where s.segment_s > l.duration_s
