"""Game persistence helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, literal_column, or_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..db import db_models
from ..logging import logger
from ..models import NormalizedGame
from ..utils.date_utils import season_from_date
from ..utils.datetime_utils import end_of_et_day_utc, now_utc
from ..utils.db_queries import get_league_id
from .teams import _upsert_team

if TYPE_CHECKING:
    from ..models import TeamIdentity


def _normalize_status(status: str | None) -> str:
    if not status:
        return db_models.GameStatus.scheduled.value
    status_normalized = status.lower()
    if status_normalized in {"final", "completed"}:
        return db_models.GameStatus.final.value
    if status_normalized == db_models.GameStatus.live.value:
        return db_models.GameStatus.live.value
    if status_normalized == db_models.GameStatus.pregame.value:
        return db_models.GameStatus.pregame.value
    if status_normalized == db_models.GameStatus.archived.value:
        return db_models.GameStatus.archived.value
    if status_normalized == db_models.GameStatus.scheduled.value:
        return db_models.GameStatus.scheduled.value
    if status_normalized == db_models.GameStatus.postponed.value:
        return db_models.GameStatus.postponed.value
    if status_normalized == db_models.GameStatus.canceled.value:
        return db_models.GameStatus.canceled.value
    return db_models.GameStatus.scheduled.value


# One-way progression order for the happy path.
# Higher index = further along in lifecycle. Transitions may only move forward.
_STATUS_ORDER: dict[str, int] = {
    db_models.GameStatus.scheduled.value: 0,
    db_models.GameStatus.pregame.value: 1,
    db_models.GameStatus.live.value: 2,
    db_models.GameStatus.final.value: 3,
    db_models.GameStatus.archived.value: 4,
}


def resolve_status_transition(current_status: str | None, incoming_status: str | None) -> str:
    """Resolve a safe status transition without regressing games.

    Rules:
    - archived is terminal (never regresses from archived)
    - final never regresses (except to archived)
    - Generally, status only moves forward in the lifecycle
    - Non-lifecycle statuses (postponed, canceled) are accepted as-is
    """
    current = _normalize_status(current_status)
    incoming = _normalize_status(incoming_status)

    # Terminal states: archived never regresses
    if current == db_models.GameStatus.archived.value:
        return current

    # Final never regresses except to archived
    if current == db_models.GameStatus.final.value:
        if incoming == db_models.GameStatus.archived.value:
            return incoming
        return current

    # For lifecycle states, only allow forward progression
    current_order = _STATUS_ORDER.get(current)
    incoming_order = _STATUS_ORDER.get(incoming)

    if current_order is not None and incoming_order is not None:
        if incoming_order < current_order:
            return current  # Don't regress
        return incoming

    # Non-lifecycle statuses (postponed, canceled) pass through
    return incoming


def merge_external_ids(
    existing: dict[str, Any],
    updates: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge external IDs, preferring new non-null values."""
    if not updates:
        return existing

    merged = dict(existing or {})
    for key, value in updates.items():
        if value is not None:
            merged[key] = value
    return merged


