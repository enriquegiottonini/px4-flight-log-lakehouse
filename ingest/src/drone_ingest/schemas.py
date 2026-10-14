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


def validate_records(records: list, entity: str = "logs_index") -> tuple[list[dict], list[Rejection]]:
    """Split a snapshot into valid records (first occurrence per log_id) and rejections."""
    valid: list[dict] = []
    rejected: list[Rejection] = []
    seen: set[str] = set()
    for rec in records:
        raw = json.dumps(rec, ensure_ascii=False, default=str)[:20_000]
        if not isinstance(rec, dict):
            rejected.append(Rejection(entity, None, "not_an_object", type(rec).__name__, raw))
            continue
        log_id = rec.get("log_id") if isinstance(rec.get("log_id"), str) else None
        try:
            IndexRecord.model_validate(rec)
        except ValidationError as e:
            reason, detail = _reason(e)
            rejected.append(Rejection(entity, log_id, reason, detail, raw))
            continue
        if rec["log_id"] in seen:
            rejected.append(Rejection(entity, log_id, "duplicate_log_id_in_snapshot", "kept the first one", raw))
            continue
        seen.add(rec["log_id"])
        valid.append(rec)
    return valid, rejected
