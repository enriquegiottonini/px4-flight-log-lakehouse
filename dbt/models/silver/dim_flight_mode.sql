-- Known modes from the seed, plus ids seen in the data that PX4's table doesn't list.
with used as (select distinct mode_id from {{ ref('stg_log_mode_segments') }})
select
    coalesce(s.mode_id, u.mode_id) as mode_id,
    coalesce(s.mode_name, 'Unknown (' || cast(u.mode_id as varchar) || ')') as mode_name,
    s.mode_id is not null as is_known
from {{ ref('flight_modes') }} s
full outer join used u on s.mode_id = u.mode_id
