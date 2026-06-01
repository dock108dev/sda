"""Materialized normalized card-feed artifacts.

The feed builder remains the SSOT for card semantics. This module moves that
work out of the hot request path by persisting the rendered contract shape and
refreshing it when source play data or the card-feed contract changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, selectinload

from app.db.flow import SportsGameCardFeedArtifact
from app.db.sports import SportsGame, SportsGamePlay

from .schemas import CARD_FEED_CONTRACT_VERSION, CardFeedResponse, SpoilerPolicy
from .service import (
    _build_card_feed_result,
    _league_code,
    _plays_through,
    _source_hash_for_card_feed,
)

CARD_FEED_GENERATOR_LABEL = f"card-feed-v{CARD_FEED_CONTRACT_VERSION}"


@dataclass(frozen=True)
class CardFeedMaterializationResult:
    game_id: int
    contract_version: int
    spoiler_policy: str
    status: str
    card_count: int
    generated: bool
    source_hash: str


@dataclass(frozen=True)
class CardFeedRefreshSummary:
    scanned_games: int
    eligible_games: int
    generated: int
    skipped_current: int
    failed: int
    errors: tuple[str, ...]


def artifact_to_response(
    artifact: SportsGameCardFeedArtifact,
    *,
    is_stale: bool = False,
) -> CardFeedResponse:
    """Hydrate the public card-feed response from a persisted artifact."""
    payload: dict[str, Any] = {
        "contractVersion": artifact.contract_version,
        "game": artifact.game_json,
        "spoilerPolicy": artifact.spoiler_policy,
        "generation": {
            "status": artifact.generation_status,
            "cardCount": artifact.card_count,
            "lastPlayIndex": artifact.last_play_index,
            "generatedAt": artifact.generated_at,
            "isStale": is_stale,
            "validationIssues": artifact.validation_issues_json,
        },
        "reveal": artifact.reveal_json,
        "sections": artifact.sections_json,
        "cards": artifact.cards_json,
    }
    return CardFeedResponse.model_validate(payload)


async def get_materialized_card_feed(
    session: AsyncSession,
    game_id: int,
    spoiler_policy: SpoilerPolicy,
) -> CardFeedResponse:
    """Return the persisted card feed without generating on the request path."""
    artifact = await _load_artifact_async(session, game_id, spoiler_policy)
    if artifact is None:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Card feed has not been materialized for this game.",
        )
    game = await _load_game_async(session, game_id)
    return artifact_to_response(
        artifact,
        is_stale=artifact.source_hash != _source_hash(game),
    )


async def get_or_materialize_card_feed(
    session: AsyncSession,
    game_id: int,
    spoiler_policy: SpoilerPolicy,
    *,
    force: bool = False,
) -> CardFeedResponse:
    """Return current materialized feed, generating it only when stale/missing."""
    game = await _load_game_async(session, game_id)
    source_hash = _source_hash(game)
    artifact = await _load_artifact_async(session, game_id, spoiler_policy)
    if artifact and not force and artifact.source_hash == source_hash:
        return artifact_to_response(artifact)
    artifact = await _materialize_loaded_game_async(
        session,
        game,
        spoiler_policy,
        source_hash=source_hash,
    )
    return artifact_to_response(artifact)


async def materialize_card_feed(
    session: AsyncSession,
    game_id: int,
    spoiler_policy: SpoilerPolicy = SpoilerPolicy.pre_reveal,
    *,
    force: bool = False,
) -> CardFeedMaterializationResult:
    """Materialize one game's current card feed."""
    game = await _load_game_async(session, game_id)
    source_hash = _source_hash(game)
    artifact = await _load_artifact_async(session, game_id, spoiler_policy)
    if artifact and not force and artifact.source_hash == source_hash:
        return _result_from_artifact(artifact, generated=False, source_hash=source_hash)
    artifact = await _materialize_loaded_game_async(
        session,
        game,
        spoiler_policy,
        source_hash=source_hash,
    )
    return _result_from_artifact(artifact, generated=True, source_hash=source_hash)


