"""Admin operations for materialized Scroll Down card feeds."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.db import AsyncSession, get_db

router = APIRouter(prefix="/card-feeds", tags=["card-feeds"])


class CardFeedMaterializationResponse(BaseModel):
    game_id: int = Field(..., alias="gameId")
    contract_version: int = Field(..., alias="contractVersion")
    feed_key: str = Field(..., alias="feedKey")
    status: str
    card_count: int = Field(..., alias="cardCount")
    generated: bool
    source_hash: str = Field(..., alias="sourceHash")


class CardFeedRefreshResponse(BaseModel):
    scanned_games: int = Field(..., alias="scannedGames")
    eligible_games: int = Field(..., alias="eligibleGames")
    generated: int
    skipped_current: int = Field(..., alias="skippedCurrent")
    failed: int
    errors: list[str]


@router.post(
    "/games/{game_id}/materialize",
    response_model=CardFeedMaterializationResponse,
    response_model_by_alias=True,
)
async def materialize_game_card_feed(
    game_id: int,
    force: bool = Query(False),
    session: AsyncSession = Depends(get_db),
) -> CardFeedMaterializationResponse:
    """Materialize one game's current card-feed contract."""
    from app.feed.materialization import materialize_card_feed

    result = await materialize_card_feed(
        session,
        game_id,
        force=force,
    )
    return CardFeedMaterializationResponse(
        gameId=result.game_id,
        contractVersion=result.contract_version,
        feedKey=result.feed_key,
        status=result.status,
        cardCount=result.card_count,
        generated=result.generated,
        sourceHash=result.source_hash,
    )


@router.post(
    "/refresh",
    response_model=CardFeedRefreshResponse,
    response_model_by_alias=True,
)
async def refresh_recent_card_feeds(
    lookback_hours: int = Query(72, ge=1, le=720, alias="lookbackHours"),
    lookahead_hours: int = Query(72, ge=0, le=720, alias="lookaheadHours"),
    force: bool = Query(False),
    session: AsyncSession = Depends(get_db),
) -> CardFeedRefreshResponse:
    """Refresh card feeds for the deploy/scheduler data window."""
    from app.feed.materialization import refresh_card_feeds_for_window

    result = await refresh_card_feeds_for_window(
        session,
        lookback_hours=lookback_hours,
        lookahead_hours=lookahead_hours,
        force=force,
    )
    return CardFeedRefreshResponse(
        scannedGames=result.scanned_games,
        eligibleGames=result.eligible_games,
        generated=result.generated,
        skippedCurrent=result.skipped_current,
        failed=result.failed,
        errors=list(result.errors),
    )
