"""Boxscore helper functions and dataclasses.

Internal helpers for boxscore validation, stats building,
game matching, and enrichment. Used by boxscores.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from ..db import db_models
from ..logging import logger
from ..models import NormalizedGame, NormalizedPlayerBoxscore, NormalizedTeamBoxscore
from ..utils.datetime_utils import date_window_for_matching, now_utc, to_et_date
from .games import _normalize_status, resolve_status_transition


@dataclass(frozen=True)
class PlayerBoxscoreStats:
    """Statistics from player boxscore upsert operation."""
    inserted: int = 0
    rejected: int = 0
    errors: int = 0

    @property
    def total_processed(self) -> int:
        return self.inserted + self.rejected + self.errors


@dataclass(frozen=True)
class GamePersistResult:
    """Result of boxscore persistence (enrichment-only model).

    Boxscores enrich existing games; they never create new game records.
    Games are created exclusively by Odds API during schedule sync.
    """
    game_id: int | None
    enriched: bool = False
    player_stats: PlayerBoxscoreStats | None = None

    @property
    def has_player_stats(self) -> bool:
        """Returns True if player stats were successfully upserted."""
        return self.player_stats is not None and self.player_stats.inserted > 0


def _validate_nhl_player_boxscore(payload: NormalizedPlayerBoxscore, game_id: int) -> str | None:
    """Validate NHL player boxscore before insertion.

    Returns None if valid, or a rejection reason string if invalid.
    Logs rejected rows with game_id, team, role, and reason.
    """
    # Only apply NHL-specific validation for NHL
    if payload.team.league_code != "NHL":
        return None

    team_name = payload.team.name or payload.team.abbreviation or "unknown"

    # Check: player name is required
    if not payload.player_name or not payload.player_name.strip():
        reason = "missing_player_name"
        logger.warning(
            "nhl_player_boxscore_rejected",
            game_id=game_id,
            team=team_name,
            role=payload.player_role,
            reason=reason,
            player_id=payload.player_id,
        )
        return reason

    # Check: player role is required for NHL
    if not payload.player_role:
        reason = "missing_player_role"
        logger.warning(
            "nhl_player_boxscore_rejected",
            game_id=game_id,
            team=team_name,
            role=None,
            reason=reason,
            player_name=payload.player_name,
        )
        return reason

    # Check: at least one stat field must be non-null (don't fabricate zeroes)
    # Check role-specific stats based on player_role
    if payload.player_role == "skater":
        has_stats = any([
            payload.minutes is not None,
            payload.goals is not None,
            payload.assists is not None,
            payload.points is not None,
            payload.shots_on_goal is not None,
            payload.plus_minus is not None,
            payload.hits is not None,
            payload.blocked_shots is not None,
        ])
    elif payload.player_role == "goalie":
        has_stats = any([
            payload.minutes is not None,
            payload.saves is not None,
            payload.goals_against is not None,
            payload.shots_against is not None,
            payload.save_percentage is not None,
        ])
    else:
        # Unknown role - should not happen due to earlier validation
        has_stats = False

    if not has_stats:
        reason = "all_stats_null"
        logger.warning(
            "nhl_player_boxscore_rejected",
            game_id=game_id,
            team=team_name,
            role=payload.player_role,
            reason=reason,
            player_name=payload.player_name,
        )
        return reason

    return None  # Valid


def _build_team_stats(payload: NormalizedTeamBoxscore) -> dict:
    """Build stats dict from typed fields + raw_stats, excluding None values."""
    stats = {}
    if payload.points is not None:
        stats["points"] = payload.points
    if payload.rebounds is not None:
        stats["rebounds"] = payload.rebounds
    if payload.assists is not None:
        stats["assists"] = payload.assists
    if payload.turnovers is not None:
        stats["turnovers"] = payload.turnovers
    if payload.hits is not None:
        stats["hits"] = payload.hits
    if payload.shots_on_goal is not None:
        stats["shots_on_goal"] = payload.shots_on_goal
    if payload.penalty_minutes is not None:
        stats["penalty_minutes"] = payload.penalty_minutes
    if payload.raw_stats:
        stats.update(payload.raw_stats)
    return stats


def _build_player_stats(payload: NormalizedPlayerBoxscore) -> dict:
    """Build stats dict from typed fields + raw_stats, excluding None values."""
    stats = {}
    # Common fields
    if payload.player_role is not None:
        stats["player_role"] = payload.player_role
    if payload.position is not None:
        stats["position"] = payload.position
    if payload.sweater_number is not None:
        stats["sweater_number"] = payload.sweater_number
    if payload.minutes is not None:
        stats["minutes"] = payload.minutes
    if payload.points is not None:
        stats["points"] = payload.points
    if payload.rebounds is not None:
        stats["rebounds"] = payload.rebounds
    if payload.assists is not None:
        stats["assists"] = payload.assists
    # NHL skater stats
    if payload.shots_on_goal is not None:
        stats["shots_on_goal"] = payload.shots_on_goal
    if payload.penalties is not None:
        stats["penalties"] = payload.penalties
    if payload.goals is not None:
        stats["goals"] = payload.goals
    if payload.plus_minus is not None:
        stats["plus_minus"] = payload.plus_minus
    if payload.hits is not None:
        stats["hits"] = payload.hits
    if payload.blocked_shots is not None:
        stats["blocked_shots"] = payload.blocked_shots
    if payload.shifts is not None:
        stats["shifts"] = payload.shifts
    if payload.giveaways is not None:
        stats["giveaways"] = payload.giveaways
    if payload.takeaways is not None:
        stats["takeaways"] = payload.takeaways
    if payload.faceoff_pct is not None:
        stats["faceoff_pct"] = payload.faceoff_pct
    # NHL goalie stats
    if payload.saves is not None:
        stats["saves"] = payload.saves
    if payload.goals_against is not None:
        stats["goals_against"] = payload.goals_against
    if payload.shots_against is not None:
        stats["shots_against"] = payload.shots_against
    if payload.save_percentage is not None:
        stats["save_percentage"] = payload.save_percentage
    # Raw stats (includes any additional fields)
    if payload.raw_stats:
        stats.update(payload.raw_stats)
    return stats


def _find_game_for_boxscore(
    session: Session,
    league_id: int,
    home_team_id: int,
    away_team_id: int,
    game_date: datetime,
) -> db_models.SportsGame | None:
    """Find an existing game by identity (league, teams, date).

    Uses a ±1 day window to handle timezone differences between sources:
    - Odds API may store games with UTC date (Jan 23 00:00 UTC for a 7pm ET game on Jan 22)
    - Sports Reference uses US local date (Jan 22 for the same game)

    This range-based matching ensures games are found regardless of which source created them.
    """
    day_start, day_end = date_window_for_matching(to_et_date(game_date), days_before=0, days_after=1)
    return (
        session.query(db_models.SportsGame)
        .filter(db_models.SportsGame.league_id == league_id)
        .filter(db_models.SportsGame.home_team_id == home_team_id)
        .filter(db_models.SportsGame.away_team_id == away_team_id)
        .filter(db_models.SportsGame.game_date >= day_start)
        .filter(db_models.SportsGame.game_date < day_end)
        .order_by(db_models.SportsGame.game_date.asc())
        .first()
    )


def _enrich_game_with_boxscore(
    session: Session,
    game: db_models.SportsGame,
    payload: NormalizedGame,
) -> bool:
    """Update an existing game with boxscore data. Returns True if game was updated.

    This enriches a pregame placeholder with final game data:
    - Sets scores, venue, source_game_key
    - Transitions status from scheduled to final
    """
    updated = False

    # Update scores
    if payload.home_score is not None and payload.home_score != game.home_score:
        game.home_score = payload.home_score
        updated = True
    if payload.away_score is not None and payload.away_score != game.away_score:
        game.away_score = payload.away_score
        updated = True

    # Update venue if provided
    if payload.venue and payload.venue != game.venue:
        game.venue = payload.venue
        updated = True

    # source_game_key is set at game creation time (upsert in persist_game_payload).
    # Do NOT set it here during enrichment — if two rows exist for the same game,
    # setting it here causes UniqueViolation on uq_sports_game_league_source_key.

    # Transition status (scheduled → final) with protection against regression
    normalized_status = _normalize_status(payload.status)
    new_status = resolve_status_transition(game.status, normalized_status)
    if new_status != game.status:
        game.status = new_status
        updated = True

    if updated:
        game.updated_at = now_utc()
        game.last_scraped_at = now_utc()
        game.last_ingested_at = now_utc()
        game.scrape_version = (game.scrape_version or 0) + 1
        session.flush()

    return updated
