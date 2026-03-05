"""FairBet Live endpoint: closing snapshot (DB) + live lines (Redis).

GET /api/fairbet/live?game_id=...&market_key=...

Fast and cheap:
  - DB read for closing snapshot (durable)
  - Redis read for live snapshot + recent history (ephemeral)
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.db import get_db
from app.db.odds import ClosingLine
from app.services.live_odds_redis import (
    read_all_live_snapshots_for_game,
    read_live_history,
    read_live_snapshot,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class ClosingLineResponse(BaseModel):
    provider: str
    market_key: str
    selection: str
    line_value: float | None
    price_american: float
    captured_at: str
    source_type: str


class LiveSnapshotResponse(BaseModel):
    last_updated_at: float | None = None
    provider: str | None = None
    selections: list[dict[str, Any]] = []
    ttl_seconds_remaining: int | None = None


class FairbetLiveResponse(BaseModel):
    game_id: int
    market_key: str | None
    closing: list[ClosingLineResponse]
    live: dict[str, LiveSnapshotResponse] | LiveSnapshotResponse | None
    history: list[dict[str, Any]]
    meta: dict[str, Any]


@router.get("/live")
async def fairbet_live(
    game_id: int = Query(..., description="Game ID"),
    market_key: str | None = Query(None, description="Market key (spread, total, moneyline). Omit for all."),
    history_count: int = Query(50, ge=0, le=300, description="Number of history entries"),
) -> FairbetLiveResponse:
    """Get closing snapshot + live odds for a game.

    Combines durable closing lines from DB with ephemeral live lines from Redis.
    """
    # Fetch closing lines from DB
    async for session in get_db():
        stmt = select(ClosingLine).where(ClosingLine.game_id == game_id)
        if market_key:
            stmt = stmt.where(ClosingLine.market_key == market_key)

        result = await session.execute(stmt)
        closing_rows = result.scalars().all()

        # Get league from game
        from app.db.sports import SportsGame, SportsLeague

        game_stmt = (
            select(SportsLeague.code)
            .join(SportsGame, SportsGame.league_id == SportsLeague.id)
            .where(SportsGame.id == game_id)
        )
        league_result = await session.execute(game_stmt)
        league_code = league_result.scalar_one_or_none()

    if not league_code:
        raise HTTPException(status_code=404, detail="Game not found")

    # Build closing response
    closing = [
        ClosingLineResponse(
            provider=row.provider,
            market_key=row.market_key,
            selection=row.selection,
            line_value=row.line_value,
            price_american=row.price_american,
            captured_at=row.captured_at.isoformat() if row.captured_at else "",
            source_type=row.source_type,
        )
        for row in closing_rows
    ]

    # Fetch live data from Redis
    live: dict[str, LiveSnapshotResponse] | LiveSnapshotResponse | None = None
    history: list[dict] = []

    if market_key:
        snapshot = read_live_snapshot(league_code, game_id, market_key)
        if snapshot:
            live = LiveSnapshotResponse(
                last_updated_at=snapshot.get("last_updated_at"),
                provider=snapshot.get("provider"),
                selections=snapshot.get("selections", []),
                ttl_seconds_remaining=snapshot.get("ttl_seconds_remaining"),
            )

        if history_count > 0:
            history = read_live_history(game_id, market_key, count=history_count)
    else:
        # Return all markets
        all_snapshots = read_all_live_snapshots_for_game(league_code, game_id)
        live = {
            mk: LiveSnapshotResponse(
                last_updated_at=snap.get("last_updated_at"),
                provider=snap.get("provider"),
                selections=snap.get("selections", []),
                ttl_seconds_remaining=snap.get("ttl_seconds_remaining"),
            )
            for mk, snap in all_snapshots.items()
        }

    live_updated_at = None
    if isinstance(live, LiveSnapshotResponse) and live.last_updated_at:
        live_updated_at = datetime.fromtimestamp(live.last_updated_at).isoformat()
    elif isinstance(live, dict) and live:
        latest = max(
            (s.last_updated_at for s in live.values() if s.last_updated_at),
            default=None,
        )
        if latest:
            live_updated_at = datetime.fromtimestamp(latest).isoformat()

    return FairbetLiveResponse(
        game_id=game_id,
        market_key=market_key,
        closing=closing,
        live=live,
        history=history,
        meta={
            "league": league_code,
            "live_updated_at": live_updated_at,
            "closing_count": len(closing),
        },
    )
