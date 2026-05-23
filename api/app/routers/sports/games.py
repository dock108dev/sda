"""Game action endpoints for sports admin.

The catch-up list/detail routes are owned by ``catchup.py``. This module keeps
non-list game actions and legacy admin diagnostics that still have explicit
callers.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from ...db import AsyncSession, get_db
from ...db.sports import SportsGame
from .game_detail import router as detail_router
from .game_helpers import enqueue_single_game_resync
from .schemas import JobResponse

router = APIRouter()
router.include_router(detail_router)


@router.post("/games/{game_id}/resync", response_model=JobResponse)
async def resync_game(game_id: int, session: AsyncSession = Depends(get_db)) -> JobResponse:
    """Resync all data for a game: boxscores, player stats, odds, PBP, advanced stats."""
    game = await session.get(SportsGame, game_id)
    if not game:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Game not found")
    return await enqueue_single_game_resync(session, game)
