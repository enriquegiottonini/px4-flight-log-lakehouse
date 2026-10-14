"""Lookup tables copied from PX4 flight_review app/plot_app/config_tables.py.

These become dbt seeds in Phase 6 (dbt/seeds/*.csv).
"""

FLIGHT_MODES = {
    0: "Manual", 1: "Altitude", 2: "Position", 3: "Mission", 4: "Loiter",
    5: "Return to Land", 6: "Position (Slow)", 8: "Altitude Cruise", 10: "Acro",
    12: "Descend", 13: "Terminate", 14: "Offboard", 15: "Stabilized", 17: "Takeoff",
    18: "Land", 19: "Follow Target", 20: "Precision Land", 21: "Orbit", 22: "VTOL Takeoff",
    23: "External 1", 24: "External 2", 25: "External 3", 26: "External 4",
    27: "External 5", 28: "External 6", 29: "External 7", 30: "External 8",
}

ERROR_LABELS = {
    1: "Other", 2: "Vibration", 3: "Airframe-design", 4: "Sensor-error",
    5: "Component-failure", 6: "Software", 7: "Human-error", 8: "External-conditions",
}

VTOL_MODES = {1: "Transition", 2: "Fixed-Wing", 3: "Multicopter"}