def upsert_game_stub(
    session: Session,
    *,
    league_code: str,
    game_date: datetime,
    home_team: TeamIdentity,
    away_team: TeamIdentity,
    status: str | None,
    home_score: int | None = None,
    away_score: int | None = None,
    venue: str | None = None,
    external_ids: dict[str, Any] | None = None,
    tip_time: datetime | None = None,
) -> tuple[int, bool]:
    """Upsert a game without boxscores (used for live schedule feeds).

    Game matching uses DATE only (not exact datetime) to prevent duplicates
    when different sources provide different times for the same game.

    Args:
        tip_time: Actual scheduled start time (from Odds API or Live Feed).
                  If provided and game_date has no time component, tip_time is used.
    """
    league_id = get_league_id(session, league_code)
    home_team_id = _upsert_team(session, league_id, home_team)
    away_team_id = _upsert_team(session, league_id, away_team)
    normalized_status = _normalize_status(status)

    # Match games by DATE only (not exact datetime) to prevent duplicates
    # when Sports Reference (midnight) vs Odds API (actual time) create the same game.
    # Convert to ET before extracting date so late-night UTC games land on the correct
    # Eastern-Time sports-calendar day.
    game_date_only = game_date.astimezone(ZoneInfo("America/New_York")).date()

    # Use a UTC range that covers both old (midnight UTC) and new (midnight ET→UTC)
    # storage conventions so we never create duplicates during the migration window.
    day_start_utc = datetime.combine(game_date_only, datetime.min.time(), tzinfo=UTC)
    day_end_utc = end_of_et_day_utc(game_date_only)

    existing = (
        session.query(db_models.SportsGame)
        .filter(db_models.SportsGame.league_id == league_id)
        .filter(db_models.SportsGame.home_team_id == home_team_id)
        .filter(db_models.SportsGame.away_team_id == away_team_id)
        .filter(db_models.SportsGame.game_date >= day_start_utc)
        .filter(db_models.SportsGame.game_date < day_end_utc)
        .first()
    )

    if existing:
        updated_status = resolve_status_transition(existing.status, normalized_status)
        updated = False
        if updated_status != existing.status:
            existing.status = updated_status
            updated = True
        if home_score is not None and home_score != existing.home_score:
            existing.home_score = home_score
            updated = True
        if away_score is not None and away_score != existing.away_score:
            existing.away_score = away_score
            updated = True
        if venue and venue != existing.venue:
            existing.venue = venue
            updated = True
        if external_ids:
            merged_external_ids = merge_external_ids(existing.external_ids, external_ids)
            if merged_external_ids != existing.external_ids:
                existing.external_ids = merged_external_ids
                updated = True
        # Update tip_time if provided and not already set (or if new one is more specific)
        if tip_time and existing.tip_time is None:
            existing.tip_time = tip_time
            updated = True
        # Don't set end_time to now_utc() - it should come from PBP data
        if updated:
            existing.updated_at = now_utc()
            existing.last_ingested_at = now_utc()
        session.flush()
        return existing.id, False

    # Normalize game_date to midnight ET → UTC for storage so the stored
    # timestamp always represents the correct Eastern-Time sports-calendar day.
    normalized_game_date = datetime.combine(
        game_date_only, datetime.min.time(), tzinfo=ZoneInfo("America/New_York")
    ).astimezone(UTC)
    season = season_from_date(game_date_only, league_code)

    game = db_models.SportsGame(
        league_id=league_id,
        season=season,
        season_type="regular",
        game_date=normalized_game_date,
        tip_time=tip_time,  # Actual start time (from Odds API or Live Feed)
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        home_score=home_score,
        away_score=away_score,
        venue=venue,
        status=normalized_status,
        end_time=None,  # Will be set from PBP data when game is final
        source_game_key=None,
        scrape_version=1,
        last_scraped_at=None,
        last_ingested_at=now_utc(),
        external_ids=external_ids or {},
    )
    session.add(game)
    session.flush()
    return game.id, True


def update_game_from_live_feed(
    session: Session,
    *,
    game: db_models.SportsGame,
    status: str | None,
    home_score: int | None,
    away_score: int | None,
    venue: str | None = None,
    external_ids: dict[str, Any] | None = None,
    tip_time: datetime | None = None,
) -> bool:
    """Apply live feed updates while preventing status regression."""
    updated_status = resolve_status_transition(game.status, status)
    merged_external_ids = merge_external_ids(game.external_ids, external_ids)
    updated = False

    if updated_status != game.status:
        game.status = updated_status
        updated = True
    if home_score is not None and home_score != game.home_score:
        game.home_score = home_score
        updated = True
    if away_score is not None and away_score != game.away_score:
        game.away_score = away_score
        updated = True
    if venue and venue != game.venue:
        game.venue = venue
        updated = True
    if merged_external_ids != game.external_ids:
        game.external_ids = merged_external_ids
        updated = True
    # Update tip_time if provided and not already set
    if tip_time and game.tip_time is None:
        game.tip_time = tip_time
        updated = True
    # Don't set end_time to now_utc() - it should come from PBP data

    if updated:
        game.updated_at = now_utc()
        game.last_ingested_at = now_utc()
        session.flush()
    return updated


