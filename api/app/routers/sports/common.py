"""Shared helpers for sports admin routes."""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy import select

from ...db import AsyncSession
from ...db.scraper import SportsScrapeRun
from ...db.sports import (
    SportsGamePlay,
    SportsLeague,
    SportsPlayerBoxscore,
    SportsTeamBoxscore,
)
from .schemas import (
    MLBBatterStat,
    MLBPitcherStat,
    NHLGoalieStat,
    NHLSkaterStat,
    PlayEntry,
    PlayerStat,
    ScrapeRunConfig,
    ScrapeRunResponse,
    TeamStat,
)
from .schemas.common import _score_obj


def serialize_play_entry(play: SportsGamePlay, league_code: str | None = None) -> PlayEntry:
    """Serialize a play record to API response format."""
    from ...services.period_labels import period_label, time_label

    team_abbr = None
    if play.team:
        team_abbr = play.team.abbreviation
    elif isinstance(play.raw_data, dict):
        team_abbr = play.raw_data.get("team_abbreviation")

    # Compute display-ready period/time labels when league + period are available
    p_label: str | None = None
    t_label: str | None = None
    if play.quarter is not None and league_code:
        p_label = period_label(play.quarter, league_code)
        t_label = time_label(play.quarter, play.game_clock, league_code)

    return PlayEntry(
        play_index=play.play_index,
        quarter=play.quarter,
        game_clock=play.game_clock,
        period_label=p_label,
        time_label=t_label,
        play_type=play.play_type,
        team_abbreviation=team_abbr,
        player_name=play.player_name,
        description=play.description,
        score=_score_obj(play.home_score, play.away_score),
    )


_URL_PATTERN = re.compile(r"https?://\S+")


def normalize_post_text(text: str | None) -> str | None:
    """Normalize post text for deduplication."""
    if not text:
        return None
    cleaned = _URL_PATTERN.sub("", text.lower())
    cleaned = re.sub(r"[^a-z0-9\s]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or None


async def get_league(session: AsyncSession, code: str) -> SportsLeague:
    """Fetch league by code or raise 404."""
    stmt = select(SportsLeague).where(SportsLeague.code == code.upper())
    result = await session.execute(stmt)
    league = result.scalar_one_or_none()
    if not league:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"League {code} not found"
        )
    return league


logger = logging.getLogger(__name__)


def _normalize_config(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """Parse raw JSONB config through ScrapeRunConfig for consistent camelCase."""
    if not raw:
        return raw
    try:
        return ScrapeRunConfig(**raw).model_dump(by_alias=True)
    except ValidationError:
        logger.warning("malformed_scrape_run_config", extra={"raw_config": raw})
        return raw


def serialize_run(run: SportsScrapeRun, league_code: str) -> ScrapeRunResponse:
    """Serialize scrape run to API response."""
    return ScrapeRunResponse(
        id=run.id,
        league_code=league_code,
        status=run.status,
        scraper_type=run.scraper_type,
        job_id=run.job_id,
        season=run.season,
        start_date=run.start_date.date() if run.start_date else None,
        end_date=run.end_date.date() if run.end_date else None,
        summary=run.summary,
        error_details=run.error_details,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        requested_by=run.requested_by,
        config=_normalize_config(run.config),
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
    return float(minutes_val) if isinstance(minutes_val, (int, float)) else None


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
    if isinstance(minutes_val, (int, float)) and minutes_val > 0:
        mins = int(minutes_val)
        secs = int(round((minutes_val - mins) * 60))
        return f"{mins}:{secs:02d}"

    # If toi stored as seconds, convert to MM:SS
    if isinstance(toi, (int, float)):
        minutes = int(toi) // 60
        seconds = int(toi) % 60
        return f"{minutes}:{seconds:02d}"

    return None


def serialize_nhl_skater(player: SportsPlayerBoxscore) -> NHLSkaterStat:
    """Serialize NHL skater boxscore with hockey-specific fields."""
    stats = player.stats or {}
    return NHLSkaterStat(
        team=player.team.name if player.team else "Unknown",
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
