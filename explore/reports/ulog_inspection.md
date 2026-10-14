# ULog inspection

Auto-picked: the smallest real (non-SITL, >= 30 s) log per vehicle class from the HEAD sample.

## `2cfe9a4c-fae0-4764-bc10-1688ed4607de`

- File: 0.81 MB, logged span 485 s
- sys_name: PX4, ver_hw: BEAGLEBOARD_POCKETBEAGLE2_A53_CPD, ver_sw_release: 17891328, time_ref_utc: 0
- Topics: 69, parameters: 805, logged messages: 0

### Wanted fields

| topic | instances | msgs | rate Hz | fields present | fields missing |
| --- | --- | --- | --- | --- | --- |
| `vehicle_global_position` | 1 | 202 | 5 | lat, lon, alt | – |
| `vehicle_local_position` | 1 | 402 | 10 | vx, vy, vz, z | – |
| `battery_status` | 0 | – | – | – | remaining, voltage_v, current_a |
| `vehicle_status` | 1 | 81 | 2 | nav_state, arming_state | – |
| `vehicle_air_data` | 1 | 201 | 5 | baro_alt_meter | – |

- Global position: lat 29.4053..29.4054, lon -95.0266..-95.0265, alt 8.9..11.4 m AMSL; zeros (lat=lon=0): 0
- Rows after 1 Hz downsampling: 42

- Logged message levels: {}

First logged messages:

```
```

<details><summary>All topics</summary>

| topic | multi_id | msgs | fields |
| --- | --- | --- | --- |
| action_request | 0 | 2 | 4 |
| actuator_armed | 0 | 80 | 8 |
| actuator_motors | 0 | 402 | 15 |
| actuator_outputs | 0 | 402 | 18 |
| config_overrides | 0 | 80 | 6 |
| control_allocator_status | 0 | 201 | 27 |
| cpuload | 0 | 81 | 3 |
| distance_sensor_mode_change_request | 0 | 1 | 2 |
| estimator_aid_src_baro_hgt | 0 | 82 | 14 |
| estimator_aid_src_gnss_hgt | 0 | 41 | 14 |
| estimator_aid_src_gnss_pos | 0 | 41 | 21 |
| estimator_aid_src_gnss_vel | 0 | 41 | 28 |
| estimator_aid_src_gravity | 0 | 81 | 28 |
| estimator_baro_bias | 0 | 82 | 8 |
| estimator_event_flags | 0 | 41 | 20 |
| estimator_gps_status | 0 | 41 | 17 |
| estimator_innovation_test_ratios | 0 | 82 | 33 |
| estimator_innovation_variances | 0 | 81 | 33 |
| estimator_innovations | 0 | 81 | 33 |
| estimator_sensor_bias | 0 | 42 | 32 |
| estimator_states | 0 | 81 | 52 |
| estimator_status | 0 | 201 | 40 |
| estimator_status_flags | 0 | 51 | 74 |
| event | 0 | 1 | 29 |
| failsafe_flags | 0 | 77 | 42 |
| failure_detector_status | 0 | 80 | 12 |
| home_position | 0 | 1 | 15 |
| hover_thrust_estimate | 0 | 402 | 9 |
| input_rc | 0 | 81 | 30 |
| manual_control_setpoint | 0 | 202 | 17 |
| manual_control_switches | 0 | 41 | 16 |
| mission_result | 0 | 1 | 15 |
| navigator_status | 0 | 80 | 3 |
| parameter_update | 0 | 1 | 9 |
| position_setpoint_triplet | 0 | 1 | 70 |
| rate_ctrl_status | 0 | 201 | 4 |
| rtl_status | 0 | 21 | 6 |
| rtl_time_estimate | 0 | 21 | 4 |
| sensor_accel | 0 | 41 | 12 |
| sensor_baro | 0 | 41 | 6 |
| sensor_combined | 0 | 803 | 14 |
| sensor_gps | 0 | 41 | 37 |
| sensor_gyro | 0 | 41 | 12 |
| sensor_selection | 0 | 1 | 3 |
| sensors_status_imu | 0 | 201 | 35 |
| takeoff_status | 0 | 6 | 3 |
| telemetry_status | 0 | 41 | 38 |
| trajectory_setpoint | 0 | 203 | 15 |
| transponder_report | 0 | 1 | 40 |
| vehicle_acceleration | 0 | 803 | 5 |
| vehicle_air_data | 0 | 201 | 9 |
| vehicle_angular_velocity | 0 | 803 | 8 |
| vehicle_attitude | 0 | 803 | 11 |
| vehicle_attitude_setpoint | 0 | 803 | 9 |
| vehicle_command | 0 | 1 | 15 |
| vehicle_constraints | 0 | 43 | 4 |
| vehicle_control_mode | 0 | 80 | 16 |
| vehicle_global_position | 0 | 202 | 18 |
| vehicle_gps_position | 0 | 41 | 37 |
| vehicle_imu | 0 | 81 | 16 |
| vehicle_imu_status | 0 | 42 | 32 |
| vehicle_land_detected | 0 | 44 | 13 |
| vehicle_local_position | 0 | 402 | 55 |
| vehicle_local_position_setpoint | 0 | 403 | 15 |
| vehicle_rates_setpoint | 0 | 803 | 8 |
| vehicle_status | 0 | 81 | 39 |
| vehicle_thrust_setpoint | 0 | 803 | 5 |
| vehicle_torque_setpoint | 0 | 803 | 5 |
| yaw_estimator_status | 0 | 41 | 25 |

