"""Normalize visit ORM columns before API serialization (Postgres JSONB/ARRAY quirks)."""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from schemas.coercion import (
    coerce_json_dict,
    coerce_json_list,
    coerce_optional_json_dict,
    coerce_str_list,
)

if TYPE_CHECKING:
    from models.visit import Visit


def normalize_visit(visit: Visit) -> None:
    """Mutate visit in place so VisitRead validation always succeeds."""
    visit.soap_note = coerce_json_dict(visit.soap_note)
    visit.soap_audit_trail = coerce_json_dict(visit.soap_audit_trail)
    visit.anomalies = coerce_json_list(visit.anomalies)
    visit.differentials = coerce_json_list(visit.differentials)
    visit.compliance_notes = coerce_json_list(visit.compliance_notes)
    visit.bias_flags = coerce_json_list(visit.bias_flags)
    visit.trajectory_watch_zones = coerce_str_list(visit.trajectory_watch_zones)
    visit.drift_flag = coerce_optional_json_dict(visit.drift_flag)

    score = visit.trajectory_score
    if score is not None and isinstance(score, float) and (
        math.isnan(score) or math.isinf(score)
    ):
        visit.trajectory_score = None
