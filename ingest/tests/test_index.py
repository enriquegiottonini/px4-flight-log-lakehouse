"""Index snapshot: validation, file integrity and the daily diff (D-003). No network, no services."""

import gzip
import json
from datetime import date

import pytest

from drone_ingest.index import IndexFileError, canonical_json, diff_records, read_index_file
from drone_ingest.schemas import validate_records

ALL_DATES = date(2000, 1, 1)  # fixtures include logs back to 2017


def test_sample_records_are_all_valid(load_json, expected):
    valid, rejected = validate_records(load_json("dbinfo_sample.json"))
    assert len(valid) == expected["dbinfo_sample"]["records"]
    assert rejected == []


def test_corrupt_records_are_rejected_with_reasons(load_json, expected):
    valid, rejected = validate_records(load_json("dbinfo_corrupt.json"))
    assert [r["log_id"] for r in valid] == expected["dbinfo_corrupt"]["loaded"]
    assert [r.reason for r in rejected] == expected["dbinfo_corrupt"]["rejected_reasons"]


def test_truncated_gzip_fails_the_whole_snapshot(fixtures):
    with pytest.raises(IndexFileError):
        read_index_file(fixtures / "dbinfo_truncated.json.gz")


def test_complete_gzip_roundtrip(tmp_path, load_json):
    path = tmp_path / "dbinfo.json.gz"
    path.write_bytes(gzip.compress(json.dumps(load_json("dbinfo_sample.json")).encode()))
    assert len(read_index_file(path)) == 200


def test_canonical_json_ignores_key_order():
    assert canonical_json({"b": 1, "a": [2, 3]}) == canonical_json({"a": [2, 3], "b": 1})


def _bronze_after(rows):
    """Latest hash per log_id, as bronze would hold it after appending `rows`."""
    return {r["log_id"]: r["payload_hash"] for r in rows}


def test_first_load_inserts_everything(load_json):
    valid, _ = validate_records(load_json("dbinfo_sample.json"))
    diff = diff_records(valid, {}, ALL_DATES)
    assert (len(diff.inserts), len(diff.updates), diff.unchanged) == (200, 0, 0)
    assert {r["_change_type"] for r in diff.inserts} == {"insert"}


def test_same_snapshot_twice_inserts_nothing(load_json):
    valid, _ = validate_records(load_json("dbinfo_sample.json"))
    bronze = _bronze_after(diff_records(valid, {}, ALL_DATES).inserts)
    again = diff_records(valid, bronze, ALL_DATES)
    assert (len(again.inserts), len(again.updates), again.unchanged) == (0, 0, 200)


def test_next_day_has_new_logs_and_one_edited_rating(load_json, expected):
    day1, _ = validate_records(load_json("dbinfo_sample.json"))
    day2, _ = validate_records(load_json("dbinfo_sample_next_day.json"))
    bronze = _bronze_after(diff_records(day1, {}, ALL_DATES).inserts)
    diff = diff_records(day2, bronze, ALL_DATES)
    want = expected["dbinfo_sample_next_day"]["diff_vs_sample"]
    assert sorted(r["log_id"] for r in diff.inserts) == want["insert"]
    assert [r["log_id"] for r in diff.updates] == want["update"]
    assert diff.unchanged == want["unchanged"]
    assert diff.updates[0]["_change_type"] == "update"
    assert json.loads(diff.updates[0]["payload"])["rating"] == "good"


def test_records_before_start_date_are_ignored(load_json):
    valid, _ = validate_records(load_json("dbinfo_sample.json"))
    cutoff = date(2026, 1, 1)
    diff = diff_records(valid, {}, cutoff)
    assert diff.out_of_window == sum(1 for r in valid if r["log_date"] < cutoff.isoformat())
    assert all(r["log_date"] >= cutoff for r in diff.inserts)
