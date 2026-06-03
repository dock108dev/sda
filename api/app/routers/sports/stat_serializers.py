"""Boxscore and stat serializers shared by sports admin routes."""

from __future__ import annotations

from typing import Any

from ...db.sports import SportsPlayerBoxscore, SportsTeamBoxscore
from .schemas import (
    MLBBatterStat,
    MLBPitcherStat,
    NHLGoalieStat,
    NHLSkaterStat,
    PlayerStat,
    TeamStat,
)


def serialize_team_stat(
    box: SportsTeamBoxscore,
    league_code: str | None = None,
) -> TeamStat:
    """Serialize team boxscore from JSONB stats column."""
    normalized = None
    if league_code and box.stats:
        from ...services.stat_normalization import normalize_stats

        normalized_dicts = normalize_stats(box.stats, league_code)
        if normalized_dicts:
            from .schemas import NormalizedStat

            normalized = [NormalizedStat(**s) for s in normalized_dicts]

    return TeamStat(
        team=box.team.name if box.team else "Unknown",
        team_abbreviation=box.team.abbreviation if box.team else None,
        is_home=box.is_home,
        stats=box.stats or {},
        source=box.source,
        updated_at=box.updated_at,
        normalized_stats=normalized,
    )


def _extract_minutes(stats: dict[str, Any]) -> float | None:
    """Extract minutes played from stats dict."""
    minutes_val = stats.get("minutes")
    if isinstance(minutes_val, str) and ":" in minutes_val:
        parts = minutes_val.split(":")
        try:
            minutes_val = int(parts[0]) + int(parts[1]) / 60
        except (ValueError, IndexError):
            minutes_val = None
    elif isinstance(minutes_val, str):
        try:
            minutes_val = float(minutes_val)
        except ValueError:
            minutes_val = None
    return float(minutes_val) if isinstance(minutes_val, int | float) else None


def _get_int_stat(stats: dict[str, Any], key: str) -> int | None:
    """Extract int stat from JSONB stats dict."""
    if key in stats and stats[key] is not None:
        try:
            return int(stats[key])
        except (ValueError, TypeError):
            return None
    return None


def _get_nested_int(stats: dict[str, Any], key: str) -> int | None:
    """Extract int from nested CBB format like {"total": 5, "offensive": 2}."""
    value = stats.get(key)
    if value is None:
        return None
    if isinstance(value, dict):
        total = value.get("total")
        if total is not None:
            try:
                return int(total)
            except (ValueError, TypeError):
                pass
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def serialize_player_stat(
    player: SportsPlayerBoxscore,
    league_code: str | None = None,
) -> PlayerStat:
    """Serialize player boxscore, flattening stats for frontend display."""
    stats = player.stats or {}
    minutes_val = _extract_minutes(stats)

    # Rebounds: try flat key, then nested CBB API format
    rebounds = _get_int_stat(stats, "rebounds")
    if rebounds is None:
        rebounds = _get_nested_int(stats, "rebounds") or _get_nested_int(stats, "totalRebounds")

    normalized = None
    if league_code and stats:
        from ...services.stat_normalization import normalize_stats

        normalized_dicts = normalize_stats(stats, league_code)
        if normalized_dicts:
            from .schemas import NormalizedStat

            normalized = [NormalizedStat(**s) for s in normalized_dicts]

    return PlayerStat(
        team=player.team.name if player.team else "Unknown",
        team_abbreviation=player.team.abbreviation if player.team else None,
        player_name=player.player_name,
        minutes=round(minutes_val, 1) if minutes_val is not None else None,
        points=_get_int_stat(stats, "points") or _get_nested_int(stats, "points"),
        rebounds=rebounds,
        assists=_get_int_stat(stats, "assists") or _get_nested_int(stats, "assists"),
        raw_stats=stats,
        source=player.source,
        updated_at=player.updated_at,
        normalized_stats=normalized,
    )


def _extract_toi(stats: dict[str, Any]) -> str | None:
    """Extract time-on-ice, preserving MM:SS format for NHL.

    Handles multiple storage formats:
    - "toi" as MM:SS string (e.g., "21:12")
    - "minutes" as decimal float (e.g., 21.2 -> "21:12")
    - "toi" as total seconds (e.g., 1272 -> "21:12")
    """
    toi = stats.get("toi")
    if isinstance(toi, str) and ":" in toi:
        return toi

    # Try minutes field (stored as decimal, e.g., 21.2 means 21 min 12 sec)
    minutes_val = stats.get("minutes")
    if isinstance(minutes_val, int | float) and minutes_val > 0:
        mins = int(minutes_val)
        secs = int(round((minutes_val - mins) * 60))
        return f"{mins}:{secs:02d}"

    # If toi stored as seconds, convert to MM:SS
    if isinstance(toi, int | float):
        minutes = int(toi) // 60
        seconds = int(toi) % 60
        return f"{minutes}:{seconds:02d}"

    return None


