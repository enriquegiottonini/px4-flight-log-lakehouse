"""Contract for PX4 index records: only the fields the pipeline relies on are validated.

Everything else is kept as-is in the raw payload; silver does the cleaning (CLAUDE.md 3.3).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StrictInt, ValidationError


class IndexRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    log_id: UUID
    log_date: date
    duration_s: StrictInt  # may be a wrapped-around uint64; still an int, silver nulls it
    flight_mode_durations: list[tuple[StrictInt, StrictInt]]


@dataclass
class Rejection:
    entity: str
    log_id: str | None
    reason: str
    detail: str
    raw: str


def _reason(err: ValidationError) -> tuple[str, str]:
    first = err.errors()[0]
    field = str(first["loc"][0]) if first["loc"] else "record"
    # "missing" only if the field itself is absent; a missing item inside a list is "invalid"
    kind = "missing" if first["type"] == "missing" and len(first["loc"]) == 1 else "invalid"
    return f"{kind}_{field}", first["msg"]


def validate_record(rec, seen: set[str], entity: str = "logs_index") -> Rejection | None:
    """Check one record; `seen` tracks log_ids already accepted in this snapshot."""
    if not isinstance(rec, dict):
        return Rejection(entity, None, "not_an_object", type(rec).__name__, _raw(rec))
    log_id = rec.get("log_id") if isinstance(rec.get("log_id"), str) else None
    try:
        IndexRecord.model_validate(rec)
    except ValidationError as e:
        reason, detail = _reason(e)
        return Rejection(entity, log_id, reason, detail, _raw(rec))
    if rec["log_id"] in seen:
        return Rejection(entity, log_id, "duplicate_log_id_in_snapshot", "kept the first one", _raw(rec))
    seen.add(rec["log_id"])
    return None


def _raw(rec) -> str:
    return json.dumps(rec, ensure_ascii=False, default=str)[:20_000]


def validate_records(records, entity: str = "logs_index") -> tuple[list[dict], list[Rejection]]:
    """Split records into valid ones (first occurrence per log_id) and rejections."""
    valid: list[dict] = []
    rejected: list[Rejection] = []
    seen: set[str] = set()
    for rec in records:
        if (rejection := validate_record(rec, seen, entity)) is None:
            valid.append(rec)
        else:
            rejected.append(rejection)
    return valid, rejected
