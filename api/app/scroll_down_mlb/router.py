"""HTTP surface for Scroll Down MLB.

Three endpoints — consumer namespace per repo policy
(`tests/test_router_namespaces.py`):

  GET /api/v1/scroll-down-mlb/games/recent           — spoiler-safe feed
  GET /api/v1/scroll-down-mlb/games/{game_id}/deck   — pre-reveal deck
  GET /api/v1/scroll-down-mlb/games/{game_id}/reveal — final-score reveal

Phase 5 wires the service to the real SDA database. The router itself
stays thin — orchestration lives in `service.py`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, status

from app.db import AsyncSession, get_db

from . import service
from .schemas import (
    ScrollDownMlbDeckResponse,
    ScrollDownMlbRecentResponse,
    ScrollDownMlbRevealResponse,
)

router = APIRouter(prefix="/api/v1/scroll-down-mlb", tags=["scroll-down-mlb"])


@router.get(
    "/games/recent",
    response_model=ScrollDownMlbRecentResponse,
    response_model_by_alias=True,
)
async def list_recent_games(
    session: AsyncSession = Depends(get_db),
) -> ScrollDownMlbRecentResponse:
    """Recent games for the catch-up feed.

    Spoiler-safe: no scores, no winners. The frontend's home grid renders
    matchups only.
    """
    games = await service.get_recent_games(session)
    return ScrollDownMlbRecentResponse(games=games)


@router.get(
    "/games/{game_id}/deck",
    response_model=ScrollDownMlbDeckResponse,
    response_model_by_alias=True,
)
async def get_game_deck(
    game_id: str = Path(..., min_length=1, max_length=64),
    session: AsyncSession = Depends(get_db),
) -> ScrollDownMlbDeckResponse:
    """Spoiler-safe deck for the catch-up flow.

    Returns whichever deck (live provisional or official) is most current.
    The client uses `deckVersion` to detect updates without diffing cards.
    """
    deck = await service.get_game_deck(session, game_id)
    if deck is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No deck available for this game yet.",
        )
    return deck


@router.get(
    "/games/{game_id}/reveal",
    response_model=ScrollDownMlbRevealResponse,
    response_model_by_alias=True,
)
async def get_game_reveal(
    game_id: str = Path(..., min_length=1, max_length=64),
    session: AsyncSession = Depends(get_db),
) -> ScrollDownMlbRevealResponse:
    """Final-score reveal — the ONLY endpoint allowed to leak the result.

    Returns 409 if the game has not yet produced a reveal payload (in
    progress, postponed, or upstream not ready).
    """
    reveal = await service.get_game_reveal(session, game_id)
    if reveal is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Reveal not available yet for this game.",
        )
    return reveal