async def refresh_card_feeds_for_window(
    session: AsyncSession,
    *,
    lookback_hours: int = 72,
    lookahead_hours: int = 72,
    spoiler_policy: SpoilerPolicy = SpoilerPolicy.pre_reveal,
    force: bool = False,
    now: datetime | None = None,
) -> CardFeedRefreshSummary:
    """Materialize card feeds for all PBP games in a deploy/scheduler window."""
    anchor = now or datetime.now(UTC)
    start = anchor - timedelta(hours=lookback_hours)
    end = anchor + timedelta(hours=lookahead_hours)
    result = await session.execute(
        select(SportsGame.id)
        .where(SportsGame.game_date >= start)
        .where(SportsGame.game_date <= end)
        .where(
            exists().where(SportsGamePlay.game_id == SportsGame.id)
        )
        .order_by(SportsGame.game_date.asc(), SportsGame.id.asc())
    )
    game_ids = [int(game_id) for game_id in result.scalars().all()]
    generated = 0
    skipped = 0
    failed = 0
    errors: list[str] = []
    for game_id in game_ids:
        try:
            item = await materialize_card_feed(
                session,
                game_id,
                spoiler_policy,
                force=force,
            )
            generated += int(item.generated)
            skipped += int(not item.generated)
        except Exception as exc:  # pragma: no cover - exercised via CLI/deploy
            failed += 1
            errors.append(f"{game_id}: {type(exc).__name__}: {exc}")
    return CardFeedRefreshSummary(
        scanned_games=len(game_ids),
        eligible_games=len(game_ids),
        generated=generated,
        skipped_current=skipped,
        failed=failed,
        errors=tuple(errors),
    )


def materialize_recent_card_feeds_sync(
    session: Session,
    *,
    lookback_hours: int = 96,
    lookahead_hours: int = 48,
    spoiler_policy: SpoilerPolicy = SpoilerPolicy.pre_reveal,
    force: bool = False,
    now: datetime | None = None,
) -> CardFeedRefreshSummary:
    """Sync variant used by the scraper worker after PBP ingestion."""
    anchor = now or datetime.now(UTC)
    start = anchor - timedelta(hours=lookback_hours)
    end = anchor + timedelta(hours=lookahead_hours)
    game_ids = [
        int(game_id)
        for (game_id,) in (
            session.query(SportsGame.id)
            .filter(SportsGame.game_date >= start)
            .filter(SportsGame.game_date <= end)
            .filter(exists().where(SportsGamePlay.game_id == SportsGame.id))
            .order_by(SportsGame.game_date.asc(), SportsGame.id.asc())
            .all()
        )
    ]
    generated = 0
    skipped = 0
    failed = 0
    errors: list[str] = []
    for game_id in game_ids:
        try:
            item = materialize_card_feed_sync(
                session,
                game_id,
                spoiler_policy,
                force=force,
            )
            generated += int(item.generated)
            skipped += int(not item.generated)
        except Exception as exc:  # pragma: no cover - operational guard
            failed += 1
            errors.append(f"{game_id}: {type(exc).__name__}: {exc}")
    return CardFeedRefreshSummary(
        scanned_games=len(game_ids),
        eligible_games=len(game_ids),
        generated=generated,
        skipped_current=skipped,
        failed=failed,
        errors=tuple(errors),
    )


def materialize_card_feed_sync(
    session: Session,
    game_id: int,
    spoiler_policy: SpoilerPolicy = SpoilerPolicy.pre_reveal,
    *,
    force: bool = False,
) -> CardFeedMaterializationResult:
    """Sync materialization for Celery scraper tasks."""
    game = _load_game_sync(session, game_id)
    source_hash = _source_hash(game)
    artifact = _load_artifact_sync(session, game_id, spoiler_policy)
    if artifact and not force and artifact.source_hash == source_hash:
        return _result_from_artifact(artifact, generated=False, source_hash=source_hash)
    artifact = _materialize_loaded_game_sync(
        session,
        game,
        spoiler_policy,
        source_hash=source_hash,
    )
    return _result_from_artifact(artifact, generated=True, source_hash=source_hash)


async def _load_game_async(session: AsyncSession, game_id: int) -> SportsGame:
    result = await session.execute(_game_select().where(SportsGame.id == game_id))
    game = result.scalar_one_or_none()
    if game is None:
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Game not found")
    return game


def _load_game_sync(session: Session, game_id: int) -> SportsGame:
    game = session.execute(_game_select().where(SportsGame.id == game_id)).scalar_one_or_none()
    if game is None:
        raise ValueError(f"Game not found: {game_id}")
    return game


def _game_select():
    return select(SportsGame).options(
        selectinload(SportsGame.league),
        selectinload(SportsGame.home_team),
        selectinload(SportsGame.away_team),
        selectinload(SportsGame.plays).selectinload(SportsGamePlay.team),
    )


