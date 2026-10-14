"""Build deterministic test fixtures for the drone_ingest package (Phase 4).

Output in ingest/tests/fixtures/:
- dbinfo_sample.json            200 real index records, stratified to include every known defect
- dbinfo_sample_next_day.json   the same snapshot one "day" later: +5 new logs, 1 edited rating
- dbinfo_corrupt.json           records that must land in bronze.rejected_records
- dbinfo_truncated.json.gz      a cut-off gzip (whole snapshot must fail validation)
- ulog/<log_id>.ulg             3 small real ULogs, whose index rows are in dbinfo_sample.json
- ulog/truncated.ulg            first 100 KB of a real ULog
- ulog/not_a_ulog.ulg           an HTML error page saved with a .ulg name
- expected.json                 counts the Phase 4 tests assert against

    uv run python make_fixtures.py
"""

import copy
import gzip
import json
import random
import shutil
from pathlib import Path

from lookups import FLIGHT_MODES

HERE = Path(__file__).parent
INDEX_FILE = HERE / "data" / "dbinfo.json.gz"
ULOG_DIR = HERE / "data" / "ulogs"
OUT = HERE.parent / "ingest" / "tests" / "fixtures"
SEED = 42
SAMPLE_SIZE = 200
RATING_JUNK = {"BRAVO!", "BRAWO!", "1", "none"}

# defect name -> (predicate, how many records to force into the sample)
STRATA = {
    "airframe_type_int": (lambda r: isinstance(r["airframe_type"], int), 15),
    "wind_speed_sentinel": (lambda r: r["wind_speed"] == -1, 10),
    "wind_speed_real": (lambda r: r["wind_speed"] >= 0, 10),
    "rating_junk": (lambda r: r["rating"] in RATING_JUNK, 6),
    "rating_crash": (lambda r: r["rating"] in {"crash_sw_hw", "crash_pilot"}, 6),
    "rating_good_great": (lambda r: r["rating"] in {"good", "great", "unsatisfactory"}, 6),
    "error_labels": (lambda r: bool(r["error_labels"]), 10),
    "vehicle_uuid_empty": (lambda r: r["vehicle_uuid"] == "", 10),
    "flight_modes_empty": (lambda r: not r["flight_modes"], 5),
    "flight_mode_unknown_id": (lambda r: any(m not in FLIGHT_MODES for m in r["flight_modes"]), 5),
    "duration_overflow": (lambda r: r["duration_s"] > 86400, 3),
    "duration_zero": (lambda r: r["duration_s"] == 0, 5),
    "mode_segment_overflow": (lambda r: any(s > 86400 for _, s in r["flight_mode_durations"]), 3),
    "sitl": (lambda r: "SITL" in r["sys_hw"].upper(), 10),
    "ver_sw_release_empty": (lambda r: r["ver_sw_release"] == "", 3),
    "estimator_unknown": (lambda r: r["estimator"].startswith("unknown"), 2),
    "mav_type_fixed_wing": (lambda r: r["mav_type"] == "Fixed Wing", 8),
    "mav_type_vtol": (lambda r: "VTOL" in r["mav_type"], 8),
    "mav_type_other": (lambda r: r["mav_type"] in {"Ground Rover", "unknown type", "Rocket", "Submarine"}, 5),
}


def build_sample(records: list[dict], rng: random.Random, must_have: set[str]) -> list[dict]:
    chosen: dict[str, dict] = {r["log_id"]: r for r in records if r["log_id"] in must_have}
    for name, (pred, k) in STRATA.items():
        pool = [r for r in records if pred(r) and r["log_id"] not in chosen]
        already = sum(1 for r in chosen.values() if pred(r))
        for r in rng.sample(pool, max(0, min(k - already, len(pool)))):
            chosen[r["log_id"]] = r
    recent = [r for r in records if r["log_date"] >= "2026-10-01" and r["log_id"] not in chosen]
    for r in rng.sample(recent, SAMPLE_SIZE - len(chosen)):
        chosen[r["log_id"]] = r
    return sorted(chosen.values(), key=lambda r: r["log_id"])


def corrupt_records(base: dict) -> list[dict]:
    """One bad record per rejection reason; `_expect_reason` documents the expected outcome."""
    def variant(reason: str, **changes) -> dict:
        r = copy.deepcopy(base)
        r["log_id"] = f"00000000-0000-4000-8000-{len(out):012d}"
        r.update(changes)
        r["_expect_reason"] = reason
        return r

    out: list[dict] = [copy.deepcopy(base)]  # valid control record: the only one that loads
    out.append(variant("missing_log_id"))
    del out[-1]["log_id"]
    out.append(variant("invalid_log_id", log_id="not-a-uuid"))
    out.append(variant("invalid_log_date", log_date="2026-13-45"))
    out.append(variant("missing_log_date"))
    del out[-1]["log_date"]
    out.append(variant("invalid_type_duration_s", duration_s="81"))
    out.append(variant("invalid_flight_mode_durations", flight_mode_durations=[[2], [3, "x"]]))
    out.append(variant("not_an_object"))
    out[-1] = ["this", "is", "not", "a", "record"]
    out.append(variant("duplicate_log_id_in_snapshot", log_id=base["log_id"]))
    return out