</details>

## `786d35c7-8d81-4903-816e-491760285a0c`

- File: 1.78 MB, logged span 93 s
- sys_name: PX4, ver_hw: PX4_FMU_V5, ver_sw_release: 17564416, time_ref_utc: 0
- Topics: 49, parameters: 856, logged messages: 54

### Wanted fields

| topic | instances | msgs | rate Hz | fields present | fields missing |
| --- | --- | --- | --- | --- | --- |
| `vehicle_global_position` | 1 | 435 | 5 | lat, lon, alt | – |
| `vehicle_local_position` | 1 | 868 | 10 | vx, vy, vz, z | – |
| `battery_status` | 1 | 435 | 5 | remaining, voltage_v, current_a | – |
| `vehicle_status` | 1 | 185 | 2 | nav_state, arming_state | – |
| `vehicle_air_data` | 0 | – | – | – | baro_alt_meter |

- Global position: lat 21.3194..21.3249, lon -157.9239..-157.9224, alt 0.4..18.6 m AMSL; zeros (lat=lon=0): 0
- Rows after 1 Hz downsampling: 87
- Battery remaining: 0.00 -> 0.00 (range 0.00..0.00)

- Logged message levels: {'WARNING': 6, 'INFO': 48}

First logged messages:

```
   783.92s WARNING  [commander] Manual control lost
   783.95s INFO     [logger] [logger] /fs/microsd/log/2026-09-11/07_13_03.ulg
   783.95s INFO     [logger] Opened full log file: /fs/microsd/log/2026-09-11/07_13_03.ulg
   784.01s INFO     [commander] Manual control regained after 0.6s
   784.06s INFO     [fw_pos_control_l1] Takeoff on runway
   788.18s INFO     [commander] Takeoff detected
   794.26s INFO     [runway_takeoff] #Takeoff airspeed reached
   794.54s INFO     [runway_takeoff] #Climbout
```

<details><summary>All topics</summary>

| topic | multi_id | msgs | fields |
| --- | --- | --- | --- |
| actuator_armed | 0 | 185 | 9 |
| actuator_controls_0 | 0 | 1,734 | 10 |
| actuator_outputs | 0 | 874 | 18 |
| airspeed | 0 | 89 | 5 |
| airspeed_validated | 0 | 465 | 8 |
| airspeed_wind | 0 | 94 | 12 |
| airspeed_wind | 1 | 94 | 12 |
| battery_status | 0 | 435 | 48 |
| commander_state | 0 | 185 | 3 |
| cpuload | 0 | 186 | 3 |
| esc_status | 0 | 372 | 112 |
| home_position | 0 | 2 | 12 |
| logger_status | 0 | 93 | 10 |
| manual_control_setpoint | 0 | 464 | 14 |
| mission | 0 | 1 | 4 |
| mission_result | 0 | 3 | 15 |
| navigator_mission_item | 0 | 1 | 18 |
| parameter_update | 0 | 1 | 9 |
| position_controller_status | 0 | 176 | 11 |
| position_setpoint_triplet | 0 | 5 | 88 |
| px4io_status | 0 | 92 | 74 |
| rate_ctrl_status | 0 | 435 | 5 |
| rtl_flight_time | 0 | 92 | 3 |
| safety | 0 | 92 | 5 |
| sensor_accel | 0 | 94 | 12 |
| sensor_combined | 0 | 3,711 | 11 |
| sensor_gyro | 0 | 94 | 9 |
| sensor_selection | 0 | 1 | 3 |
| sensors_status_imu | 0 | 465 | 27 |
| tecs_status | 0 | 413 | 29 |
| telemetry_status | 0 | 94 | 36 |
| telemetry_status | 1 | 94 | 36 |
| telemetry_status | 2 | 94 | 36 |
| test_motor | 0 | 1 | 6 |
| vehicle_acceleration | 0 | 1,734 | 5 |
| vehicle_angular_acceleration | 0 | 4,332 | 5 |
| vehicle_angular_velocity | 0 | 4,332 | 5 |
| vehicle_attitude | 0 | 1,734 | 11 |
| vehicle_attitude_setpoint | 0 | 1,734 | 17 |
| vehicle_command | 0 | 10 | 15 |
| vehicle_control_mode | 0 | 185 | 15 |
| vehicle_global_position | 0 | 435 | 14 |
| vehicle_imu | 0 | 176 | 14 |
| vehicle_imu_status | 0 | 89 | 23 |
| vehicle_land_detected | 0 | 95 | 12 |
| vehicle_local_position | 0 | 868 | 46 |
| vehicle_rates_setpoint | 0 | 4,332 | 7 |
| vehicle_status | 0 | 185 | 32 |
| vehicle_status_flags | 0 | 185 | 34 |

