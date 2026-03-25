"""NCAAB-specific metric calculations.

Computes derived player and team metrics from raw box score and
four-factor data. Intended to work with data already ingested
into the sports data pipeline.

Input stat keys align with standard NCAAB analytics:
- ``off_rating`` / ``def_rating`` — offensive and defensive efficiency
- ``off_efg_pct`` / ``off_tov_pct`` / ``off_orb_pct`` / ``off_ft_rate``
  — Dean Oliver's four factors (offensive)
- ``def_efg_pct`` / ``def_tov_pct`` / ``def_orb_pct`` / ``def_ft_rate``
  — four factors (defensive)
- ``pace`` — possessions per 40 minutes
"""

from __future__ import annotations

from typing import Any

from app.analytics.core.types import PlayerProfile, TeamProfile
from app.analytics.sports._helpers import (
    metric_float as _float,
    metric_float_or as _float_or,
    metric_round as _round,
    strip_none as _strip_none,
)
from app.analytics.sports.ncaab.constants import (
    BASELINE_DEF_RATING as _BASELINE_DEF_RATING,
)
from app.analytics.sports.ncaab.constants import (
    BASELINE_OFF_EFG_PCT as _BASELINE_OFF_EFG_PCT,
)
from app.analytics.sports.ncaab.constants import (
    BASELINE_OFF_RATING as _BASELINE_OFF_RATING,
)
from app.analytics.sports.ncaab.constants import (
    BASELINE_PACE as _BASELINE_PACE,
)


class NCAABMetrics:
    """Compute NCAAB-specific analytical metrics from raw stats."""

    # ------------------------------------------------------------------
    # Player metrics
    # ------------------------------------------------------------------

    def build_player_metrics(self, stats: dict[str, Any]) -> dict[str, float]:
        """Derive analytical player metrics from raw NCAAB stats.

        Args:
            stats: Dict with keys such as ``off_rating``, ``usage_rate``,
                ``ts_pct``, ``efg_pct``, ``game_score``, ``points``,
                ``rebounds``, ``assists``.

        Returns:
            Dict of derived metric name -> value.
        """
        off_rating = _float(stats, "off_rating")
        usage_rate = _float(stats, "usage_rate")
        ts_pct = _float(stats, "ts_pct")
        efg_pct = _float(stats, "efg_pct")
        game_score = _float(stats, "game_score")
        points = _float(stats, "points")
        rebounds = _float(stats, "rebounds")
        assists = _float(stats, "assists")

        return _strip_none({
            "off_rating": _round(off_rating),
            "usage_rate": _round(usage_rate),
            "ts_pct": _round(ts_pct),
            "efg_pct": _round(efg_pct),
            "game_score": _round(game_score),
            "points": _round(points),
            "rebounds": _round(rebounds),
            "assists": _round(assists),
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
            sport="ncaab",
            name=str(stats.get("name", "")),
            team_id=stats.get("team_id"),
            metrics=metrics,
        )

    # ------------------------------------------------------------------
    # Team metrics
    # ------------------------------------------------------------------

    def build_team_metrics(self, stats: dict[str, Any]) -> dict[str, float]:
        """Derive team-level four-factor metrics from raw stats.

        Args:
            stats: Team stat dict with four-factor keys such as
                ``off_rating``, ``def_rating``, ``net_rating``,
                ``pace``, ``off_efg_pct``, ``off_tov_pct``, etc.

        Returns:
            Dict of team metric name -> value.
        """
        off_rating = _float(stats, "off_rating")
        def_rating = _float(stats, "def_rating")
        net_rating = _float(stats, "net_rating")
        pace = _float(stats, "pace")

        off_efg_pct = _float(stats, "off_efg_pct")
        off_tov_pct = _float(stats, "off_tov_pct")
        off_orb_pct = _float(stats, "off_orb_pct")
        off_ft_rate = _float(stats, "off_ft_rate")

        def_efg_pct = _float(stats, "def_efg_pct")
        def_tov_pct = _float(stats, "def_tov_pct")
        def_orb_pct = _float(stats, "def_orb_pct")
        def_ft_rate = _float(stats, "def_ft_rate")

        fg3_rate = _float(stats, "fg3_rate")

        # Compute net rating if not provided
        if net_rating is None and off_rating is not None and def_rating is not None:
            net_rating = off_rating - def_rating

        return _strip_none({
            "off_rating": _round(off_rating),
            "def_rating": _round(def_rating),
            "net_rating": _round(net_rating),
            "pace": _round(pace),
            "off_efg_pct": _round(off_efg_pct),
            "off_tov_pct": _round(off_tov_pct),
            "off_orb_pct": _round(off_orb_pct),
            "off_ft_rate": _round(off_ft_rate),
            "def_efg_pct": _round(def_efg_pct),
            "def_tov_pct": _round(def_tov_pct),
            "def_orb_pct": _round(def_orb_pct),
            "def_ft_rate": _round(def_ft_rate),
            "fg3_rate": _round(fg3_rate),
        })

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
            sport="ncaab",
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
        """Estimate matchup advantages using four-factor comparisons.

        Compares team A's offensive four factors against team B's
        defensive four factors (and vice versa). Falls back to league
        baselines when data is unavailable.

        Args:
            entity_a: First team's stats or pre-computed metrics.
            entity_b: Second team's stats or pre-computed metrics.

        Returns:
            Dict of matchup metric name -> value.
        """
        a_off_efg = _float_or(entity_a, "off_efg_pct", _BASELINE_OFF_EFG_PCT)
        b_def_efg = _float_or(entity_b, "def_efg_pct", _BASELINE_OFF_EFG_PCT)

        a_off_tov = _float_or(entity_a, "off_tov_pct", 0.170)
        b_def_tov = _float_or(entity_b, "def_tov_pct", 0.170)

        a_pace = _float_or(entity_a, "pace", _BASELINE_PACE)
        b_pace = _float_or(entity_b, "pace", _BASELINE_PACE)

        a_off_orb = _float_or(entity_a, "off_orb_pct", 0.280)
        b_def_orb = _float_or(entity_b, "def_orb_pct", 0.280)

        a_off_ft = _float_or(entity_a, "off_ft_rate", 0.300)
        b_def_ft = _float_or(entity_b, "def_ft_rate", 0.300)

        return {
            "efg_edge": _round(a_off_efg - b_def_efg),
            "tov_differential": _round(b_def_tov - a_off_tov),
            "orb_edge": _round(a_off_orb - b_def_orb),
            "ft_rate_edge": _round(a_off_ft - b_def_ft),
            "projected_pace": _round((a_pace + b_pace) / 2.0),
            "a_off_rating": _round(_float_or(entity_a, "off_rating", _BASELINE_OFF_RATING)),
            "b_def_rating": _round(_float_or(entity_b, "def_rating", _BASELINE_DEF_RATING)),
        }


