"""Coerce DB/JSON values into shapes expected by API response schemas."""
from __future__ import annotations

from typing import Any


def coerce_json_list(value: Any) -> list[Any]:
    """JSONB list columns sometimes come back as ``{}`` instead of ``[]``."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return []
    return [value]


def coerce_str_list(value: Any) -> list[str]:
    """Postgres ARRAY columns may deserialize as non-lists in edge cases."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, dict):
        return []
    return [str(value)]