</details>

## `14900471-eec2-4e0b-868d-365be641867a`

- File: 1.43 MB, logged span 37 s
- sys_name: PX4, ver_hw: PX4_FMU_V5, ver_sw_release: 17629952, time_ref_utc: 23220
- Topics: 103, parameters: 1102, logged messages: 7

### Wanted fields

| topic | instances | msgs | rate Hz | fields present | fields missing |
| --- | --- | --- | --- | --- | --- |
| `vehicle_global_position` | 1 | 186 | 5 | lat, lon, alt | – |
| `vehicle_local_position` | 1 | 370 | 10 | vx, vy, vz, z | – |
| `battery_status` | 1 | 186 | 5 | remaining, voltage_v, current_a | – |
| `vehicle_status` | 1 | 74 | 2 | nav_state, arming_state | – |
| `vehicle_air_data` | 1 | 186 | 5 | baro_alt_meter | – |

- Global position: lat 39.9593..39.9593, lon 116.3535..116.3535, alt 49.9..50.7 m AMSL; zeros (lat=lon=0): 0
- Rows after 1 Hz downsampling: 38
- Battery remaining: 1.00 -> 1.00 (range 1.00..1.00)

- Logged message levels: {'INFO': 7}

First logged messages:

```
   231.94s INFO     [logger] closed logfile, bytes written: 1384854
   257.65s INFO     [logger] Start file log (type: full)
   257.65s INFO     [logger] [logger] /fs/microsd/log/2026-01-27/13_04_29.ulg	
   257.65s INFO     [logger] Opened full log file: /fs/microsd/log/2026-01-27/13_04_29.ulg
   264.48s INFO     [commander] Armed by RC (switch)	
   270.88s INFO     [commander] Takeoff detected	
   280.60s INFO     [commander] Disarmed by RC (switch)	
```

<details><summary>All topics</summary>

