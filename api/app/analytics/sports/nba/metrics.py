"""NBA-specific metric calculations.

Computes derived player, team, and matchup metrics from raw stats.
Intended to work with data already ingested into NBA stat tables.

Input stat keys align with common NBA advanced stats:
- ``off_rating`` / ``def_rating`` — offensive/defensive efficiency
- ``pace`` — possessions per 48 minutes
- ``ts_pct`` / ``efg_pct`` — shooting efficiency
- ``tov_pct`` — turnover percentage
- ``orb_pct`` / ``drb_pct`` — rebounding percentages
- ``usage_rate`` — usage percentage
"""

from __future__ import annotations

from typing import Any

from app.analytics.core.types import PlayerProfile, TeamProfile
from app.analytics.sports._helpers import (
    metric_float as _float,
    metric_round as _round,
    safe_mean as _safe_mean,
    strip_none as _strip_none,
)
from app.analytics.sports.nba.constants import (
    BASELINE_DEF_RATING as _BASELINE_DEF_RATING,
)
from app.analytics.sports.nba.constants import (
    BASELINE_EFG_PCT as _BASELINE_EFG_PCT,
)
from app.analytics.sports.nba.constants import (
    BASELINE_OFF_RATING as _BASELINE_OFF_RATING,
)
from app.analytics.sports.nba.constants import (
    BASELINE_PACE as _BASELINE_PACE,
)


class NBAMetrics:
    """Compute NBA-specific analytical metrics from raw stats."""

    # ------------------------------------------------------------------
    # Player metrics
    # ------------------------------------------------------------------

    def build_player_metrics(self, stats: dict[str, Any]) -> dict[str, float]:
        """Derive analytical player metrics from raw NBA stats.

        Args:
            stats: Dict with keys such as ``off_rating``, ``def_rating``,
                ``ts_pct``, ``efg_pct``, ``ast_pct``, ``tov_pct``,
                ``orb_pct``, ``usage_rate``, ``contested_shots``,
                ``deflections``.

        Returns:
            Dict of derived metric name -> value.
        """
        off_rating = _float(stats, "off_rating")
        def_rating = _float(stats, "def_rating")
        usage_rate = _float(stats, "usage_rate")
        ts_pct = _float(stats, "ts_pct")
        efg_pct = _float(stats, "efg_pct")
        ast_pct = _float(stats, "ast_pct")
        tov_pct = _float(stats, "tov_pct")
        orb_pct = _float(stats, "orb_pct")
        contested_shots = _float(stats, "contested_shots")
        deflections = _float(stats, "deflections")

        net_rating = None
        if off_rating is not None and def_rating is not None:
            net_rating = off_rating - def_rating

        return _strip_none({
            "off_rating": _round(off_rating),
            "def_rating": _round(def_rating),
            "net_rating": _round(net_rating),
            "usage_rate": _round(usage_rate),
            "ts_pct": _round(ts_pct),
            "efg_pct": _round(efg_pct),
            "ast_pct": _round(ast_pct),
            "tov_pct": _round(tov_pct),
            "orb_pct": _round(orb_pct),
            "contested_shots": _round(contested_shots),
            "deflections": _round(deflections),
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
            sport="nba",
            name=str(stats.get("name", "")),
            team_id=stats.get("team_id"),
            metrics=metrics,
        )

    # ------------------------------------------------------------------
    # Team metrics
    # ------------------------------------------------------------------

    def build_team_metrics(self, stats: dict[str, Any]) -> dict[str, float]:
        """Derive team-level metrics from aggregated or per-player stats.

        Accepts either pre-aggregated team stats or a ``players`` list
        of individual player stat dicts that will be averaged.

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
        off_rating = _float(stats, "off_rating")
        def_rating = _float(stats, "def_rating")
        net_rating = _float(stats, "net_rating")
        pace = _float(stats, "pace")
        efg_pct = _float(stats, "efg_pct")
        ts_pct = _float(stats, "ts_pct")
        tov_pct = _float(stats, "tov_pct")
        orb_pct = _float(stats, "orb_pct")
        ft_rate = _float(stats, "ft_rate")
        fg3_pct = _float(stats, "fg3_pct")
        ast_pct = _float(stats, "ast_pct")
        paint_points = _float(stats, "paint_points")
        fastbreak_points = _float(stats, "fastbreak_points")

        if net_rating is None and off_rating is not None and def_rating is not None:
            net_rating = off_rating - def_rating

        return _strip_none({
            "off_rating": _round(off_rating),
            "def_rating": _round(def_rating),
            "net_rating": _round(net_rating),
            "pace": _round(pace),
            "efg_pct": _round(efg_pct),
            "ts_pct": _round(ts_pct),
            "tov_pct": _round(tov_pct),
            "orb_pct": _round(orb_pct),
            "ft_rate": _round(ft_rate),
            "fg3_pct": _round(fg3_pct),
            "ast_pct": _round(ast_pct),
            "paint_points": _round(paint_points),
            "fastbreak_points": _round(fastbreak_points),
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
            sport="nba",
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
        """Estimate matchup dynamics between two teams.

        Compares offensive vs defensive ratings, pace differential,
        and shooting efficiency gaps.

        Args:
            entity_a: Team A stats or pre-computed metrics.
            entity_b: Team B stats or pre-computed metrics.

        Returns:
            Dict of matchup metric name -> value.
        """
        a_off = _float(entity_a, "off_rating") or _BASELINE_OFF_RATING
        a_pace = _float(entity_a, "pace") or _BASELINE_PACE
        a_efg = _float(entity_a, "efg_pct") or _BASELINE_EFG_PCT

        b_off = _float(entity_b, "off_rating") or _BASELINE_OFF_RATING
        b_def = _float(entity_b, "def_rating") or _BASELINE_DEF_RATING
        b_pace = _float(entity_b, "pace") or _BASELINE_PACE

        a_def = _float(entity_a, "def_rating") or _BASELINE_DEF_RATING
        b_efg = _float(entity_b, "efg_pct") or _BASELINE_EFG_PCT

        # Offensive efficiency vs opponent defense
        a_off_vs_b_def = _round(a_off - b_def)
        b_off_vs_a_def = _round(b_off - a_def)

        # Pace differential
        pace_diff = _round(a_pace - b_pace)
        expected_pace = _round(_safe_mean(a_pace, b_pace))

        # Shooting efficiency gap
        efg_diff = _round(a_efg - b_efg)

        return _strip_none({
            "a_off_vs_b_def": a_off_vs_b_def,
            "b_off_vs_a_def": b_off_vs_a_def,
            "pace_differential": pace_diff,
            "expected_pace": expected_pace,
            "efg_differential": efg_diff,
        })

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
        keys: set[str] = set()
        for m in all_metrics:
            keys.update(m.keys())

        team: dict[str, float] = {}
        for key in sorted(keys):
            vals = [m[key] for m in all_metrics if key in m]
            if vals:
                team[f"team_{key}"] = _round(sum(vals) / len(vals))
        return team