def serialize_nhl_skater(player: SportsPlayerBoxscore) -> NHLSkaterStat:
    """Serialize NHL skater boxscore with hockey-specific fields."""
    stats = player.stats or {}
    return NHLSkaterStat(
        team=player.team.name if player.team else "Unknown",
        team_abbreviation=player.team.abbreviation if player.team else None,
        player_name=player.player_name,
        toi=_extract_toi(stats),
        goals=_get_int_stat(stats, "goals"),
        assists=_get_int_stat(stats, "assists"),
        points=_get_int_stat(stats, "points"),
        shots_on_goal=_get_int_stat(stats, "shots_on_goal"),
        plus_minus=_get_int_stat(stats, "plus_minus"),
        penalty_minutes=_get_int_stat(stats, "penalty_minutes"),
        hits=_get_int_stat(stats, "hits"),
        blocked_shots=_get_int_stat(stats, "blocked_shots"),
        raw_stats=stats,
        source=player.source,
        updated_at=player.updated_at,
    )


def _get_float_stat(stats: dict[str, Any], key: str) -> float | None:
    """Extract float stat from JSONB stats dict."""
    if key in stats and stats[key] is not None:
        try:
            return float(stats[key])
        except (ValueError, TypeError):
            return None
    return None


def _normalize_save_pct(stats: dict) -> float | None:
    """Return SV% as decimal (0.935). Handles legacy rows stored as percentage (93.5)."""
    val = _get_float_stat(stats, "save_percentage")
    if val is not None and val > 1:
        val = round(val / 100, 4)
    return val


def serialize_nhl_goalie(player: SportsPlayerBoxscore) -> NHLGoalieStat:
    """Serialize NHL goalie boxscore with goaltender-specific fields."""
    stats = player.stats or {}
    return NHLGoalieStat(
        team=player.team.name if player.team else "Unknown",
        team_abbreviation=player.team.abbreviation if player.team else None,
        player_name=player.player_name,
        toi=_extract_toi(stats),
        shots_against=_get_int_stat(stats, "shots_against"),
        saves=_get_int_stat(stats, "saves"),
        goals_against=_get_int_stat(stats, "goals_against"),
        save_percentage=_normalize_save_pct(stats),
        raw_stats=stats,
        source=player.source,
        updated_at=player.updated_at,
    )


def serialize_mlb_batter(player: SportsPlayerBoxscore) -> MLBBatterStat:
    """Serialize MLB batter boxscore with baseball-specific fields."""
    stats = player.stats or {}
    return MLBBatterStat(
        team=player.team.name if player.team else "Unknown",
        team_abbreviation=player.team.abbreviation if player.team else None,
        player_name=player.player_name,
        position=stats.get("position") or getattr(player, "position", None),
        at_bats=_get_int_stat(stats, "atBats"),
        hits=_get_int_stat(stats, "hits"),
        runs=_get_int_stat(stats, "runs"),
        rbi=_get_int_stat(stats, "rbi"),
        home_runs=_get_int_stat(stats, "homeRuns"),
        base_on_balls=_get_int_stat(stats, "baseOnBalls"),
        strike_outs=_get_int_stat(stats, "strikeOuts"),
        stolen_bases=_get_int_stat(stats, "stolenBases"),
        avg=stats.get("avg"),
        obp=stats.get("obp"),
        slg=stats.get("slg"),
        ops=stats.get("ops"),
        raw_stats=stats,
        source=player.source,
        updated_at=player.updated_at,
    )


def serialize_mlb_pitcher(player: SportsPlayerBoxscore) -> MLBPitcherStat:
    """Serialize MLB pitcher boxscore with pitching-specific fields."""
    stats = player.stats or {}
    return MLBPitcherStat(
        team=player.team.name if player.team else "Unknown",
        team_abbreviation=player.team.abbreviation if player.team else None,
        player_name=player.player_name,
        innings_pitched=stats.get("inningsPitched"),
        hits=_get_int_stat(stats, "hits"),
        runs=_get_int_stat(stats, "runs"),
        earned_runs=_get_int_stat(stats, "earnedRuns"),
        base_on_balls=_get_int_stat(stats, "baseOnBalls"),
        strike_outs=_get_int_stat(stats, "strikeOuts"),
        home_runs=_get_int_stat(stats, "homeRuns"),
        era=stats.get("era"),
        pitch_count=_get_int_stat(stats, "pitchCount"),
        strikes=_get_int_stat(stats, "strikes"),
        raw_stats=stats,
        source=player.source,
        updated_at=player.updated_at,
    )