def main() -> None:
    rng = random.Random(SEED)
    records = json.load(gzip.open(INDEX_FILE))
    by_id = {r["log_id"]: r for r in records}
    ulogs = sorted(ULOG_DIR.glob("*.ulg"))
    assert len(ulogs) == 3, "run inspect_ulog.py first (expects 3 ULogs in data/ulogs/)"
    ulog_ids = {p.stem for p in ulogs}

    # Regenerate everything except the hand-written README.md
    if (OUT / "ulog").exists():
        shutil.rmtree(OUT / "ulog")
    for f in OUT.glob("*.json*"):
        f.unlink()
    (OUT / "ulog").mkdir(parents=True)

    # --- index snapshots ------------------------------------------------------
    sample = build_sample(records, rng, ulog_ids)
    sample_ids = {r["log_id"] for r in sample}
    (OUT / "dbinfo_sample.json").write_text(json.dumps(sample, indent=1))

    new = rng.sample([r for r in records if r["log_date"] >= "2026-10-01" and r["log_id"] not in sample_ids], 5)
    edited_target = next(r for r in sample if r["rating"] == "" and r["log_id"] not in ulog_ids)
    next_day = []
    for r in sample:
        r = copy.deepcopy(r)
        if r["log_id"] == edited_target["log_id"]:
            r["rating"] = "good"
        next_day.append(r)
    next_day = sorted(next_day + new, key=lambda r: r["log_id"])
    (OUT / "dbinfo_sample_next_day.json").write_text(json.dumps(next_day, indent=1))

    corrupt = corrupt_records(sample[0])
    (OUT / "dbinfo_corrupt.json").write_text(json.dumps(corrupt, indent=1))

    full = gzip.compress(json.dumps(sample).encode())
    (OUT / "dbinfo_truncated.json.gz").write_bytes(full[: len(full) // 2])

    # --- ULogs ----------------------------------------------------------------
    for p in ulogs:
        shutil.copy(p, OUT / "ulog" / p.name)
    smallest = min(ulogs, key=lambda p: p.stat().st_size)
    (OUT / "ulog" / "truncated.ulg").write_bytes(smallest.read_bytes()[:100_000])
    (OUT / "ulog" / "not_a_ulog.ulg").write_text(
        "<html><head><title>503 Service Temporarily Unavailable</title></head></html>\n")

    # --- expectations ---------------------------------------------------------
    expected = {
        "seed": SEED,
        "dbinfo_sample": {
            "records": len(sample),
            "defect_counts": {name: sum(1 for r in sample if pred(r)) for name, (pred, _) in STRATA.items()},
        },
        "dbinfo_sample_next_day": {
            "records": len(next_day),
            "diff_vs_sample": {"insert": sorted(r["log_id"] for r in new),
                               "update": [edited_target["log_id"]],
                               "unchanged": len(sample) - 1},
        },
        "dbinfo_corrupt": {"records": len(corrupt), "loaded": [corrupt[0]["log_id"]],
                           "rejected_reasons": [r["_expect_reason"] if isinstance(r, dict) else "not_an_object"
                                                for r in corrupt[1:]]},
        "dbinfo_truncated": {"must_fail": True},
        "ulog": {
            p.name: {"index_row_in_sample": p.stem in sample_ids, "mav_type": by_id[p.stem]["mav_type"],
                     "bytes": p.stat().st_size}
            for p in ulogs
        } | {
            # pyulog parses a cut-off file without error (file_corruption=False), so truncation can only be
            # caught by comparing the file size with the Content-Length recorded at download time.
            "truncated.ulg": {"must_reject": True, "reason": "size_mismatch",
                              "expected_bytes": smallest.stat().st_size, "actual_bytes": 100_000},
            "not_a_ulog.ulg": {"must_reject": True, "reason": "invalid_ulog_header"},
        },
    }
    (OUT / "expected.json").write_text(json.dumps(expected, indent=1))

    total = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    print(json.dumps(expected["dbinfo_sample"]["defect_counts"], indent=1))
    print(f"wrote {sum(1 for f in OUT.rglob('*') if f.is_file())} files, {total / 1e6:.1f} MB -> {OUT}")


if __name__ == "__main__":
    main()
