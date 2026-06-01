"""Small value helpers shared by feed sport adapters."""

from __future__ import annotations

from typing import Any


def normalize_type(value: str | None) -> str:
    return (value or "").strip().lower().replace("-", "_").replace(" ", "_")


def normalize_type_or_none(value: str | None) -> str | None:
    normalized = normalize_type(value)
    return normalized or None


def drop_empty(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: nested
        for key, nested in value.items()
        if nested is not None and nested != {} and nested != []
    }
