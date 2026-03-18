"""MLB-specific metric calculations.

Computes derived batting, pitching, and fielding metrics from raw
box score and Statcast data. Intended to work with data already
ingested into ``mlb_game_advanced_stats`` and ``mlb_player_advanced_stats``.

Input stat keys align with the Statcast-derived fields stored by the
scraper (see ``scraper/sports_scraper/live/mlb_statcast.py``):
- ``zone_swing_pct`` / ``outside_swing_pct`` — plate discipline
- ``zone_contact_pct`` / ``outside_contact_pct`` — contact ability
- ``avg_exit_velocity`` — quality of contact (mph)
- ``hard_hit_pct`` — fraction of batted balls >= 95 mph
- ``barrel_pct`` — fraction meeting MLB barrel criteria
"""

from __future__ import annotations

from typing import Any

from app.analytics.core.types import PlayerProfile, TeamProfile
from app.analytics.sports.mlb.constants import (
    BASELINE_AVG_EXIT_VELOCITY as _BASELINE_AVG_EV,
)
from app.analytics.sports.mlb.constants import (
    BASELINE_BARREL_RATE as _BASELINE_BARREL,
)
from app.analytics.sports.mlb.constants import (
    BASELINE_CONTACT_RATE as _BASELINE_CONTACT_RATE,
)
from app.analytics.sports.mlb.constants import (
    BASELINE_HARD_HIT_RATE as _BASELINE_HARD_HIT,
)
from app.analytics.sports.mlb.constants import (
    BASELINE_POWER_INDEX as _BASELINE_POWER_INDEX,
)
from app.analytics.sports.mlb.constants import (
    BASELINE_SWING_RATE as _BASELINE_SWING_RATE,
)


