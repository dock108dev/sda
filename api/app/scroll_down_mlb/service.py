"""Public surface for Scroll Down MLB.

The router calls into here. Implementation is split across three private
modules to keep this file focused on the async router entrypoints:

  * `_dto`      — built-deck → spoiler-safe DTO + final-score-leak scan
  * `_pipeline` — `build_deck_from_upstream` (full builder pipeline) +
                  policy splitter + `_source_hash` for live/official
                  deck-version stamping
  * `service`   — async router entrypoints (`get_recent_games`,
                  `get_game_deck`, `get_game_reveal`); re-exports the
                  pipeline/DTO callables consumed by tests

Pipeline order is documented in `_pipeline.build_deck_from_upstream`.

`get_game_deck` / `get_game_reveal` / `get_recent_games` return None when
the upstream payload is missing; the router maps that to 404/409 per its
contract.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.scroll_down_mlb import ScrollDownMlbDeck
from app.db.sports import GameStatus, SportsGame, SportsLeague

from . import persistence
from ._dto import built_deck_to_dto, scan_response_for_final_score_leaks
from ._pipeline import (
    apply_validation_policy,
    build_deck_from_upstream,
    generate_final_deck,
    generate_live_deck,
)
from .data_source import load_game_payload
from .schemas import (
    GenerationPolicy,
    ScrollDownMlbDeckResponse,
    ScrollDownMlbRecentGame,
    ScrollDownMlbRevealResponse,
    TeamSummary,
)

logger = logging.getLogger(__name__)

__all__ = [
    "apply_validation_policy",
    "build_deck_from_upstream",
    "built_deck_to_dto",
    "generate_final_deck",
    "generate_live_deck",
    "get_game_deck",
    "get_game_reveal",
    "get_recent_games",
    "scan_response_for_final_score_leaks",
]


# Window used by /games/recent. 48h covers yesterday's MLB slate plus
# anything early today, so the consumer home grid never looks empty
# overnight on the East Coast.
_RECENT_WINDOW_HOURS = 48


async def get_recent_games(
    session: AsyncSession, *, now: datetime | None = None
) -> list[ScrollDownMlbRecentGame]:
    """Spoiler-safe recent-games feed.

    Returns MLB games whose first pitch falls within the last
    `_RECENT_WINDOW_HOURS`, capped at `now` so future-scheduled games
    never appear (this is a catch-up product — there is nothing to
    reconstruct for a game that hasn't started). Joined against the
    deck table for `hasDeck` / `deckVersion` so the home grid can show
    whether catch-up is ready without a second query.
    """
    end_cap = now or datetime.now(UTC)
    cutoff = end_cap - timedelta(hours=_RECENT_WINDOW_HOURS)

    # Subquery: latest deck row per game.
    deck_subq = (
        select(
            ScrollDownMlbDeck.game_id.label("game_id"),
            func.max(ScrollDownMlbDeck.generated_at).label("latest_generated"),
        )
        .group_by(ScrollDownMlbDeck.game_id)
        .subquery()
    )

    stmt = (
        select(SportsGame, ScrollDownMlbDeck)
        .join(SportsLeague, SportsLeague.id == SportsGame.league_id)
        .options(
            selectinload(SportsGame.home_team),
            selectinload(SportsGame.away_team),
        )
        .join(
            deck_subq,
            deck_subq.c.game_id == SportsGame.id,
            isouter=True,
        )
        .join(
            ScrollDownMlbDeck,
            and_(
                ScrollDownMlbDeck.game_id == deck_subq.c.game_id,
                ScrollDownMlbDeck.generated_at == deck_subq.c.latest_generated,
            ),
            isouter=True,
        )
        .where(
            func.lower(SportsLeague.code) == "mlb",
            SportsGame.game_date >= cutoff,
            SportsGame.game_date <= end_cap,
        )
        .order_by(desc(SportsGame.game_date))
        .limit(50)
    )

    result = await session.execute(stmt)
    rows = result.all()

    games: list[ScrollDownMlbRecentGame] = []
    for game, deck_row in rows:
        is_final = GameStatus.is_final_or_post_final_status(game.status)
        is_pregame = (game.status or "").lower() in ("scheduled", "pregame")
        home = game.home_team
        away = game.away_team
        games.append(
            ScrollDownMlbRecentGame(
                game_id=str(game.id),
                game_date=(game.local_game_date if game.local_game_date else None),
                status=game.status,
                status_type=(
                    "final" if is_final else "pregame" if is_pregame else "live"
                ),
                away_team=TeamSummary(
                    id=str(away.id) if away else "away",
                    abbreviation=(away.abbreviation if away else "AWY") or "AWY",
                    display_name=away.name if away else "Away",
                    color_light=(away.color_light_hex if away else None),
                    color_dark=(away.color_dark_hex if away else None),
                ),
                home_team=TeamSummary(
                    id=str(home.id) if home else "home",
                    abbreviation=(home.abbreviation if home else "HME") or "HME",
                    display_name=home.name if home else "Home",
                    color_light=(home.color_light_hex if home else None),
                    color_dark=(home.color_dark_hex if home else None),
                ),
                venue_name=game.venue,
                start_time=game.game_date,
                has_deck=deck_row is not None,
                deck_version=deck_row.deck_version if deck_row is not None else None,
                is_final=is_final,
            )
        )
    return games


async def get_game_deck(
    session: AsyncSession, game_id: str
) -> ScrollDownMlbDeckResponse | None:
    """Return the (live or official) deck for `game_id`.

    Behavior:

      - Game not found / not MLB                  → None (router → 404)
      - Game scheduled / pregame                  → None (router → 404 or
        409 depending on the route's contract; current router → 404)
      - Game live: build fresh from current data, return live deck
      - Game final: serve persisted official deck if present; otherwise
        build, validate, persist (freeze), return.
    """
    try:
        gid = int(game_id)
    except (TypeError, ValueError):
        return None

    payload = await load_game_payload(session, gid)
    if payload is None:
        logger.info(
            "scroll_down_mlb.deck.not_found", extra={"game_id": gid}
        )
        return None

    game = payload.get("game") or {}
    is_final = bool(game.get("isFinal"))
    is_pregame = bool(game.get("isPregame"))

    if is_pregame:
        logger.info(
            "scroll_down_mlb.deck.pregame", extra={"game_id": gid}
        )
        return None

    if is_final:
        existing = await persistence.fetch_official_deck(session, gid)
        if existing is not None:
            logger.info(
                "scroll_down_mlb.deck.served_official",
                extra={
                    "game_id": gid,
                    "deck_version": existing.deck_version,
                },
            )
            return existing

    started = time.monotonic()
    policy = GenerationPolicy.official if is_final else GenerationPolicy.live
    outcome = build_deck_from_upstream(payload, policy=policy)
    duration_ms = int((time.monotonic() - started) * 1000)

    if outcome.blocked:
        logger.warning(
            "scroll_down_mlb.deck.validation_blocked",
            extra={
                "game_id": gid,
                "policy": policy.value,
                "errors": [e.code for e in outcome.errors],
                "duration_ms": duration_ms,
            },
        )
        # Fail closed on official; fail-open on live (live decks already
        # have errors downgraded to warnings by apply_validation_policy).
        return None

    deck = outcome.deck
    if deck is None:
        return None

    if is_final:
        await persistence.upsert_deck(
            session,
            game_id=gid,
            deck=deck,
            warnings=outcome.warnings,
            errors=outcome.errors,
            generator_label="phase5-py-v1",
        )
        await session.commit()
        logger.info(
            "scroll_down_mlb.deck.frozen_official",
            extra={
                "game_id": gid,
                "deck_version": deck.deck_version,
                "card_count": len(deck.cards),
                "duration_ms": duration_ms,
            },
        )
    else:
        logger.info(
            "scroll_down_mlb.deck.built_live",
            extra={
                "game_id": gid,
                "deck_version": deck.deck_version,
                "card_count": len(deck.cards),
                "duration_ms": duration_ms,
            },
        )
    return deck


async def get_game_reveal(
    session: AsyncSession, game_id: str
) -> ScrollDownMlbRevealResponse | None:
    """Return the reveal payload for a final game.

    Live or scheduled games return None (router → 409). Final games
    return finalScore + winnerTeamId + a deterministic recap fallback
    if no recap source is wired up.
    """
    try:
        gid = int(game_id)
    except (TypeError, ValueError):
        return None

    game_row = await session.execute(
        select(SportsGame)
        .options(
            selectinload(SportsGame.home_team),
            selectinload(SportsGame.away_team),
            selectinload(SportsGame.league),
        )
        .where(SportsGame.id == gid)
    )
    game: SportsGame | None = game_row.scalar_one_or_none()
    if game is None or (game.league.code or "").lower() != "mlb":
        return None
    if not GameStatus.is_final_or_post_final_status(game.status):
        return None
    if game.home_score is None or game.away_score is None:
        # Final-status game without a score on file — refuse to fabricate.
        logger.warning(
            "scroll_down_mlb.reveal.missing_score", extra={"game_id": gid}
        )
        return None

    home = game.home_team
    away = game.away_team
    home_won = game.home_score > game.away_score
    is_tie = game.home_score == game.away_score
    winner_team_id: str | None = None
    if not is_tie:
        winner_team_id = str(home.id if home_won else away.id) if (
            home and away
        ) else None

    # Deterministic recap fallback. Phase 5 deliberately avoids an LLM
    # dependency; the gameflow source can be wired in a follow-up.
    if is_tie:
        summary = (
            f"{away.name if away else 'Away'} and "
            f"{home.name if home else 'Home'} ended in a tie, "
            f"{game.away_score}–{game.home_score}."
        )
    else:
        winner_name = (home.name if home_won else away.name) if home and away else "The winner"
        loser_name = (away.name if home_won else home.name) if home and away else "The loser"
        summary = (
            f"{winner_name} beat {loser_name}, "
            f"{max(game.home_score, game.away_score)}–"
            f"{min(game.home_score, game.away_score)}."
        )

    return ScrollDownMlbRevealResponse(
        game_id=str(gid),
        final_score={"home": game.home_score, "away": game.away_score},
        winner_team_id=winner_team_id,
        summary=summary,
        key_stats=[],
        game_flow=[],
        generated_at=datetime.now(UTC),
    )
