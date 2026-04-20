"""Odds persistence helpers.

Handles odds matching to games and persistence, including NCAAB-specific name matching.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from enum import Enum

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..db import db_models
from ..logging import logger
from ..models import NormalizedOddsSnapshot
from ..utils.datetime_utils import now_utc, to_et_date


def _notify_odds_update(session: Session, game_id: int) -> None:
    """Emit pg_notify('odds_update', ...) within the current transaction. Best-effort."""
    try:
        payload = json.dumps({"game_id": game_id, "event_type": "odds_update"})
        session.execute(
            text("SELECT pg_notify('odds_update', :p)"), {"p": payload}
        )
    except Exception:
        pass


class OddsUpsertResult(Enum):
    """Result of an odds upsert attempt."""

    PERSISTED = "persisted"
    SKIPPED_NO_MATCH = "skipped_no_match"
    SKIPPED_LIVE = "skipped_live"


from ..odds.fairbet import upsert_fairbet_odds  # noqa: E402
from .games import find_or_create_game  # noqa: E402


def _execute_odds_upsert(
    session: Session,
    game_id: int,
    snapshot: NormalizedOddsSnapshot,
    side_value: str | None,
) -> None:
    """Insert opening line (first-seen, never overwritten) then upsert closing line.

    Two rows per bet are maintained via the ``is_closing_line`` flag:
    * ``is_closing_line=False`` — opening line, written once via ``DO NOTHING``.
    * ``is_closing_line=True``  — closing line, continuously updated via ``DO UPDATE``.
    """
    common_values: dict = dict(
        game_id=game_id,
        book=snapshot.book,
        market_type=snapshot.market_type,
        side=side_value,
        line=snapshot.line,
        price=snapshot.price,
        observed_at=snapshot.observed_at,
        source_key=snapshot.source_key,
        raw_payload=snapshot.raw_payload,
        market_category=snapshot.market_category,
        player_name=snapshot.player_name,
        description=snapshot.description,
    )

    # --- Opening line: first-seen value, never overwritten ---
    opening_stmt = (
        insert(db_models.SportsGameOdds)
        .values(**common_values, is_closing_line=False)
        .on_conflict_do_nothing(
            index_elements=["game_id", "book", "market_type", "side", "is_closing_line"],
        )
    )
    session.execute(opening_stmt)

    # --- Closing line: continuously updated (existing behaviour) ---
    closing_stmt = (
        insert(db_models.SportsGameOdds)
        .values(**common_values, is_closing_line=True)
        .on_conflict_do_update(
            index_elements=["game_id", "book", "market_type", "side", "is_closing_line"],
            set_={
                "line": snapshot.line,
                "price": snapshot.price,
                "observed_at": snapshot.observed_at,
                "source_key": snapshot.source_key,
                "raw_payload": snapshot.raw_payload,
                "market_category": snapshot.market_category,
                "player_name": snapshot.player_name,
                "description": snapshot.description,
                "updated_at": now_utc(),
            },
        )
    )
    session.execute(closing_stmt)


def upsert_odds(session: Session, snapshot: NormalizedOddsSnapshot) -> OddsUpsertResult:
    """Upsert odds snapshot, matching to an existing game or creating one.

    Uses ``find_or_create_game()`` for all game resolution — the same
    function used by boxscores, PBP, schedule feeds, and live feeds.

    For historical dates, ``create_if_missing=False`` so we never create
    stub games for past matchups (the game should already exist from
    boxscore ingestion).  For today/future, stubs are created so odds
    are captured before the game appears in schedule feeds.

    Returns:
        PERSISTED — odds were written to the database.
        SKIPPED_NO_MATCH — no matching game found.
        SKIPPED_LIVE — game is live; write skipped to preserve closing lines.
    """
    game_date_only = to_et_date(snapshot.game_date)
    today = date.today()
    is_historical = game_date_only < today

    # Guard: reject far-future games (>48h out)
    max_future = today + timedelta(days=2)
    if game_date_only > max_future:
        return OddsUpsertResult.SKIPPED_NO_MATCH

    # Build external_ids from snapshot
    external_ids = {}
    if snapshot.source_key:
        external_ids["odds_api_event_id"] = snapshot.source_key
    if snapshot.event_id:
        external_ids["odds_api_event_id"] = snapshot.event_id

    game_id, created = find_or_create_game(
        session,
        league_code=snapshot.league_code,
        game_date=snapshot.game_date,
        home_team=snapshot.home_team,
        away_team=snapshot.away_team,
        external_ids=external_ids or None,
        create_if_missing=not is_historical,  # Never stub historical games
    )

    if game_id is None:
        return OddsUpsertResult.SKIPPED_NO_MATCH

    game = session.get(db_models.SportsGame, game_id)

    # Skip live games to preserve pre-game closing lines
    if game and game.status == db_models.GameStatus.live.value:
        return OddsUpsertResult.SKIPPED_LIVE

    # Backfill typed column from JSONB if not yet set
    if game is not None and not game.odds_api_event_id:
        odds_id = external_ids.get("odds_api_event_id")
        if odds_id:
            game.odds_api_event_id = str(odds_id)

    # Write odds records
    side_value = snapshot.side if snapshot.side else None
    _execute_odds_upsert(session, game_id, snapshot, side_value)

    # FairBet work table
    if game is not None:
        upsert_fairbet_odds(session, game_id, game.status, snapshot)
        game.last_odds_at = now_utc()
        _notify_odds_update(session, game_id)

    return OddsUpsertResult.PERSISTED