| topic | multi_id | msgs | fields |
| --- | --- | --- | --- |
| action_request | 0 | 3 | 4 |
| actuator_armed | 0 | 74 | 9 |
| actuator_controls_0 | 0 | 738 | 10 |
| actuator_controls_1 | 0 | 370 | 10 |
| actuator_controls_3 | 0 | 188 | 10 |
| actuator_outputs | 0 | 370 | 18 |
| actuator_outputs | 1 | 370 | 18 |
| airspeed_validated | 0 | 186 | 8 |
| airspeed_wind | 0 | 36 | 14 |
| battery_status | 0 | 186 | 53 |
| commander_state | 0 | 74 | 3 |
| cpuload | 0 | 75 | 3 |
| estimator_attitude | 0 | 73 | 11 |
| estimator_attitude | 1 | 73 | 11 |
| estimator_attitude | 2 | 73 | 11 |
| estimator_baro_bias | 0 | 73 | 8 |
| estimator_baro_bias | 1 | 73 | 8 |
| estimator_baro_bias | 2 | 73 | 8 |
| estimator_event_flags | 0 | 38 | 29 |
| estimator_event_flags | 1 | 37 | 29 |
| estimator_event_flags | 2 | 38 | 29 |
| estimator_global_position | 0 | 36 | 14 |
| estimator_global_position | 1 | 36 | 14 |
| estimator_global_position | 2 | 36 | 14 |
| estimator_gps_status | 0 | 36 | 16 |
| estimator_gps_status | 1 | 36 | 16 |
| estimator_gps_status | 2 | 36 | 16 |
| estimator_innovation_test_ratios | 0 | 73 | 31 |
| estimator_innovation_test_ratios | 1 | 73 | 31 |
| estimator_innovation_test_ratios | 2 | 73 | 31 |
| estimator_innovation_variances | 0 | 73 | 31 |
| estimator_innovation_variances | 1 | 73 | 31 |
| estimator_innovation_variances | 2 | 73 | 31 |
| estimator_innovations | 0 | 73 | 31 |
| estimator_innovations | 1 | 73 | 31 |
| estimator_innovations | 2 | 73 | 31 |
| estimator_local_position | 0 | 73 | 47 |
| estimator_local_position | 1 | 73 | 47 |
| estimator_local_position | 2 | 73 | 47 |
| estimator_selector_status | 0 | 38 | 46 |
| estimator_sensor_bias | 0 | 67 | 32 |
| estimator_sensor_bias | 1 | 67 | 32 |
| estimator_sensor_bias | 2 | 97 | 32 |
| estimator_states | 0 | 36 | 51 |
| estimator_states | 1 | 36 | 51 |
| estimator_states | 2 | 36 | 51 |
| estimator_status | 0 | 186 | 36 |
| estimator_status | 1 | 186 | 36 |
| estimator_status | 2 | 186 | 36 |
| estimator_status_flags | 0 | 40 | 68 |
| estimator_status_flags | 1 | 40 | 68 |
| estimator_status_flags | 2 | 40 | 68 |
| event | 0 | 4 | 29 |
| failure_detector_status | 0 | 74 | 10 |
| home_position | 0 | 2 | 12 |
| input_rc | 0 | 73 | 28 |
| magnetometer_bias_estimate | 0 | 103 | 21 |
| manual_control_setpoint | 0 | 186 | 16 |
| manual_control_switches | 0 | 38 | 13 |
| px4io_status | 0 | 38 | 77 |
| rate_ctrl_status | 0 | 186 | 5 |
| rate_ctrl_status | 1 | 186 | 5 |
| rtl_time_estimate | 0 | 36 | 4 |
| safety | 0 | 38 | 3 |
| sensor_accel | 0 | 36 | 12 |
| sensor_accel | 1 | 36 | 12 |
| sensor_accel | 2 | 36 | 12 |
| sensor_baro | 0 | 36 | 6 |
| sensor_combined | 0 | 7,309 | 13 |
| sensor_gps | 0 | 36 | 29 |
| sensor_gyro | 0 | 37 | 9 |
| sensor_gyro | 1 | 37 | 9 |
| sensor_gyro | 2 | 37 | 9 |
| sensor_gyro_fft | 0 | 593 | 23 |
| sensor_mag | 0 | 37 | 8 |
| sensors_status_imu | 0 | 186 | 35 |
| system_power | 0 | 73 | 15 |
| takeoff_status | 0 | 2 | 3 |
| telemetry_status | 0 | 36 | 38 |
| vehicle_acceleration | 0 | 738 | 5 |
| vehicle_air_data | 0 | 186 | 8 |
| vehicle_angular_velocity | 0 | 1,842 | 5 |
| vehicle_attitude | 0 | 738 | 11 |
| vehicle_attitude_setpoint | 0 | 738 | 17 |
| vehicle_control_mode | 0 | 74 | 14 |
| vehicle_global_position | 0 | 186 | 14 |
| vehicle_gps_position | 0 | 73 | 27 |
| vehicle_imu | 0 | 74 | 15 |
| vehicle_imu | 1 | 74 | 15 |
| vehicle_imu | 2 | 74 | 15 |
| vehicle_imu_status | 0 | 37 | 29 |
| vehicle_imu_status | 1 | 37 | 29 |
| vehicle_imu_status | 2 | 37 | 29 |
| vehicle_land_detected | 0 | 44 | 12 |
| vehicle_local_position | 0 | 370 | 47 |
| vehicle_magnetometer | 0 | 73 | 7 |
| vehicle_rates_setpoint | 0 | 590 | 7 |
| vehicle_status | 0 | 74 | 31 |
| vehicle_status_flags | 0 | 74 | 40 |
| vtol_vehicle_status | 0 | 186 | 6 |
| yaw_estimator_status | 0 | 13 | 24 |
| yaw_estimator_status | 1 | 13 | 24 |
| yaw_estimator_status | 2 | 13 | 24 |

</details>
