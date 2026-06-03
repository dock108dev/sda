"""Game persistence helpers.

Central game resolution: ``find_or_create_game()`` is the **single entry
point** for every ingestion path (odds, boxscores, PBP, player stats,
schedule feeds, live feeds, backfill).  It uses a multi-tier matching
strategy and a Redis-based match cache shared across all Celery workers.
"""

from __future__ import annotations

from datetime import date as _date_type
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session, object_session

from ..db import db_models
from ..logging import logger
from ..models import NormalizedGame
from ..utils.date_utils import season_from_date
from ..utils.datetime_utils import end_of_et_day_utc, now_utc, start_of_et_day_utc, to_et_date
from ..utils.db_queries import get_league_id
from .game_cache import _cache_delete, _cache_get, _cache_key, _cache_set, _notify_game_update
from .game_status import _normalize_status, merge_external_ids, resolve_status_transition
from .teams import _upsert_team

if TYPE_CHECKING:
    from ..models import TeamIdentity


# ---------------------------------------------------------------------------
# Unified find-or-create
# ---------------------------------------------------------------------------


def _has_real_time(game_date) -> bool:
    """Return True if game_date carries a meaningful tip time (not a
    placeholder created from a date-only source).

    Recognises two placeholder patterns:
    - midnight ET  (from ``date_to_utc_datetime`` / ``_to_datetime``)
    - noon ET      (from NHL ``_et_noon_utc`` schedule fallback)
    """
    if isinstance(game_date, _date_type) and not isinstance(game_date, datetime):
        return False  # bare date — no time info
    et_day = to_et_date(game_date)
    midnight_et = start_of_et_day_utc(et_day)
    noon_et = midnight_et + timedelta(hours=12)
    return game_date != midnight_et and game_date != noon_et


def _to_datetime(game_date) -> datetime:
    """Coerce a date or datetime to a timezone-aware UTC datetime for storage."""
    if isinstance(game_date, _date_type) and not isinstance(game_date, datetime):
        return start_of_et_day_utc(game_date)
    return game_date


