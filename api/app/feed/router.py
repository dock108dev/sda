"""HTTP routes for the cross-sport narrative card feed."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.db import AsyncSession, get_db

from .debug_schemas import CardGenerationDebugResponse
from .schemas import CardFeedResponse, SpoilerPolicy
from .service import get_game_card_feed, get_game_card_generation_debug

router = APIRouter(prefix="/feed", tags=["v1", "feed"])


@router.get(
    "/games/{game_id}/cards",
    response_model=CardFeedResponse,
    response_model_by_alias=True,
    response_model_exclude_none=True,
    summary="Get normalized narrative cards for a game",
)
async def get_game_cards(
    game_id: int,
    spoiler_policy: SpoilerPolicy = Query(SpoilerPolicy.pre_reveal, alias="spoilerPolicy"),
    through_play_index: int | None = Query(
        None,
        ge=0,
        alias="throughPlayIndex",
        description="Only return cards earned at or before this play index.",
    ),
    session: AsyncSession = Depends(get_db),
) -> CardFeedResponse:
    """Return renderable cross-sport narrative cards for one game."""
    return await get_game_card_feed(
        session,
        game_id,
        spoiler_policy,
        through_play_index=through_play_index,
    )


@router.get(
    "/games/{game_id}/cards/debug",
    response_model=CardGenerationDebugResponse,
    response_model_by_alias=True,
    summary="Debug normalized narrative card generation",
)
async def get_game_cards_debug(
    game_id: int,
    spoiler_policy: SpoilerPolicy = Query(SpoilerPolicy.pre_reveal, alias="spoilerPolicy"),
    through_play_index: int | None = Query(None, ge=0, alias="throughPlayIndex"),
    include_feed: bool = Query(True, alias="includeFeed"),
    session: AsyncSession = Depends(get_db),
) -> CardGenerationDebugResponse:
    """Return card generation metadata and validation findings for inspection."""
    return await get_game_card_generation_debug(
        session,
        game_id,
        spoiler_policy,
        through_play_index=through_play_index,
        include_feed=include_feed,
    )
