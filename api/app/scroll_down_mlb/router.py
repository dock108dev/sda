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

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Response, status

from app.db import AsyncSession, get_db

from . import service
from .schemas import (
    ScrollDownMlbDeckResponse,
    ScrollDownMlbRecentResponse,
    ScrollDownMlbRevealResponse,
)


def _if_none_match_hits(if_none_match: str, current_etag: str) -> bool:
    """RFC 7232-flavored match: split on commas, strip W/ prefix + quotes."""
    for candidate in if_none_match.split(","):
        token = candidate.strip()
        if token == "*":
            return True
        if token.startswith("W/"):
            token = token[2:]
        if len(token) >= 2 and token.startswith('"') and token.endswith('"'):
            token = token[1:-1]
        if token == current_etag:
            return True
    return False

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
    response: Response,
    game_id: str = Path(..., min_length=1, max_length=64, pattern=r"^[0-9]+$"),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    session: AsyncSession = Depends(get_db),
):
    """Spoiler-safe deck for the catch-up flow.

    Returns whichever deck (live provisional or official) is most current.
    The client uses `deckVersion` to detect updates without diffing cards.

    Supports conditional GETs: when the client sends `If-None-Match` with
    the previously seen `deckVersion`, the server short-circuits to 304
    using a lightweight metadata-only version check — avoiding both the
    payload load and the full build pipeline when nothing has changed.
    """
    if if_none_match is not None:
        current_etag = await service.compute_deck_etag(session, game_id)
        if current_etag is not None and _if_none_match_hits(
            if_none_match, current_etag
        ):
            return Response(
                status_code=status.HTTP_304_NOT_MODIFIED,
                headers={"ETag": f'"{current_etag}"'},
            )
    deck = await service.get_game_deck(session, game_id)
    if deck is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No deck available for this game yet.",
        )
    response.headers["ETag"] = f'"{deck.deck_version}"'
    return deck


@router.get(
    "/games/{game_id}/reveal",
    response_model=ScrollDownMlbRevealResponse,
    response_model_by_alias=True,
)
async def get_game_reveal(
    game_id: str = Path(..., min_length=1, max_length=64, pattern=r"^[0-9]+$"),
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
