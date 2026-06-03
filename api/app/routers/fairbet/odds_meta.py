"""FairBet odds metadata endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from ...db import AsyncSession, get_db
from ...services.ev_config import INCLUDED_BOOKS
from .odds_core import build_base_filters, load_metadata

router = APIRouter()


@router.get("/odds/meta")
async def get_fairbet_odds_meta(
    session: AsyncSession = Depends(get_db),
    league: str | None = Query(None),
    market_category: str | None = Query(None),
    exclude_categories: list[str] | None = Query(None),
    game_id: int | None = Query(None),
    book: str | None = Query(None),
    player_name: str | None = Query(None),
) -> dict[str, Any]:
    """Return metadata-only payload for filter dropdowns."""
    _, conditions = build_base_filters(
        league=league,
        market_category=market_category,
        game_id=game_id,
        player_name=player_name,
        included_books=INCLUDED_BOOKS,
        exclude_categories=exclude_categories,
    )
    books, cats, games = await load_metadata(conditions, True, session.execute)
    return {
        "books_available": books,
        "market_categories_available": cats,
        "games_available": games,
    }
