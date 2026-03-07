"""MLB-specific historical data aggregation.

Combines raw per-game stat records into averaged inputs suitable for
the MetricsEngine. Supports simple averaging, rate calculations, and
recency-weighted blending.

Stat keys align with the Statcast-derived fields stored by the scraper
(see ``scraper/sports_scraper/live/mlb_statcast.py``).
"""

from __future__ import annotations

from typing import Any

# Stat keys that are averaged across games (simple mean).
_MEAN_KEYS: list[str] = [
    "zone_swing_pct",
    "outside_swing_pct",
    "zone_contact_pct",
    "outside_contact_pct",
    "avg_exit_velocity",
    "hard_hit_pct",
    "barrel_pct",
]

# Stat keys that are summed for rate calculations.
_SUM_KEYS: list[str] = [
    "pitches",
    "balls_in_play",
    "contacts",
    "swings",
]


class MLBAggregation:
    """Aggregate MLB per-game stat records."""

    def aggregate_player_games(
        self,
        games: list[dict[str, Any]],
        *,
        recent_n: int | None = None,
        recent_weight: float = 0.7,
        season_weight: float = 0.3,
    ) -> dict[str, Any]:
        """Aggregate per-game player stats into a single stat dict.

        Args:
            games: List of per-game stat dicts. Each dict may contain
                any subset of the recognized stat keys.
            recent_n: If set, blend the most recent N games with
                the full season using the given weights.
            recent_weight: Weight applied to the recent window.
            season_weight: Weight applied to the full season.

        Returns:
            Dict of aggregated stat key -> value, ready for
            MetricsEngine consumption.
        """
        if not games:
            return {}

        season_avg = _compute_averages(games)

        if recent_n is not None and recent_n > 0 and len(games) > recent_n:
            recent_games = games[-recent_n:]
            recent_avg = _compute_averages(recent_games)
            return _weighted_blend(
                recent_avg, season_avg,
                recent_weight=recent_weight,
                season_weight=season_weight,
            )

        return season_avg

    def aggregate_team_games(
        self,
        games: list[dict[str, Any]],
        *,
        recent_n: int | None = None,
        recent_weight: float = 0.7,
        season_weight: float = 0.3,
    ) -> dict[str, Any]:
        """Aggregate per-game team stats.

        Uses the same logic as player aggregation since team-level
        Statcast data uses the same stat keys.

        Args:
            games: List of per-game team stat dicts.
            recent_n: If set, blend recent vs full season.
            recent_weight: Weight for the recent window.
            season_weight: Weight for the full season.

        Returns:
            Dict of aggregated stat key -> value.
        """
        return self.aggregate_player_games(
            games,
            recent_n=recent_n,
            recent_weight=recent_weight,
            season_weight=season_weight,
        )

    def build_matchup_history(
        self,
        entity_a_games: list[dict[str, Any]],
        entity_b_games: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Build aggregated profiles for matchup modeling.

        Args:
            entity_a_games: Game history for entity A (e.g., batter).
            entity_b_games: Game history for entity B (e.g., pitcher).

        Returns:
            Dict with ``entity_a`` and ``entity_b`` aggregated stats.
        """
        return {
            "entity_a": self.aggregate_player_games(entity_a_games),
            "entity_b": self.aggregate_player_games(entity_b_games),
        }


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------


def _compute_averages(games: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute simple averages for recognized stat keys across games.

    Ignores missing keys per-game (only averages over games that
    have the key). Returns an empty dict if no recognized keys
    are found.
    """
    if not games:
        return {}

    result: dict[str, Any] = {}

    for key in _MEAN_KEYS:
        values = _collect_floats(games, key)
        if values:
            result[key] = round(sum(values) / len(values), 4)

    # Rate calculations from summed counters
    for key in _SUM_KEYS:
        values = _collect_floats(games, key)
        if values:
            result[key] = round(sum(values), 4)

    # Derived rate: contact_rate from totals if available
    total_contacts = result.get("contacts")
    total_swings = result.get("swings")
    if total_contacts is not None and total_swings and total_swings > 0:
        result["rate_contact"] = round(total_contacts / total_swings, 4)

    return result


def _collect_floats(games: list[dict[str, Any]], key: str) -> list[float]:
    """Extract non-None float values for a key across games."""
    values: list[float] = []
    for g in games:
        val = g.get(key)
        if val is None:
            continue
        try:
            values.append(float(val))
        except (ValueError, TypeError):
            continue
    return values


def _weighted_blend(
    recent: dict[str, Any],
    season: dict[str, Any],
    *,
    recent_weight: float,
    season_weight: float,
) -> dict[str, Any]:
    """Blend two stat dicts using specified weights.

    For keys present in both dicts, produces a weighted average.
    Keys present in only one dict are passed through unchanged.
    """
    all_keys = set(recent) | set(season)
    result: dict[str, Any] = {}

    for key in all_keys:
        r_val = recent.get(key)
        s_val = season.get(key)

        if r_val is not None and s_val is not None:
            try:
                blended = float(r_val) * recent_weight + float(s_val) * season_weight
                result[key] = round(blended, 4)
            except (ValueError, TypeError):
                result[key] = r_val
        elif r_val is not None:
            result[key] = r_val
        else:
            result[key] = s_val

    return result


def rolling_average(values: list[float], window: int) -> list[float]:
    """Compute a rolling average over the last ``window`` values.

    Returns a list the same length as ``values``, with None-equivalent
    (NaN) for positions before the window is full.
    """
    if not values or window <= 0:
        return []

    result: list[float] = []
    for i in range(len(values)):
        start = max(0, i - window + 1)
        window_vals = values[start:i + 1]
        result.append(round(sum(window_vals) / len(window_vals), 4))
    return result


def weighted_average(
    values: list[float],
    weights: list[float] | None = None,
) -> float | None:
    """Compute a weighted average. If no weights, uses equal weighting."""
    if not values:
        return None
    if weights is None:
        return round(sum(values) / len(values), 4)
    if len(weights) != len(values):
        return round(sum(values) / len(values), 4)

    total_weight = sum(weights)
    if total_weight == 0:
        return None
    return round(sum(v * w for v, w in zip(values, weights)) / total_weight, 4)


def rate_calculation(numerator: float, denominator: float) -> float | None:
    """Safe rate calculation that avoids division by zero."""
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)
