-- Within each vehicle class, the shares of time across modes must add up to 1.
-- (Caught an integer-division bug: every share was 0, which a 0..1 range test can't see.)
select vehicle_class, sum(share_of_class_time) as total_share
from {{ ref('mart_flight_mode_usage') }}
group by 1
having abs(sum(share_of_class_time) - 1) > 0.001
