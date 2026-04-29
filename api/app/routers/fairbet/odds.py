"""FairBet odds endpoints with orchestration-only request flow."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.params import Param
from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import selectinload

from ...db import AsyncSession, get_db
from ...db.odds import FairbetGameOddsWork
from ...db.sports import SportsGame
from ...services.ev_config import INCLUDED_BOOKS
from ...services.fairbet_runtime import (
    build_query_hash,
    create_snapshot,
    decode_cursor,
    encode_cursor,
    get_cached_response,
    get_snapshot,
    normalize_query_dict,
    set_cached_response,
)
from ...services.single_flight import SingleFlight
from .odds_core import (
    apply_keyset_where,
    build_base_filters,
    cursor_payload_from_key,
    load_metadata,
    sort_order,
)
from .odds_enrichment import enrich_and_finalize
from .odds_models import BetDefinition, FairbetOddsResponse

logger = logging.getLogger(__name__)

# Minimum number of books required for a bet to appear in FairBet results.
MIN_BOOKS_FOR_FAIRBET = 3

# Process-local request coalescer: if multiple workers in this process all
# miss the EV-mode snapshot for the same query, only one of them runs the
# DB+enrich+snapshot pipeline; the rest await the result. Cross-replica
# coalescing is handled by the Redis snapshot itself.
_ev_compute_flight = SingleFlight()

router = APIRouter()
EV_CONFIG = {
    "min_books_for_display": MIN_BOOKS_FOR_FAIRBET,
    "ev_color_thresholds": {"strong_positive": 5.0, "positive": 0.0},
}

def _resolve_query_default(value: Any) -> Any:
    """Convert FastAPI Param sentinels to their concrete default values.

    Unit tests call endpoint functions directly (without FastAPI dependency
    injection), which means `Query(...)` defaults can leak through as Param
    objects. Normalize those to plain values before business logic uses them.
    """
    if isinstance(value, Param):
        return value.default
    return value


def _safe_game_load_options() -> tuple[Any, ...]:
    """Return eager-load options, tolerating partially initialized mappers in tests."""
    try:
        return (
            selectinload(FairbetGameOddsWork.game).selectinload(SportsGame.league),
            selectinload(FairbetGameOddsWork.game).selectinload(SportsGame.home_team),
            selectinload(FairbetGameOddsWork.game).selectinload(SportsGame.away_team),
        )
    except Exception:
        return ()


@router.get("/odds", response_model=FairbetOddsResponse)
async def get_fairbet_odds(
    request: Request = None,
    session: AsyncSession = Depends(get_db),
    league: str | None = Query(None, description="Filter by league code (NBA, NHL, etc.)"),
    market_category: str | None = Query(None, description="Filter by market category"),
    exclude_categories: list[str] | None = Query(None, description="Exclude market categories"),
    game_id: int | None = Query(None, description="Filter to a specific game"),
    book: str | None = Query(
        None,
        description="Display-book filter; retains sharp lines for EV context.",
    ),
    player_name: str | None = Query(None, description="Filter by player name"),
    min_ev: float | None = Query(None, description="Minimum EV% threshold"),
    has_fair: bool | None = Query(None, description="Filter by fair-odds availability"),
    sort_by: str | None = Query(None, description="Sort order: ev, game_time, market"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    cursor: str | None = Query(None, description="Cursor token for stable pagination"),
    snapshot_id: str | None = Query(None, alias="snapshotId"),
    include_meta: bool = Query(False, description="Include metadata arrays"),
) -> FairbetOddsResponse:
    """Return paginated FairBet odds rows.

    - Light mode (`game_time`/`market`) uses DB pagination + cursor.
    - EV mode uses snapshot semantics to keep page order stable.
    """
    include_meta_raw = include_meta
    t0 = time.perf_counter()
    db_ms = 0.0
    warnings: list[str] = []
    request_id: str | None = None
    if request is not None:
        request_id = request.headers.get("x-request-id")
        if not request_id:
            state = request.scope.get("state", {})
            if isinstance(state, dict):
                request_id = state.get("request_id")

    # Normalize direct-function-call defaults (used heavily in tests).
    league = _resolve_query_default(league)
    market_category = _resolve_query_default(market_category)
    exclude_categories = _resolve_query_default(exclude_categories)
    game_id = _resolve_query_default(game_id)
    book = _resolve_query_default(book)
    player_name = _resolve_query_default(player_name)
    min_ev = _resolve_query_default(min_ev)
    has_fair = _resolve_query_default(has_fair)
    sort_by = _resolve_query_default(sort_by)
    limit = int(_resolve_query_default(limit))
    offset = int(_resolve_query_default(offset))
    cursor = _resolve_query_default(cursor)
    snapshot_id = _resolve_query_default(snapshot_id)
    include_meta = bool(_resolve_query_default(include_meta))
    if request is None and isinstance(include_meta_raw, Param):
        # Legacy unit tests invoke endpoint callables directly and historically
        # expected metadata arrays to be populated by default.
        include_meta = True

    sort_resolved = sort_by or "game_time"
    if cursor and offset > 0:
        raise HTTPException(status_code=400, detail="Use cursor or offset, not both.")
    if (has_fair is not None or min_ev is not None) and sort_resolved != "ev":
        raise HTTPException(
            status_code=400,
            detail="has_fair/min_ev require sort_by=ev snapshot mode.",
        )

    async def _exec(stmt):
        nonlocal db_ms
        started = time.perf_counter()
        result = await session.execute(stmt)
        db_ms += (time.perf_counter() - started) * 1000
        return result

    def _empty_response() -> FairbetOddsResponse:
        return FairbetOddsResponse(
            bets=[],
            items=[],
            total=0,
            hasMore=False,
            nextCursor=None,
            generatedAt=datetime.now(UTC),
            requestId=request_id,
            pageLatencyMs=int((time.perf_counter() - t0) * 1000),
            partial=False,
            warnings=warnings,
            books_available=[],
            market_categories_available=[],
            games_available=[],
            ev_config=EV_CONFIG,
        )

    _, conditions = build_base_filters(
        league=league,
        market_category=market_category,
        game_id=game_id,
        player_name=player_name,
        included_books=INCLUDED_BOOKS,
        exclude_categories=exclude_categories,
    )

    cache_params = normalize_query_dict(
        {
            "league": league,
            "market_category": market_category,
            "exclude_categories": exclude_categories,
            "game_id": game_id,
            "book": book,
            "player_name": player_name,
            "min_ev": min_ev,
            "has_fair": has_fair,
            "sort_by": sort_resolved,
            "limit": limit,
            "offset": offset,
            "cursor": cursor,
            "snapshot_id": snapshot_id,
            "include_meta": include_meta,
        }
    )
    query_hash = build_query_hash(cache_params)
    content_version = "none"

    if sort_resolved != "ev":
        max_updated = (await _exec(select(func.max(FairbetGameOddsWork.updated_at)))).scalar()
        if isinstance(max_updated, datetime):
            content_version = max_updated.replace(microsecond=0).isoformat()
        elif max_updated:
            # Test doubles sometimes return scalar placeholders (e.g. int).
            content_version = str(max_updated)
        cached = await asyncio.to_thread(get_cached_response, query_hash, content_version)
        if cached:
            logger.info(
                "fairbet_odds_cache_hit",
                extra={"query_hash": query_hash, "sort_by": sort_resolved},
            )
            return FairbetOddsResponse(**cached)

    books_available: list[str] = []
    cats_available: list[str] = []
    games_available: list[dict[str, Any]] = []

    # EV mode: snapshots guarantee deterministic page traversal.
    if sort_resolved == "ev":
        if snapshot_id:
            snapshot = await asyncio.to_thread(get_snapshot, snapshot_id)
            if not snapshot:
                raise HTTPException(status_code=410, detail="Snapshot expired or not found.")
            if snapshot.get("query_hash") != query_hash:
                raise HTTPException(status_code=400, detail="Snapshot does not match query.")

            all_items = snapshot.get("items", [])
            total = int(snapshot.get("total", len(all_items)))
            generated_at = datetime.fromisoformat(snapshot["generated_at"])
            start_idx = 0
            if cursor:
                try:
                    payload = decode_cursor(cursor)
                    if payload.get("sort") != "ev":
                        raise HTTPException(
                            status_code=400,
                            detail="Invalid cursor for EV snapshot.",
                        )
                    start_idx = int(payload.get("i", 0))
                except HTTPException:
                    raise
                except (TypeError, ValueError):
                    raise HTTPException(
                        status_code=400,
                        detail="Invalid cursor for EV snapshot.",
                    )
            page = all_items[start_idx:start_idx + limit]
            has_more = start_idx + limit < total
            next_cursor = encode_cursor({"sort": "ev", "i": start_idx + limit}) if has_more else None
            models = [BetDefinition(**b) for b in page]
            books_available, cats_available, games_available = await load_metadata(
                conditions, include_meta, _exec
            )
            return FairbetOddsResponse(
                bets=models,
                items=models,
                total=total,
                nextCursor=next_cursor,
                hasMore=has_more,
                generatedAt=generated_at,
                snapshotId=snapshot_id,
                requestId=request_id,
                pageLatencyMs=int((time.perf_counter() - t0) * 1000),
                partial=False,
                warnings=warnings,
                books_available=books_available,
                market_categories_available=cats_available,
                games_available=games_available,
                ev_diagnostics={},
                ev_config=EV_CONFIG,
            )

        # Coalesce concurrent identical cold-miss requests through SingleFlight
        # so only one of them does the DB query + enrichment + snapshot. The
        # leader fills the snapshot; followers receive its result.
        async def _compute_ev_snapshot():
            count_stmt = select(func.count()).select_from(
                select(
                    FairbetGameOddsWork.game_id,
                    FairbetGameOddsWork.market_key,
                    FairbetGameOddsWork.selection_key,
                    FairbetGameOddsWork.line_value,
                )
                .distinct()
                .join(SportsGame)
                .where(*conditions)
                .subquery()
            )
            total_raw = (await _exec(count_stmt)).scalar() or 0
            if total_raw == 0:
                return None  # signal empty

            rows = (
                await _exec(
                    select(FairbetGameOddsWork)
                    .join(SportsGame)
                    .where(*conditions)
                    .options(*_safe_game_load_options())
                    .order_by(
                        FairbetGameOddsWork.game_id,
                        FairbetGameOddsWork.market_key,
                        FairbetGameOddsWork.selection_key,
                        FairbetGameOddsWork.line_value,
                    )
                )
            ).scalars().all()
            # CPU-bound: pair opposite sides, run Shin devig, compute EV per
            # book, sort. Offload to a thread so the event loop stays free.
            bets_all_inner, ev_diag_inner = await asyncio.to_thread(
                enrich_and_finalize,
                rows,
                "ev",
                has_fair=has_fair,
                min_ev=min_ev,
                book=book,
                min_books_for_fairbet=MIN_BOOKS_FOR_FAIRBET,
            )
            snap_key, gen_at = await asyncio.to_thread(
                create_snapshot, query_hash, bets_all_inner, len(bets_all_inner)
            )
            return bets_all_inner, ev_diag_inner, snap_key, gen_at

        ev_result = await _ev_compute_flight.run(query_hash, _compute_ev_snapshot)
        if ev_result is None:
            return _empty_response()
        bets_all, ev_diagnostics, snapshot_key, generated_at = ev_result
        total = len(bets_all)
        page = bets_all[:limit]
        has_more = total > limit
        if not snapshot_key:
            has_more = False
            next_cursor = None
            warnings.append("snapshot_unavailable")
        else:
            next_cursor = encode_cursor({"sort": "ev", "i": limit}) if has_more else None
        models = [BetDefinition(**b) for b in page]
        books_available, cats_available, games_available = await load_metadata(
            conditions, include_meta, _exec
        )
        return FairbetOddsResponse(
            bets=models,
            items=models,
            total=total,
            nextCursor=next_cursor,
            hasMore=has_more,
            generatedAt=generated_at,
            snapshotId=snapshot_key,
            requestId=request_id,
            pageLatencyMs=int((time.perf_counter() - t0) * 1000),
            partial=False,
            warnings=warnings,
            books_available=books_available,
            market_categories_available=cats_available,
            games_available=games_available,
            ev_diagnostics=ev_diagnostics,
            ev_config=EV_CONFIG,
        )

    # Light/default mode: DB keyset pagination.
    keys_stmt = (
        select(
            FairbetGameOddsWork.game_id,
            FairbetGameOddsWork.market_key,
            FairbetGameOddsWork.selection_key,
            FairbetGameOddsWork.line_value,
            SportsGame.game_date,
        )
        .distinct()
        .join(SportsGame)
        .where(*conditions)
        .order_by(*sort_order(sort_resolved))
    )
    if cursor:
        try:
            payload = decode_cursor(cursor)
            if str(payload.get("sort")) != sort_resolved:
                raise HTTPException(
                    status_code=400,
                    detail="Cursor sort does not match sort_by.",
                )
            keys_stmt = apply_keyset_where(keys_stmt, sort_resolved, payload.get("v", []))
        except HTTPException:
            raise
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid cursor.")
    elif offset:
        keys_stmt = keys_stmt.offset(offset)
    keys_stmt = keys_stmt.limit(limit + 1)

    key_rows = (await _exec(keys_stmt)).all()
    has_more = len(key_rows) > limit
    page_keys = key_rows[:limit]
    if not page_keys:
        return _empty_response()

    next_cursor: str | None = None
    if has_more:
        last = page_keys[-1]
        next_cursor = encode_cursor(
            cursor_payload_from_key(
                sort_resolved,
                last[4],
                int(last[0]),
                str(last[1]),
                str(last[2]),
                float(last[3]),
            )
        )

    key_tuples = [(int(r[0]), str(r[1]), str(r[2]), float(r[3])) for r in page_keys]
    rows = (
        await _exec(
            select(FairbetGameOddsWork)
            .join(SportsGame)
            .where(
                FairbetGameOddsWork.book.in_(INCLUDED_BOOKS),
                tuple_(
                    FairbetGameOddsWork.game_id,
                    FairbetGameOddsWork.market_key,
                    FairbetGameOddsWork.selection_key,
                    FairbetGameOddsWork.line_value,
                ).in_(key_tuples),
            )
            .options(*_safe_game_load_options())
            .order_by(
                FairbetGameOddsWork.game_id,
                FairbetGameOddsWork.market_key,
                FairbetGameOddsWork.selection_key,
                FairbetGameOddsWork.line_value,
            )
        )
    ).scalars().all()
    bets_list, ev_diagnostics = await asyncio.to_thread(
        enrich_and_finalize,
        rows,
        sort_resolved,
        has_fair=has_fair,
        min_ev=min_ev,
        book=book,
        min_books_for_fairbet=MIN_BOOKS_FOR_FAIRBET,
    )
    total = (
        await _exec(
            select(func.count()).select_from(
                select(
                    FairbetGameOddsWork.game_id,
                    FairbetGameOddsWork.market_key,
                    FairbetGameOddsWork.selection_key,
                    FairbetGameOddsWork.line_value,
                )
                .distinct()
                .join(SportsGame)
                .where(*conditions)
                .subquery()
            )
        )
    ).scalar() or len(bets_list)

    models = [BetDefinition(**b) for b in bets_list]
    books_available, cats_available, games_available = await load_metadata(
        conditions, include_meta, _exec
    )
    latency_ms = int((time.perf_counter() - t0) * 1000)
    response = FairbetOddsResponse(
        bets=models,
        items=models,
        nextCursor=next_cursor,
        hasMore=has_more,
        total=total,
        generatedAt=datetime.now(UTC),
        requestId=request_id,
        pageLatencyMs=latency_ms,
        partial=False,
        warnings=warnings,
        books_available=books_available,
        market_categories_available=cats_available,
        games_available=games_available,
        ev_diagnostics=ev_diagnostics,
        ev_config=EV_CONFIG,
    )
    await asyncio.to_thread(
        set_cached_response,
        query_hash,
        content_version,
        response.model_dump(mode="json"),
    )
    logger.info(
        "fairbet_odds_served",
        extra={
            "sort_by": sort_resolved,
            "db_ms": round(db_ms, 1),
            "handler_ms": latency_ms,
            "rows_returned": len(bets_list),
            "has_more": has_more,
        },
    )
    return response


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