async def _load_artifact_async(
    session: AsyncSession,
    game_id: int,
    spoiler_policy: SpoilerPolicy,
) -> SportsGameCardFeedArtifact | None:
    result = await session.execute(_artifact_select(game_id, spoiler_policy))
    return result.scalar_one_or_none()


def _load_artifact_sync(
    session: Session,
    game_id: int,
    spoiler_policy: SpoilerPolicy,
) -> SportsGameCardFeedArtifact | None:
    return session.execute(_artifact_select(game_id, spoiler_policy)).scalar_one_or_none()


def _artifact_select(game_id: int, spoiler_policy: SpoilerPolicy):
    return select(SportsGameCardFeedArtifact).where(
        SportsGameCardFeedArtifact.game_id == game_id,
        SportsGameCardFeedArtifact.contract_version == CARD_FEED_CONTRACT_VERSION,
        SportsGameCardFeedArtifact.spoiler_policy == spoiler_policy.value,
    )


async def _materialize_loaded_game_async(
    session: AsyncSession,
    game: SportsGame,
    spoiler_policy: SpoilerPolicy,
    *,
    source_hash: str,
) -> SportsGameCardFeedArtifact:
    artifact = await _load_artifact_async(session, game.id, spoiler_policy)
    if artifact is None:
        artifact = SportsGameCardFeedArtifact(
            game_id=game.id,
            contract_version=CARD_FEED_CONTRACT_VERSION,
            spoiler_policy=spoiler_policy.value,
            generation_status="generation_pending",
            source_hash=source_hash,
            generated_at=datetime.now(UTC),
            generator_label=CARD_FEED_GENERATOR_LABEL,
        )
        session.add(artifact)
    _apply_response_to_artifact(artifact, _build_response(game, spoiler_policy), source_hash)
    await session.flush()
    return artifact


def _materialize_loaded_game_sync(
    session: Session,
    game: SportsGame,
    spoiler_policy: SpoilerPolicy,
    *,
    source_hash: str,
) -> SportsGameCardFeedArtifact:
    artifact = _load_artifact_sync(session, game.id, spoiler_policy)
    if artifact is None:
        artifact = SportsGameCardFeedArtifact(
            game_id=game.id,
            contract_version=CARD_FEED_CONTRACT_VERSION,
            spoiler_policy=spoiler_policy.value,
            generation_status="generation_pending",
            source_hash=source_hash,
            generated_at=datetime.now(UTC),
            generator_label=CARD_FEED_GENERATOR_LABEL,
        )
        session.add(artifact)
    _apply_response_to_artifact(artifact, _build_response(game, spoiler_policy), source_hash)
    session.flush()
    return artifact


def _build_response(game: SportsGame, spoiler_policy: SpoilerPolicy) -> CardFeedResponse:
    return _build_card_feed_result(game, spoiler_policy).response


def _source_hash(game: SportsGame) -> str:
    plays = sorted(list(game.plays or []), key=lambda play: play.play_index)
    return _source_hash_for_card_feed(
        game,
        _league_code(game),
        _plays_through(plays, None),
    )


def _apply_response_to_artifact(
    artifact: SportsGameCardFeedArtifact,
    response: CardFeedResponse,
    source_hash: str,
) -> None:
    payload = response.model_dump(by_alias=True, mode="json", exclude_none=True)
    generation = payload["generation"]
    artifact.contract_version = CARD_FEED_CONTRACT_VERSION
    artifact.spoiler_policy = payload["spoilerPolicy"]
    artifact.generation_status = generation["status"]
    artifact.source_hash = source_hash
    artifact.card_count = int(generation.get("cardCount") or 0)
    artifact.last_play_index = generation.get("lastPlayIndex")
    artifact.game_json = payload["game"]
    artifact.reveal_json = payload["reveal"]
    artifact.sections_json = payload.get("sections", [])
    artifact.cards_json = payload.get("cards", [])
    artifact.validation_issues_json = generation.get("validationIssues", [])
    artifact.generated_at = datetime.now(UTC)
    artifact.generator_label = CARD_FEED_GENERATOR_LABEL


def _result_from_artifact(
    artifact: SportsGameCardFeedArtifact,
    *,
    generated: bool,
    source_hash: str,
) -> CardFeedMaterializationResult:
    return CardFeedMaterializationResult(
        game_id=artifact.game_id,
        contract_version=artifact.contract_version,
        spoiler_policy=artifact.spoiler_policy,
        status=artifact.generation_status,
        card_count=artifact.card_count,
        generated=generated,
        source_hash=source_hash,
    )