class MLBMetrics:
    """Compute MLB-specific analytical metrics from raw stats."""

    # ------------------------------------------------------------------
    # Player metrics
    # ------------------------------------------------------------------

    def build_player_metrics(self, stats: dict[str, Any]) -> dict[str, float]:
        """Derive analytical batting metrics from raw Statcast-style stats.

        Args:
            stats: Dict with keys such as ``zone_swing_pct``,
                ``outside_swing_pct``, ``zone_contact_pct``,
                ``outside_contact_pct``, ``avg_exit_velocity``,
                ``hard_hit_pct``, ``barrel_pct``.

        Returns:
            Dict of derived metric name -> value.
        """
        z_swing = _float(stats, "zone_swing_pct")
        o_swing = _float(stats, "outside_swing_pct")
        z_contact = _float(stats, "zone_contact_pct")
        o_contact = _float(stats, "outside_contact_pct")
        avg_ev = _float(stats, "avg_exit_velocity")
        hard_hit = _float(stats, "hard_hit_pct")
        barrel = _float(stats, "barrel_pct")

        swing_rate = _safe_mean(z_swing, o_swing)
        contact_rate = _safe_mean(z_contact, o_contact)
        whiff_rate = (1.0 - contact_rate) if contact_rate is not None else None

        power_index = _compute_power_index(avg_ev, hard_hit)
        expected_slug = _compute_expected_slug(power_index, contact_rate)

        return _strip_none({
            "swing_rate": _round(swing_rate),
            "contact_rate": _round(contact_rate),
            "whiff_rate": _round(whiff_rate),
            "power_index": _round(power_index),
            "barrel_rate": _round(barrel),
            "hard_hit_rate": _round(hard_hit),
            "avg_exit_velocity": _round(avg_ev),
            "expected_slug": _round(expected_slug),
        })

    def build_player_profile(self, stats: dict[str, Any]) -> PlayerProfile:
        """Build a full PlayerProfile with computed metrics.

        Args:
            stats: Raw stat dictionary. Must include ``player_id``.

        Returns:
            PlayerProfile populated with derived metrics.
        """
        metrics = self.build_player_metrics(stats)
        return PlayerProfile(
            player_id=str(stats.get("player_id", "")),
            sport="mlb",
            name=str(stats.get("name", "")),
            team_id=stats.get("team_id"),
            metrics=metrics,
        )

    # ------------------------------------------------------------------
    # Team metrics
    # ------------------------------------------------------------------

    def build_team_metrics(self, stats: dict[str, Any]) -> dict[str, float]:
        """Derive team-level metrics from aggregated or per-player stats.

        Accepts either pre-aggregated team stats (same keys as player
        stats) or a ``players`` list of individual player stat dicts
        that will be averaged.

        Args:
            stats: Team stat dict. May contain a ``players`` key with
                a list of per-player stat dicts.

        Returns:
            Dict of team metric name -> value.
        """
        players: list[dict[str, Any]] = stats.get("players", [])

        if players:
            return self._aggregate_player_metrics(players)

        # Treat as pre-aggregated team-level stats
        raw = self.build_player_metrics(stats)
        return {f"team_{k}": v for k, v in raw.items()}

    def build_team_profile(self, stats: dict[str, Any]) -> TeamProfile:
        """Build a full TeamProfile with computed metrics.

        Args:
            stats: Team stat dictionary. Must include ``team_id``.

        Returns:
            TeamProfile populated with derived team metrics.
        """
        metrics = self.build_team_metrics(stats)
        return TeamProfile(
            team_id=str(stats.get("team_id", "")),
            sport="mlb",
            name=str(stats.get("name", "")),
            metrics=metrics,
        )

    # ------------------------------------------------------------------
    # Matchup metrics
    # ------------------------------------------------------------------

    def build_matchup_metrics(
        self,
        entity_a: dict[str, Any],
        entity_b: dict[str, Any],
    ) -> dict[str, float]:
        """Estimate matchup probabilities between a batter and pitcher.

        Uses batter metrics (contact rate, power index) and pitcher
        suppression factors. Falls back to league baselines when
        pitcher data is unavailable.

        Args:
            entity_a: Batter stats or pre-computed metrics.
            entity_b: Pitcher stats or pre-computed metrics.

        Returns:
            Dict of probability metric name -> value (0-1 range).
        """
        batter = self.build_player_metrics(entity_a) if entity_a else {}
        pitcher = self.build_player_metrics(entity_b) if entity_b else {}

        b_contact = batter.get("contact_rate", _BASELINE_CONTACT_RATE)
        b_power = batter.get("power_index", _BASELINE_POWER_INDEX)
        b_barrel = batter.get("barrel_rate", _BASELINE_BARREL)

        # Pitcher suppression: ratio of pitcher's contact rate to baseline.
        # < 1.0 means the pitcher suppresses contact.
        p_contact = pitcher.get("contact_rate", _BASELINE_CONTACT_RATE)
        contact_suppression = p_contact / _BASELINE_CONTACT_RATE if _BASELINE_CONTACT_RATE else 1.0

        contact_prob = min(b_contact * contact_suppression, 1.0)
        barrel_prob = min(b_barrel * (b_power / _BASELINE_POWER_INDEX), 1.0)

        # Simplified hit probability based on contact and power
        hit_prob = min(contact_prob * 0.35 + barrel_prob * 0.30, 1.0)

        # Walk and strikeout estimates from swing/contact tendencies
        b_whiff = batter.get("whiff_rate", 1.0 - _BASELINE_CONTACT_RATE)
        strikeout_prob = min(b_whiff * 0.60, 1.0)
        swing = batter.get("swing_rate", _BASELINE_SWING_RATE)
        walk_prob = max(0.0, min((1.0 - swing) * 0.25, 1.0))

        return {
            "contact_probability": _round(contact_prob),
            "barrel_probability": _round(barrel_prob),
            "hit_probability": _round(hit_prob),
            "strikeout_probability": _round(strikeout_prob),
            "walk_or_hbp_probability": _round(walk_prob),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _aggregate_player_metrics(
        self,
        players: list[dict[str, Any]],
    ) -> dict[str, float]:
        """Average per-player metrics into team-level metrics."""
        if not players:
            return {}

        all_metrics = [self.build_player_metrics(p) for p in players]
        keys = set()
        for m in all_metrics:
            keys.update(m.keys())

        team: dict[str, float] = {}
        for key in sorted(keys):
            vals = [m[key] for m in all_metrics if key in m]
            if vals:
                team[f"team_{key}"] = _round(sum(vals) / len(vals))
        return team


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _float(stats: dict[str, Any], key: str) -> float | None:
    """Extract a float value from stats, returning None if absent."""
    val = stats.get(key)
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _safe_mean(a: float | None, b: float | None) -> float | None:
    """Average two values, tolerating None on either side."""
    if a is not None and b is not None:
        return (a + b) / 2.0
    return a if a is not None else b


def _compute_power_index(
    avg_ev: float | None,
    hard_hit: float | None,
) -> float | None:
    """Compute power index from exit velocity and hard-hit rate.

    Formula: (avg_ev / 88) * (hard_hit / 0.35)
    Both factors are normalized to league-average baselines.
    """
    if avg_ev is None and hard_hit is None:
        return None

    ev_factor = (avg_ev / _BASELINE_AVG_EV) if avg_ev is not None else 1.0
    hh_factor = (hard_hit / _BASELINE_HARD_HIT) if hard_hit is not None else 1.0
    return ev_factor * hh_factor


def _compute_expected_slug(
    power_index: float | None,
    contact_rate: float | None,
) -> float | None:
    """Compute expected slugging from power index and contact rate.

    Formula: power_index * contact_rate
    """
    if power_index is None or contact_rate is None:
        return None
    return power_index * contact_rate


def _round(val: float | None, decimals: int = 4) -> float | None:
    """Round a value, passing through None."""
    if val is None:
        return None
    return round(val, decimals)


def _strip_none(d: dict[str, Any]) -> dict[str, Any]:
    """Remove keys with None values from a dict."""
    return {k: v for k, v in d.items() if v is not None}
