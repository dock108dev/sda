"""Shared metric helpers used across all sport modules.

Common utility functions for extracting, rounding, and filtering
metric values from raw stat dictionaries.
"""

from __future__ import annotations

from typing import Any


def metric_float(stats: dict[str, Any], key: str) -> float | None:
    """Extract a float value from stats, returning None if absent."""
    val = stats.get(key)
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def metric_float_or(
    stats: dict[str, Any], key: str, default: float,
) -> float:
    """Extract a float value from stats, returning *default* if absent."""
    val = metric_float(stats, key)
    return val if val is not None else default


def metric_round(val: float | None, decimals: int = 4) -> float | None:
    """Round a value, passing through None."""
    if val is None:
        return None
    return round(val, decimals)


def strip_none(d: dict[str, Any]) -> dict[str, Any]:
    """Remove keys with None values from a dict."""
    return {k: v for k, v in d.items() if v is not None}


def safe_mean(a: float | None, b: float | None) -> float | None:
    """Average two values, tolerating None on either side."""
    if a is not None and b is not None:
        return (a + b) / 2.0
    return a if a is not None else b