def find_or_create_game(
    session: Session,
    *,
    league_code: str,
    game_date: datetime,  # accepts date or datetime
    home_team: TeamIdentity,
    away_team: TeamIdentity,
    status: str | None = None,
    home_score: int | None = None,
    away_score: int | None = None,
    venue: str | None = None,
    external_ids: dict[str, Any] | None = None,
    source_game_key: str | None = None,
    season_type: str = "regular",
    create_if_missing: bool = True,
) -> tuple[int | None, bool]:
    """Find an existing game or create one.  THE single entry point for all
    ingestion paths.

    Matching strategy (tried in order):
    1. Redis cache hit (keyed by league + ET date + sorted team IDs)
    2. External ID match (nba_game_id, nhl_game_pk, odds_api_event_id, etc.)
    3. source_game_key match
    4. Team ID + ET calendar day match (exact home/away)
    5. Team ID + ET calendar day match (swapped home/away)
    6. Create (if ``create_if_missing=True``)

    On match, merges external_ids and updates game_date if more precise.
    NEVER caches negative results — only positive matches are cached.

    Returns ``(game_id, created)``.  If ``create_if_missing=False`` and no
    match, returns ``(None, False)``.
    """
    league_id = get_league_id(session, league_code)
    home_team_id = _upsert_team(session, league_id, home_team)
    away_team_id = _upsert_team(session, league_id, away_team)

    # Coerce date → datetime for DB operations; keep original for _enrich checks
    game_date_dt = _to_datetime(game_date)
    game_date_only = to_et_date(game_date_dt)
    day_start = start_of_et_day_utc(game_date_only)
    day_end = end_of_et_day_utc(game_date_only)

    team_lo = min(home_team_id, away_team_id)
    team_hi = max(home_team_id, away_team_id)
    cache_key = _cache_key(league_code, game_date_only, team_lo, team_hi)

    # --- Tier 1: Redis cache ---
    cached_id = _cache_get(cache_key)
    if cached_id is not None:
        game = session.get(db_models.SportsGame, cached_id)
        if game is not None:
            _enrich_existing(game, status, home_score, away_score, venue,
                             external_ids, game_date, season_type)
            session.flush()
            return game.id, False
        # Game was deleted since caching — fall through
        _cache_delete(cache_key)

    # --- Tier 2: External ID match ---
    if external_ids:
        for eid_key in ("nba_game_id", "nhl_game_pk", "mlb_game_pk",
                        "espn_game_id", "cbb_game_id", "ncaa_game_id",
                        "odds_api_event_id"):
            eid_val = external_ids.get(eid_key)
            if eid_val is not None:
                game = (
                    session.query(db_models.SportsGame)
                    .filter(
                        db_models.SportsGame.league_id == league_id,
                        db_models.SportsGame.external_ids[eid_key].astext == str(eid_val),
                    )
                    .first()
                )
                if game is not None:
                    _enrich_existing(game, status, home_score, away_score,
                                     venue, external_ids, game_date, season_type)
                    session.flush()
                    _cache_set(cache_key, game.id)
                    return game.id, False

    # --- Tier 3: source_game_key match ---
    if source_game_key:
        game = (
            session.query(db_models.SportsGame)
            .filter(
                db_models.SportsGame.league_id == league_id,
                db_models.SportsGame.source_game_key == source_game_key,
            )
            .first()
        )
        if game is not None:
            _enrich_existing(game, status, home_score, away_score, venue,
                             external_ids, game_date, season_type)
            session.flush()
            _cache_set(cache_key, game.id)
            return game.id, False

    # --- Tier 4: Team ID + ET date (exact) ---
    game = (
        session.query(db_models.SportsGame)
        .filter(
            db_models.SportsGame.league_id == league_id,
            db_models.SportsGame.home_team_id == home_team_id,
            db_models.SportsGame.away_team_id == away_team_id,
            db_models.SportsGame.game_date >= day_start,
            db_models.SportsGame.game_date < day_end,
        )
        .first()
    )
    if game is not None:
        _enrich_existing(game, status, home_score, away_score, venue,
                         external_ids, game_date, season_type)
        session.flush()
        _cache_set(cache_key, game.id)
        return game.id, False

    # --- Tier 5: Team ID + ET date (swapped home/away) ---
    game = (
        session.query(db_models.SportsGame)
        .filter(
            db_models.SportsGame.league_id == league_id,
            db_models.SportsGame.home_team_id == away_team_id,
            db_models.SportsGame.away_team_id == home_team_id,
            db_models.SportsGame.game_date >= day_start,
            db_models.SportsGame.game_date < day_end,
        )
        .first()
    )
    if game is not None:
        _enrich_existing(game, status, home_score, away_score, venue,
                         external_ids, game_date, season_type)
        session.flush()
        _cache_set(cache_key, game.id)
        return game.id, False

    # --- Tier 6: Create ---
    if not create_if_missing:
        return None, False

    season = season_from_date(game_date_only, league_code)
    normalized_status = _normalize_status(status)

    game = db_models.SportsGame(
        league_id=league_id,
        season=season,
        season_type=season_type,
        game_date=game_date_dt,
        local_game_date=game_date_only,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        home_score=home_score,
        away_score=away_score,
        venue=venue,
        status=normalized_status,
        end_time=None,
        source_game_key=source_game_key,
        scrape_version=1,
        last_scraped_at=None,
        last_ingested_at=now_utc(),
        external_ids=external_ids or {},
    )
    session.add(game)
    session.flush()

    _cache_set(cache_key, game.id)

    logger.info(
        "game_created",
        league=league_code,
        game_id=game.id,
        game_date=str(game_date_only),
        home_team=home_team.name,
        away_team=away_team.name,
    )

    return game.id, True


