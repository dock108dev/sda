"""Explicit precompute flow for persisted Scroll Down MLB deck artifacts."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.sports import GameStatus, SportsGame

from . import persistence
from ._pipeline import _source_hash, build_deck_from_upstream
from .data_source import load_game_payload
from .schemas import (
    DeckCardType,
    DeckGenerationStatus,
    GenerationPolicy,
    ScrollDownMlbDeckCard,
    ScrollDownMlbDeckResponse,
    TeamSummary,
)

logger = logging.getLogger(__name__)

_LOCK_NAMESPACE = 0x5D0A
_GENERATOR_LABEL = "scroll-down-mlb-precompute-v1"


@dataclass(frozen=True)
class DeckPrecomputeResult:
    """Outcome of an explicit deck precompute attempt."""

    game_id: int
    status: str
    deck_version: str | None = None
    source_hash: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class GameDeckMetadata:
    """Spoiler-safe game metadata needed by the deck cache layer."""

    game_id: int
    status: str | None
    is_final: bool
    is_pregame: bool
    home_team: TeamSummary | None
    away_team: TeamSummary | None
    first_pitch: datetime | None
    venue: str | None


def _team_summary(team: Any | None, fallback_id: str, fallback_abbr: str) -> TeamSummary:
    """Build spoiler-safe team identity from a `SportsTeam` row."""
    if team is None:
        return TeamSummary(
            id=fallback_id,
            abbreviation=fallback_abbr,
            display_name=fallback_abbr,
        )
    return TeamSummary(
        id=str(team.id),
        abbreviation=team.abbreviation or fallback_abbr,
        display_name=team.name,
        color_light=team.color_light_hex,
        color_dark=team.color_dark_hex,
    )


async def load_game_deck_metadata(
    session: AsyncSession, game_id: int
) -> GameDeckMetadata | None:
    """Load spoiler-safe metadata for a Scroll Down MLB deck."""
    stmt = (
        select(SportsGame)
        .options(
            selectinload(SportsGame.home_team),
            selectinload(SportsGame.away_team),
            selectinload(SportsGame.league),
        )
        .where(SportsGame.id == game_id)
    )
    result = await session.execute(stmt)
    game: SportsGame | None = result.scalar_one_or_none()
    if game is None or (game.league.code or "").lower() != "mlb":
        return None

    status_str = game.status
    return GameDeckMetadata(
        game_id=game_id,
        status=status_str,
        is_final=GameStatus.is_final_or_post_final_status(status_str),
        is_pregame=(status_str or "").lower() in ("scheduled", "pregame"),
        home_team=_team_summary(game.home_team, "home", "HME"),
        away_team=_team_summary(game.away_team, "away", "AWY"),
        first_pitch=game.game_date,
        venue=game.venue,
    )


def fallback_deck(
    metadata: GameDeckMetadata,
    *,
    status: DeckGenerationStatus,
    source_hash: str | None = None,
    message: str | None = None,
) -> ScrollDownMlbDeckResponse:
    """Build a deterministic spoiler-safe fallback deck."""
    version_seed = source_hash or f"{metadata.game_id}:{metadata.status or ''}"
    deck_version = f"{status.value}-{version_seed}"[:64]
    if status is DeckGenerationStatus.blocked:
        title = "Catch-up unavailable"
        description = "The catch-up deck needs review before it can be shown."
    elif status is DeckGenerationStatus.degraded:
        title = "Catch-up limited"
        description = "The catch-up deck is using a safe fallback."
    else:
        title = "Catch-up pending"
        description = "The catch-up deck is being prepared."

    return ScrollDownMlbDeckResponse(
        game_id=str(metadata.game_id),
        deck_version=deck_version,
        generated_at=datetime.now(UTC),
        is_final=metadata.is_final,
        generation_status=status,
        generation_message=message,
        home_team=metadata.home_team,
        away_team=metadata.away_team,
        first_pitch=metadata.first_pitch,
        venue=metadata.venue,
        cards=[
            ScrollDownMlbDeckCard(
                id=f"{metadata.game_id}-{status.value}",
                type=DeckCardType.scene,
                sort_order=0,
                title=title,
                description=description,
            )
        ],
    )


async def try_advisory_lock(session: AsyncSession, game_id: int) -> bool:
    """Acquire a transaction-scoped DB lock for one game generation."""
    result = await session.execute(
        select(func.pg_try_advisory_xact_lock(_LOCK_NAMESPACE, game_id))
    )
    return bool(result.scalar_one())


async def precompute_game_deck(
    session: AsyncSession,
    game_id: int,
    *,
    force: bool = False,
) -> DeckPrecomputeResult:
    """Build and persist the current deck artifact for one MLB game."""
    metadata = await load_game_deck_metadata(session, game_id)
    if metadata is None:
        return DeckPrecomputeResult(game_id=game_id, status="not_found")
    if metadata.is_pregame:
        return DeckPrecomputeResult(game_id=game_id, status="skipped_pregame")
    if not await try_advisory_lock(session, game_id):
        return DeckPrecomputeResult(game_id=game_id, status="locked")

    payload = await load_game_payload(session, game_id)
    if payload is None:
        return await _persist_fallback(
            session,
            game_id=game_id,
            metadata=metadata,
            status=DeckGenerationStatus.degraded,
            message="Source payload is unavailable.",
        )

    source_hash = _source_hash(payload)
    latest = await persistence.fetch_latest_deck_row(session, game_id)
    if latest is not None and latest.source_hash == source_hash and not force:
        return DeckPrecomputeResult(
            game_id=game_id,
            status="unchanged",
            deck_version=latest.deck_version,
            source_hash=source_hash,
        )

    plays = payload.get("plays") or []
    if not plays:
        fallback_status = (
            DeckGenerationStatus.degraded
            if metadata.is_final
            else DeckGenerationStatus.pending
        )
        return await _persist_fallback(
            session,
            game_id=game_id,
            metadata=metadata,
            status=fallback_status,
            source_hash=source_hash,
            message="Play-by-play data is not available yet.",
        )

    started = time.monotonic()
    policy = GenerationPolicy.official if metadata.is_final else GenerationPolicy.live
    try:
        outcome = build_deck_from_upstream(payload, policy=policy)
    except Exception as exc:
        logger.exception(
            "scroll_down_mlb.deck.precompute_failed",
            extra={"game_id": game_id, "policy": policy.value},
        )
        result = await _persist_fallback(
            session,
            game_id=game_id,
            metadata=metadata,
            status=DeckGenerationStatus.degraded,
            source_hash=source_hash,
            message="Deck generation failed and a safe fallback is available.",
        )
        return DeckPrecomputeResult(
            game_id=game_id,
            status=result.status,
            deck_version=result.deck_version,
            source_hash=source_hash,
            error=exc.__class__.__name__,
        )

    duration_ms = int((time.monotonic() - started) * 1000)
    if outcome.blocked:
        deck = fallback_deck(
            metadata,
            status=DeckGenerationStatus.blocked,
            source_hash=source_hash,
            message="Deck generation is blocked by validation.",
        )
        await persistence.upsert_deck(
            session,
            game_id=game_id,
            deck=deck,
            errors=outcome.errors,
            source_hash=source_hash,
            generator_label=_GENERATOR_LABEL,
        )
        await session.commit()
        logger.warning(
            "scroll_down_mlb.deck.validation_blocked",
            extra={
                "game_id": game_id,
                "policy": policy.value,
                "errors": [e.code for e in outcome.errors],
                "duration_ms": duration_ms,
            },
        )
        return DeckPrecomputeResult(
            game_id=game_id,
            status=deck.generation_status.value,
            deck_version=deck.deck_version,
            source_hash=source_hash,
        )

    deck = outcome.deck
    if deck is None:
        deck = fallback_deck(
            metadata,
            status=DeckGenerationStatus.degraded,
            source_hash=source_hash,
            message="Deck generation returned no artifact.",
        )
    else:
        deck.generation_status = DeckGenerationStatus.ready

    await persistence.upsert_deck(
        session,
        game_id=game_id,
        deck=deck,
        warnings=outcome.warnings,
        errors=outcome.errors,
        planner_report=(
            deck.planner_report.model_dump(mode="json", by_alias=True)
            if deck.planner_report
            else None
        ),
        source_hash=source_hash,
        generator_label=_GENERATOR_LABEL,
    )
    await session.commit()
    logger.info(
        "scroll_down_mlb.deck.precomputed",
        extra={
            "game_id": game_id,
            "deck_version": deck.deck_version,
            "card_count": len(deck.cards),
            "duration_ms": duration_ms,
        },
    )
    return DeckPrecomputeResult(
        game_id=game_id,
        status=deck.generation_status.value,
        deck_version=deck.deck_version,
        source_hash=source_hash,
    )


async def _persist_fallback(
    session: AsyncSession,
    *,
    game_id: int,
    metadata: GameDeckMetadata,
    status: DeckGenerationStatus,
    source_hash: str | None = None,
    message: str | None = None,
) -> DeckPrecomputeResult:
    deck = fallback_deck(
        metadata,
        status=status,
        source_hash=source_hash,
        message=message,
    )
    await persistence.upsert_deck(
        session,
        game_id=game_id,
        deck=deck,
        source_hash=source_hash,
        generator_label=_GENERATOR_LABEL,
    )
    await session.commit()
    return DeckPrecomputeResult(
        game_id=game_id,
        status=deck.generation_status.value,
        deck_version=deck.deck_version,
        source_hash=source_hash,
    )
