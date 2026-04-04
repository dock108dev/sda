"""Shared helpers for batch simulation tasks.

Contains sport-specific stats converters, rolling profile builder,
lineup serialization, and utility functions used by the main
batch simulation orchestrator.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sport-specific stats → metrics converters
# ---------------------------------------------------------------------------


def nba_stats_to_metrics(stats) -> dict:
    """Convert NBAGameAdvancedStats row to a flat metrics dict."""
    return {
        "off_rating": float(stats.off_rating or 114.0),
        "def_rating": float(stats.def_rating or 114.0),
        "net_rating": float(stats.net_rating or 0.0),
        "pace": float(stats.pace or 100.0),
        "efg_pct": float(stats.efg_pct or 0.54),
        "ts_pct": float(stats.ts_pct or 0.58),
        "tov_pct": float(stats.tov_pct or 0.13),
        "orb_pct": float(stats.orb_pct or 0.25),
        "ft_rate": float(stats.ft_rate or 0.27),
        "fg3_pct": float(stats.fg3_pct or 0.35),
        "ft_pct": float(stats.ft_pct or 0.78),
        "ast_pct": float(stats.ast_pct or 0.60),
    }


def nfl_stats_to_metrics(stats) -> dict:
    """Convert NFLGameAdvancedStats row to a flat metrics dict."""
    return {
        "epa_per_play": float(stats.epa_per_play or 0.0),
        "pass_epa": float(stats.pass_epa or 0.0),
        "rush_epa": float(stats.rush_epa or 0.0),
        "success_rate": float(stats.success_rate or 0.45),
        "pass_success_rate": float(stats.pass_success_rate or 0.45),
        "rush_success_rate": float(stats.rush_success_rate or 0.40),
        "explosive_play_rate": float(stats.explosive_play_rate or 0.08),
        "avg_cpoe": float(stats.avg_cpoe or 0.0),
        "total_plays": float(stats.total_plays or 60),
        "pass_plays": float(stats.pass_plays or 35),
        "rush_plays": float(stats.rush_plays or 25),
    }


def nhl_stats_to_metrics(stats) -> dict:
    """Convert NHLGameAdvancedStats row to a flat metrics dict."""
    return {
        "xgoals_for": float(stats.xgoals_for or 2.8),
        "xgoals_against": float(stats.xgoals_against or 2.8),
        "corsi_pct": float(stats.corsi_pct or 0.50),
        "fenwick_pct": float(stats.fenwick_pct or 0.50),
        "shooting_pct": float(stats.shooting_pct or 9.0),
        "save_pct": float(stats.save_pct or 91.0),
        "pdo": float(stats.pdo or 100.0),
        "shots_for": float(stats.shots_for or 30),
        "shots_against": float(stats.shots_against or 30),
    }


def ncaab_stats_to_metrics(stats) -> dict:
    """Convert NCAABGameAdvancedStats row to a flat metrics dict."""
    return {
        "off_rating": float(stats.off_rating or 105.0),
        "def_rating": float(stats.def_rating or 105.0),
        "net_rating": float(stats.net_rating or 0.0),
        "pace": float(stats.pace or 68.0),
        "off_efg_pct": float(stats.off_efg_pct or 0.50),
        "off_tov_pct": float(stats.off_tov_pct or 0.17),
        "off_orb_pct": float(stats.off_orb_pct or 0.28),
        "off_ft_rate": float(stats.off_ft_rate or 0.30),
        "def_efg_pct": float(stats.def_efg_pct or 0.50),
        "def_tov_pct": float(stats.def_tov_pct or 0.17),
        "def_orb_pct": float(stats.def_orb_pct or 0.28),
        "fg_pct": float(stats.fg_pct or 0.44),
        "three_pt_pct": float(stats.three_pt_pct or 0.34),
        "ft_pct": float(stats.ft_pct or 0.70),
    }


# ---------------------------------------------------------------------------
# Advanced stats model lookup
# ---------------------------------------------------------------------------


def get_advanced_stats_model(sport: str):
    """Return the advanced stats ORM model for a sport."""
    if sport == "nba":
        from app.db.nba_advanced import NBAGameAdvancedStats
        return NBAGameAdvancedStats
    if sport == "ncaab":
        from app.db.ncaab_advanced import NCAABGameAdvancedStats
        return NCAABGameAdvancedStats
    if sport == "nhl":
        from app.db.nhl_advanced import NHLGameAdvancedStats
        return NHLGameAdvancedStats
    if sport == "nfl":
        from app.db.nfl_advanced import NFLGameAdvancedStats
        return NFLGameAdvancedStats
    from app.db.mlb_advanced import MLBGameAdvancedStats
    return MLBGameAdvancedStats


# ---------------------------------------------------------------------------
# Rolling profile builder
# ---------------------------------------------------------------------------

from app.tasks._training_helpers import (  # noqa: E402
    build_rolling_profile as _build_rolling_profile_mlb,
)


def build_rolling_profile(
    team_games: list[tuple[str, object]],
    *,
    before_date: str,
    window: int,
    min_games: int = 5,
    sport: str = "mlb",
) -> dict | None:
    """Sport-aware rolling profile builder.

    For non-MLB sports, aggregates the last ``window`` games before
    ``before_date`` using sport-specific converters.  MLB delegates
    to ``_training_helpers.build_rolling_profile``.
    """
    if sport in ("nba", "ncaab", "nhl", "nfl"):
        converter = {
            "nba": nba_stats_to_metrics,
            "ncaab": ncaab_stats_to_metrics,
            "nhl": nhl_stats_to_metrics,
            "nfl": nfl_stats_to_metrics,
        }[sport]
        prior = [stats for date_str, stats in team_games if date_str < before_date]
        if len(prior) < min_games:
            return None
        recent = prior[-window:]
        all_metrics = [converter(s) for s in recent]
        aggregated: dict[str, float] = {}
        for key in all_metrics[0]:
            values = [m[key] for m in all_metrics if key in m]
            if values:
                aggregated[key] = round(sum(values) / len(values), 4)
        return aggregated
    return _build_rolling_profile_mlb(
        team_games, before_date=before_date, window=window, min_games=min_games,
    )


# ---------------------------------------------------------------------------
# Profile game counter
# ---------------------------------------------------------------------------


def count_profile_games(
    team_history: dict[int, list[tuple[str, object]]],
    team_id: int,
    cutoff: str,
    window: int,
) -> int | None:
    """Count games used in a team's rolling profile for observability."""
    if team_id not in team_history:
        return None
    prior = [s for d, s in team_history[team_id] if d < cutoff]
    return len(prior[-window:])


