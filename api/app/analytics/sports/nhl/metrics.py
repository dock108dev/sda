"""NHL-specific metric calculations.

Computes derived player and team metrics from raw stats. Intended
to work with data from NHL game and player stat tables.

Input stat keys align with common NHL analytics fields:
- ``goals``, ``assists``, ``shots`` -- standard counting stats
- ``xgoals_for``, ``xgoals_against`` -- expected goals model
- ``corsi_pct``, ``fenwick_pct`` -- possession proxies
- ``shooting_pct``, ``save_pct``, ``pdo`` -- efficiency metrics
"""

from __future__ import annotations

from typing import Any

from app.analytics.core.types import PlayerProfile, TeamProfile
from app.analytics.sports._helpers import (
    metric_float as _float,
    metric_round as _round,
    strip_none as _strip_none,
)
from app.analytics.sports.nhl.constants import (
    BASELINE_CORSI_PCT as _BASELINE_CORSI,
)
from app.analytics.sports.nhl.constants import (
    BASELINE_SHOOTING_PCT as _BASELINE_SHOOTING,
)
from app.analytics.sports.nhl.constants import (
    BASELINE_XGOALS_AGAINST as _BASELINE_XGA,
)
from app.analytics.sports.nhl.constants import (
    BASELINE_XGOALS_FOR as _BASELINE_XGF,
)


class NHLMetrics:
    """Compute NHL-specific analytical metrics from raw stats."""

    # ------------------------------------------------------------------
    # Player metrics
    # ------------------------------------------------------------------

    def build_player_metrics(self, stats: dict[str, Any]) -> dict[str, float]:
        """Derive analytical player metrics from raw stats.

        Args:
            stats: Dict with keys such as ``goals``, ``assists``,
                ``shots``, ``xgoals_for``, ``game_score``,
                ``goals_per_60``, ``shots_per_60``.

        Returns:
            Dict of derived metric name -> value.
        """
        goals = _float(stats, "goals")
        assists = _float(stats, "assists")
        shots = _float(stats, "shots")
        xgoals_for = _float(stats, "xgoals_for")
        game_score = _float(stats, "game_score")
        goals_per_60 = _float(stats, "goals_per_60")
        shots_per_60 = _float(stats, "shots_per_60")

        points = None
        if goals is not None and assists is not None:
            points = goals + assists

        shooting_pct = None
        if goals is not None and shots is not None and shots > 0:
            shooting_pct = goals / shots

        goals_above_expected = None
        if goals is not None and xgoals_for is not None:
            goals_above_expected = goals - xgoals_for

        return _strip_none({
            "goals": _round(goals),
            "assists": _round(assists),
            "points": _round(points),
            "shots": _round(shots),
            "shooting_pct": _round(shooting_pct),
            "xgoals_for": _round(xgoals_for),
            "goals_above_expected": _round(goals_above_expected),
            "game_score": _round(game_score),
            "goals_per_60": _round(goals_per_60),
            "shots_per_60": _round(shots_per_60),
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
            sport="nhl",
            name=str(stats.get("name", "")),
            team_id=stats.get("team_id"),
            metrics=metrics,
        )

    # ------------------------------------------------------------------
    # Team metrics
    # ------------------------------------------------------------------

    def build_team_metrics(self, stats: dict[str, Any]) -> dict[str, float]:
        """Derive team-level metrics from aggregated stats.

        Args:
            stats: Team stat dict with keys such as ``xgoals_for``,
                ``xgoals_against``, ``corsi_pct``, ``fenwick_pct``,
                ``shooting_pct``, ``save_pct``, ``pdo``,
                ``high_danger_goals_for``, ``high_danger_goals_against``.

        Returns:
            Dict of team metric name -> value.
        """
        xgf = _float(stats, "xgoals_for")
        xga = _float(stats, "xgoals_against")
        corsi = _float(stats, "corsi_pct")
        fenwick = _float(stats, "fenwick_pct")
        shooting = _float(stats, "shooting_pct")
        save = _float(stats, "save_pct")
        pdo = _float(stats, "pdo")
        hd_gf = _float(stats, "high_danger_goals_for")
        hd_ga = _float(stats, "high_danger_goals_against")

        xgoals_pct = None
        if xgf is not None and xga is not None and (xgf + xga) > 0:
            xgoals_pct = xgf / (xgf + xga)

        xgoals_diff = None
        if xgf is not None and xga is not None:
            xgoals_diff = xgf - xga

        hd_diff = None
        if hd_gf is not None and hd_ga is not None:
            hd_diff = hd_gf - hd_ga

        return _strip_none({
            "xgoals_for": _round(xgf),
            "xgoals_against": _round(xga),
            "xgoals_pct": _round(xgoals_pct),
            "xgoals_diff": _round(xgoals_diff),
            "corsi_pct": _round(corsi),
            "fenwick_pct": _round(fenwick),
            "shooting_pct": _round(shooting),
            "save_pct": _round(save),
            "pdo": _round(pdo),
            "high_danger_goals_for": _round(hd_gf),
            "high_danger_goals_against": _round(hd_ga),
            "high_danger_diff": _round(hd_diff),
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
            sport="nhl",
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
        """Compare two teams/players on key NHL metrics.

        Computes differentials for expected goals, possession (Corsi),
        and shooting efficiency.

        Args:
            entity_a: First entity stats or pre-computed metrics.
            entity_b: Second entity stats or pre-computed metrics.

        Returns:
            Dict of matchup comparison metrics.
        """
        a_xgf = _float(entity_a, "xgoals_for") or _BASELINE_XGF
        b_xgf = _float(entity_b, "xgoals_for") or _BASELINE_XGF
        a_xga = _float(entity_a, "xgoals_against") or _BASELINE_XGA
        b_xga = _float(entity_b, "xgoals_against") or _BASELINE_XGA

        a_corsi = _float(entity_a, "corsi_pct") or _BASELINE_CORSI
        b_corsi = _float(entity_b, "corsi_pct") or _BASELINE_CORSI

        a_shooting = _float(entity_a, "shooting_pct") or _BASELINE_SHOOTING
        b_shooting = _float(entity_b, "shooting_pct") or _BASELINE_SHOOTING

        return _strip_none({
            "xgoals_for_diff": _round(a_xgf - b_xgf),
            "xgoals_against_diff": _round(a_xga - b_xga),
            "corsi_diff": _round(a_corsi - b_corsi),
            "shooting_pct_diff": _round(a_shooting - b_shooting),
            "a_expected_goals": _round(a_xgf),
            "b_expected_goals": _round(b_xgf),
            "a_corsi_pct": _round(a_corsi),
            "b_corsi_pct": _round(b_corsi),
        })


