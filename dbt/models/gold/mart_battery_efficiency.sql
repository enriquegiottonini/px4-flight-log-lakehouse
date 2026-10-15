-- Battery drain per minute and per km, by vehicle class and flight-duration band.
select
    vehicle_class,
    duration_band,
    duration_band_order,
    count(*) as flights,
    cast(avg(battery_pct_per_min) as double) as avg_battery_pct_per_min,
    cast(avg(battery_pct_per_km) as double) as avg_battery_pct_per_km
from {{ ref('fct_flight') }}
where battery_pct_per_min is not null and duration_band is not null and {{ real_flights() }}
group by 1, 2, 3