# ---------------------------------------------------------------------------
# Lineup metadata serializer
# ---------------------------------------------------------------------------


def serialize_lineup_meta(meta: dict) -> dict:
    """Convert lineup metadata into a JSON-serializable structure.

    Produces projected batting lines by combining each batter's name
    with their per-PA outcome probabilities (the simulation weights).
    """
    def _batter_line(batter: dict, weights: list[float]) -> dict:
        w = weights if len(weights) == 7 else [0] * 7
        return {
            "name": batter.get("name", "?"),
            "K": round(w[0] * 100, 1),
            "BB": round(w[1] * 100, 1),
            "1B": round(w[2] * 100, 1),
            "2B": round(w[3] * 100, 1),
            "3B": round(w[4] * 100, 1),
            "HR": round(w[5] * 100, 1),
            "BIP": round(w[6] * 100, 1),
        }

    home_lineup = meta.get("home_lineup", [])
    away_lineup = meta.get("away_lineup", [])
    home_weights = meta.get("home_weights", [])
    away_weights = meta.get("away_weights", [])

    home_lines = [
        _batter_line(b, home_weights[i] if i < len(home_weights) else [])
        for i, b in enumerate(home_lineup)
    ]
    away_lines = [
        _batter_line(b, away_weights[i] if i < len(away_weights) else [])
        for i, b in enumerate(away_lineup)
    ]

    result: dict = {
        "home_batting": home_lines,
        "away_batting": away_lines,
    }

    hs = meta.get("home_starter")
    if hs:
        result["home_starter"] = {"name": hs.get("name", "?"), "external_ref": hs.get("external_ref", "")}
    aws = meta.get("away_starter")
    if aws:
        result["away_starter"] = {"name": aws.get("name", "?"), "external_ref": aws.get("external_ref", "")}

    return result
