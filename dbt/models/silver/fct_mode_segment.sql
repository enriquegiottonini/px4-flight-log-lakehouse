-- Time spent in each flight mode, with the attributes dashboards slice by.
select
    s.log_id,
    s.segment_seq,
    s.mode_id,
    m.mode_name,
    s.segment_s,
    l.uploaded_date,
    l.vehicle_class,
    l.is_simulation
from {{ ref('stg_log_mode_segments') }} s
join {{ ref('dim_flight_mode') }} m on s.mode_id = m.mode_id
join {{ ref('stg_logs') }} l on s.log_id = l.log_id
