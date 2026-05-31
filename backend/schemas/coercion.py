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


def coerce_json_dict(value: Any) -> dict[str, Any]:
    """JSONB object columns must not be lists/strings."""
    if value is None or value == {}:
        return {}
    if isinstance(value, dict):
        return value
    return {}


def coerce_optional_json_dict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    return None


def coerce_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None