def _enrich_existing(
    game: db_models.SportsGame,
    status: str | None,
    home_score: int | None,
    away_score: int | None,
    venue: str | None,
    external_ids: dict[str, Any] | None,
    game_date,
    season_type: str,
) -> None:
    """Update an existing game with new data without regressing state.

    Never updates ``game_date`` to a value that would violate the
    ``uq_game_identity`` constraint — if the new timestamp conflicts
    with another game row, the update is silently skipped.
    """
    updated = False

    # Status: only advance forward
    if status:
        new_status = resolve_status_transition(
            game.status,
            _normalize_status(status),
            game_date=game_date or game.game_date,
        )
        if new_status != game.status:
            game.status = new_status
            updated = True

    # Scores: only set if provided
    if home_score is not None and home_score != game.home_score:
        game.home_score = home_score
        updated = True
    if away_score is not None and away_score != game.away_score:
        game.away_score = away_score
        updated = True

    # Venue
    if venue and venue != game.venue:
        game.venue = venue
        updated = True

    # External IDs: merge
    if external_ids:
        merged = merge_external_ids(game.external_ids, external_ids)
        if merged != game.external_ids:
            game.external_ids = merged
            updated = True

    # Only update game_date when the incoming value carries a REAL time
    # and the existing value is a placeholder.
    # DO NOT update if it would violate uq_game_identity (another game
    # already has this exact timestamp for the same teams).
    if _has_real_time(game_date) and not _has_real_time(game.game_date):
        new_dt = _to_datetime(game_date)
        if new_dt != game.game_date:
            # Check for conflict before updating
            from sqlalchemy import select
            conflict = (
                select(db_models.SportsGame.id)
                .where(
                    db_models.SportsGame.league_id == game.league_id,
                    db_models.SportsGame.season == game.season,
                    db_models.SportsGame.game_date == new_dt,
                    db_models.SportsGame.home_team_id == game.home_team_id,
                    db_models.SportsGame.away_team_id == game.away_team_id,
                    db_models.SportsGame.id != game.id,
                )
            )
            # Use the session bound to this game's state
            sess = object_session(game)
            if sess and not sess.execute(conflict).first():
                game.game_date = new_dt
                updated = True

    # Keep local_game_date in sync with game_date. Backfills legacy rows
    # whose column was added but never populated, and tracks any update
    # to game_date above.
    expected_local_date = to_et_date(game.game_date)
    if game.local_game_date != expected_local_date:
        game.local_game_date = expected_local_date
        updated = True

    # Season type
    if season_type != "regular" and game.season_type == "regular":
        game.season_type = season_type
        updated = True

    if updated:
        game.updated_at = now_utc()
        game.last_ingested_at = now_utc()
        _notify_game_update(object_session(game), game.id)


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
    season_type: str = "regular",
) -> tuple[int, bool]:
    """Upsert a game without boxscores.

    Active thin wrapper around ``find_or_create_game`` for ingestion paths
    that only have schedule/live-feed fields.
    """
    game_id, created = find_or_create_game(
        session,
        league_code=league_code,
        game_date=game_date,
        home_team=home_team,
        away_team=away_team,
        status=status,
        home_score=home_score,
        away_score=away_score,
        venue=venue,
        external_ids=external_ids,
        season_type=season_type,
    )
    # find_or_create_game always creates if missing, so game_id is never None here
    return game_id, created  # type: ignore[return-value]


def update_game_from_live_feed(
    session: Session,
    *,
    game: db_models.SportsGame,
    status: str | None,
    home_score: int | None,
    away_score: int | None,
    venue: str | None = None,
    external_ids: dict[str, Any] | None = None,
) -> bool:
    """Apply live feed updates while preventing status regression."""
    updated_status = resolve_status_transition(
        game.status, status, game_date=game.game_date
    )
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

    if updated:
        game.updated_at = now_utc()
        game.last_ingested_at = now_utc()
        session.flush()
        _notify_game_update(session, game.id)
    return updated


def upsert_game(session: Session, normalized: NormalizedGame) -> tuple[int, bool]:
    """Upsert a game from historical boxscore ingestion.

    Delegates to ``find_or_create_game`` for game resolution, then sets
    boxscore-specific fields (source_game_key, scrape_version).

    Returns the game ID and whether it was newly created.
    """
    game_id, created = find_or_create_game(
        session,
        league_code=normalized.identity.league_code,
        game_date=normalized.identity.game_date,
        home_team=normalized.identity.home_team,
        away_team=normalized.identity.away_team,
        status=normalized.status,
        home_score=normalized.home_score,
        away_score=normalized.away_score,
        venue=normalized.venue,
        source_game_key=normalized.identity.source_game_key,
        season_type=normalized.identity.season_type or "regular",
    )

    # Set boxscore-specific fields that find_or_create_game doesn't handle
    if game_id is not None:
        game = session.get(db_models.SportsGame, game_id)
        if game is not None:
            updated = False
            if normalized.identity.source_game_key and not game.source_game_key:
                game.source_game_key = normalized.identity.source_game_key
                updated = True
            game.scrape_version = (game.scrape_version or 0) + 1
            game.last_scraped_at = now_utc()
            if updated:
                game.updated_at = now_utc()
            session.flush()

    logger.info(
        "game_resolution",
        league=normalized.identity.league_code,
        game_id=game_id,
        external_id=normalized.identity.source_game_key,
        inserted=created,
    )
    return game_id, created  # type: ignore[return-value]
