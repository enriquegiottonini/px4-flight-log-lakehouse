"""ULog parsing, integrity checks and the disk guard (D-004). Uses the 3 real fixture logs."""

from datetime import date

import pytest

from drone_ingest.ulog import (TELEMETRY_COLUMNS, DiskGuardError, check_disk, classify_parse_error, parse_ulog,
                               size_ok)

QUAD = "2cfe9a4c-fae0-4764-bc10-1688ed4607de"      # no battery_status
FIXED_WING = "786d35c7-8d81-4903-816e-491760285a0c"  # battery stuck at 0, no GPS topic
VTOL = "14900471-eec2-4e0b-868d-365be641867a"       # GPS UTC available, flew 2026-01-27


@pytest.fixture(scope="module")
def parsed(fixtures):
    return {name: parse_ulog(fixtures / "ulog" / f"{name}.ulg") for name in (QUAD, FIXED_WING, VTOL)}


@pytest.mark.parametrize("name", [QUAD, FIXED_WING, VTOL])
def test_telemetry_is_one_row_per_second(parsed, name):
    telemetry, _ = parsed[name]
    assert list(telemetry.columns) == TELEMETRY_COLUMNS
    assert len(telemetry) > 20
    assert telemetry["t_boot_s"].is_unique and telemetry["t_boot_s"].is_monotonic_increasing


def test_missing_topic_becomes_null_column(parsed):
    telemetry, _ = parsed[QUAD]
    assert telemetry["battery_remaining"].isna().all()
    assert telemetry["lat"].notna().any()


def test_raw_battery_kept_even_when_stuck_at_zero(parsed):
    telemetry, _ = parsed[FIXED_WING]
    assert (telemetry["battery_remaining"].dropna() == 0).all()  # bronze keeps it; silver nulls it


def test_utc_time_from_gps(parsed):
    telemetry, messages = parsed[VTOL]
    assert telemetry["ts_utc"].notna().all()
    assert telemetry["ts_utc"].dt.date.iloc[0] == date(2026, 1, 27)
    assert messages["ts_utc"].notna().all()


def test_no_gps_means_no_utc(parsed):
    telemetry, _ = parsed[FIXED_WING]
    assert telemetry["ts_utc"].isna().all()


def test_logged_messages(parsed):
    _, messages = parsed[FIXED_WING]
    assert len(messages) == 54
    assert set(messages["level"]) == {"WARNING", "INFO"}
    assert not messages["message"].str.endswith(("\t", " ")).any()  # trailing tabs stripped


def test_not_a_ulog_is_classified(fixtures):
    with pytest.raises(Exception) as exc:
        parse_ulog(fixtures / "ulog" / "not_a_ulog.ulg")
    assert classify_parse_error(exc.value) == "invalid_ulog_header"


def test_truncated_file_parses_but_fails_the_size_check(fixtures, expected):
    path = fixtures / "ulog" / "truncated.ulg"
    meta = expected["ulog"]["truncated.ulg"]
    parse_ulog(path)  # no error: this is why the size check exists
    assert not size_ok(path, meta["expected_bytes"])
    assert size_ok(fixtures / "ulog" / f"{QUAD}.ulg", meta["expected_bytes"])


def test_disk_guard():
    check_disk(free_bytes=10 * 10**9, needed_bytes=2 * 10**9, min_free_gb=3)  # leaves 8 GB: fine
    with pytest.raises(DiskGuardError):
        check_disk(free_bytes=4 * 10**9, needed_bytes=2 * 10**9, min_free_gb=3)  # would leave 2 GB
