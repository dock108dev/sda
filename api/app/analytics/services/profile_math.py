"""Shared profile aggregation math."""

from __future__ import annotations

from datetime import datetime

_PRIOR_SEASON_DECAY = 0.7


def _season_weights(game_dates: list[datetime]) -> list[float]:
    """Return per-game weights: 1.0 for current season, 0.7 for prior seasons."""
    if not game_dates:
        return []
    current_year = game_dates[0].year
    return [1.0 if d.year == current_year else _PRIOR_SEASON_DECAY for d in game_dates]


def _weighted_mean(values_weights: list[tuple[float, float]]) -> float:
    """Compute a weighted mean from (value, weight) pairs."""
    total_w = sum(w for _, w in values_weights)
    if total_w == 0:
        return 0.0
    return sum(v * w for v, w in values_weights) / total_w