def upsert_game(session: Session, normalized: NormalizedGame, tip_time: datetime | None = None) -> tuple[int, bool]:
    """Upsert a game, creating or updating as needed.

    Returns the game ID and whether it was newly created.

    Args:
        tip_time: Actual scheduled start time (from Odds API or Live Feed).
    """
    league_id = get_league_id(session, normalized.identity.league_code)
    home_team_id = _upsert_team(session, league_id, normalized.identity.home_team)
    away_team_id = _upsert_team(session, league_id, normalized.identity.away_team)
    normalized_status = _normalize_status(normalized.status)
    # Don't set end_time to now_utc() - it should come from PBP data

    # Normalize game_date to midnight UTC for storage
    game_date_only = normalized.identity.game_date.date()
    normalized_game_date = datetime.combine(game_date_only, datetime.min.time(), tzinfo=UTC)

    base_stmt = insert(db_models.SportsGame).values(
        league_id=league_id,
        season=normalized.identity.season,
        season_type=normalized.identity.season_type,
        game_date=normalized_game_date,
        tip_time=tip_time,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        home_score=normalized.home_score,
        away_score=normalized.away_score,
        venue=normalized.venue,
        status=normalized_status,
        end_time=None,  # Will be set from PBP data
        source_game_key=normalized.identity.source_game_key,
        scrape_version=1,
        last_scraped_at=now_utc(),
        last_ingested_at=now_utc(),
        external_ids={},
    )
    excluded = base_stmt.excluded
    ingest_checks = [
        excluded.home_score.is_distinct_from(db_models.SportsGame.home_score),
        excluded.away_score.is_distinct_from(db_models.SportsGame.away_score),
        excluded.status.is_distinct_from(db_models.SportsGame.status),
        excluded.venue.is_distinct_from(db_models.SportsGame.venue),
    ]
    ingest_changed = or_(*ingest_checks)

    conflict_updates = {
        "home_score": normalized.home_score,
        "away_score": normalized.away_score,
        "status": normalized_status,
        "venue": normalized.venue,
        "scrape_version": db_models.SportsGame.scrape_version + 1,
        "last_scraped_at": now_utc(),
        "last_ingested_at": case(
            (ingest_changed, now_utc()),
            else_=db_models.SportsGame.last_ingested_at,
        ),
        "updated_at": now_utc(),
        # Preserve tip_time if provided, don't overwrite existing
        "tip_time": func.coalesce(db_models.SportsGame.tip_time, tip_time),
        # Don't touch end_time - it comes from PBP data
        # Only set source_game_key if the existing row doesn't have one; avoid clobber.
        "source_game_key": func.coalesce(db_models.SportsGame.source_game_key, normalized.identity.source_game_key),
    }

    # Prefer identity constraint to avoid duplicate-key violations when the same game is seen
    # under a different source_game_key.
    stmt = base_stmt.on_conflict_do_update(
        constraint="uq_game_identity",
        set_=conflict_updates,
    )

    stmt = stmt.returning(
        db_models.SportsGame.id,
        (literal_column("xmax") == 0).label("inserted"),
    )
    result = session.execute(stmt).first()
    if not result:
        raise RuntimeError("Failed to upsert game")
    game_id, inserted = result
    logger.info(
        "game_resolution",
        league=normalized.identity.league_code,
        game_id=int(game_id),
        external_id=normalized.identity.source_game_key,
        inserted=bool(inserted),
    )
    # Idempotent upsert: game_date is immutable, and end_time only set on final status.
    return int(game_id), bool(inserted)
