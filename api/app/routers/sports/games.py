"""Game list and action endpoints for sports admin."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import case, desc, exists, func, not_, or_, select
from sqlalchemy.orm import selectinload

from ...db import AsyncSession, get_db
from ...db.flow import SportsGameFlow
from ...db.odds import SportsGameOdds
from ...db.scraper import SportsGameConflict
from ...db.social import TeamSocialPost
from ...db.sports import (
    SportsGame,
    SportsGamePlay,
    SportsPlayerBoxscore,
    SportsTeamBoxscore,
)
from ...services.game_status import LIVE_STATUSES
from ...services.response_cache import (
    build_cache_key,
    cache_status,
    get_cached,
    set_cached,
    should_bypass_cache,
)
from .game_detail import router as detail_router
from .game_helpers import (
    _GameSummaryFlags,
    apply_game_filters,
    enqueue_single_game_resync,
    summarize_game,
)
from .schemas import (
    GameListResponse,
    JobResponse,
)

router = APIRouter()
router.include_router(detail_router)

# Read-heavy endpoint: many CI workers and SSR loaders fetch the same shape.
# Short TTL keeps data fresh while collapsing duplicate queries.
_GAMES_LIST_CACHE_TTL_SECONDS = 15


@router.get("/games", response_model=GameListResponse)
async def list_games(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db),
    league: list[str] | None = Query(None),
    season: int | None = Query(None),
    team: str | None = Query(None),
    startDate: date | None = Query(None, alias="startDate"),
    endDate: date | None = Query(None, alias="endDate"),
    missingBoxscore: bool = Query(False, alias="missingBoxscore"),
    missingPlayerStats: bool = Query(False, alias="missingPlayerStats"),
    missingOdds: bool = Query(False, alias="missingOdds"),
    missingSocial: bool = Query(False, alias="missingSocial"),
    missingAny: bool = Query(False, alias="missingAny"),
    hasPbp: bool = Query(
        False,
        alias="hasPbp",
        description="Only return games with play-by-play data",
    ),
    finalOnly: bool = Query(
        False,
        alias="finalOnly",
        description="Only include games with final/completed/official status",
    ),
    safe: bool = Query(
        False,
        description="Exclude games with conflicts or missing team mappings (app-safe mode)",
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    cache_bypass = should_bypass_cache(request)
    cache_key: str | None = None
    if not cache_bypass:
        cache_key = build_cache_key(
            "games_list",
            {
                "league": league,
                "season": season,
                "team": team,
                "startDate": startDate.isoformat() if startDate else None,
                "endDate": endDate.isoformat() if endDate else None,
                "missingBoxscore": missingBoxscore,
                "missingPlayerStats": missingPlayerStats,
                "missingOdds": missingOdds,
                "missingSocial": missingSocial,
                "missingAny": missingAny,
                "hasPbp": hasPbp,
                "finalOnly": finalOnly,
                "safe": safe,
                "limit": limit,
                "offset": offset,
            },
        )
        cached = get_cached(cache_key)
        if cached is not None:
            return JSONResponse(
                content=cached,
                headers={
                    "Cache-Control": f"public, max-age={_GAMES_LIST_CACHE_TTL_SECONDS}",
                    "X-Cache": "HIT",
                },
            )
    # Page query: only eager-load relations that summarize_game consumes in
    # full (league, both teams, odds for derived metrics). Booleans and counts
    # come from scalar subqueries; live-game period/clock comes from a
    # targeted follow-up query for live games only.
    has_boxscore_sq = (
        exists(select(1).where(SportsTeamBoxscore.game_id == SportsGame.id))
        .label("has_boxscore_flag")
    )
    has_player_stats_sq = (
        exists(select(1).where(SportsPlayerBoxscore.game_id == SportsGame.id))
        .label("has_player_stats_flag")
    )
    play_count_sq = (
        select(func.count(SportsGamePlay.id))
        .where(SportsGamePlay.game_id == SportsGame.id)
        .correlate(SportsGame)
        .scalar_subquery()
        .label("play_count")
    )
    social_count_sq = (
        select(func.count(TeamSocialPost.id))
        .where(
            TeamSocialPost.game_id == SportsGame.id,
            TeamSocialPost.mapping_status == "mapped",
        )
        .correlate(SportsGame)
        .scalar_subquery()
        .label("social_post_count")
    )

    base_stmt = (
        select(
            SportsGame,
            has_boxscore_sq,
            has_player_stats_sq,
            play_count_sq,
            social_count_sq,
        )
        .options(
            selectinload(SportsGame.league),
            selectinload(SportsGame.home_team),
            selectinload(SportsGame.away_team),
            selectinload(SportsGame.odds),
        )
    )

    base_stmt = apply_game_filters(
        base_stmt,
        leagues=league,
        season=season,
        team=team,
        start_date=startDate,
        end_date=endDate,
        missing_boxscore=missingBoxscore,
        missing_player_stats=missingPlayerStats,
        missing_odds=missingOdds,
        missing_social=missingSocial,
        missing_any=missingAny,
        final_only=finalOnly,
    )

    # Filter to games with play-by-play data
    if hasPbp:
        pbp_exists = exists(select(1).where(SportsGamePlay.game_id == SportsGame.id))
        base_stmt = base_stmt.where(pbp_exists)

    # Safety filtering: exclude games with conflicts or missing team mappings
    if safe:
        # Exclude games with unresolved conflicts
        conflict_exists = exists(
            select(1)
            .where(SportsGameConflict.resolved_at.is_(None))
            .where(
                or_(
                    SportsGameConflict.game_id == SportsGame.id,
                    SportsGameConflict.conflict_game_id == SportsGame.id,
                )
            )
        )
        base_stmt = base_stmt.where(not_(conflict_exists))
        # Exclude games with missing team mappings
        base_stmt = base_stmt.where(
            SportsGame.home_team_id.isnot(None),
            SportsGame.away_team_id.isnot(None),
        )

    stmt = base_stmt.order_by(desc(SportsGame.game_date)).offset(offset).limit(limit)
    results = (await session.execute(stmt)).unique().all()
    games = [row[0] for row in results]
    flags_by_id: dict[int, _GameSummaryFlags] = {
        row[0].id: _GameSummaryFlags(
            has_boxscore=bool(row[1]),
            has_player_stats=bool(row[2]),
            has_pbp=int(row[3] or 0) > 0,
            play_count=int(row[3] or 0),
            social_post_count=int(row[4] or 0),
            has_social=int(row[4] or 0) > 0,
        )
        for row in results
    }

    # Single aggregate query replaces the prior 8 sequential count queries.
    boxscore_exists = exists(
        select(1).where(SportsTeamBoxscore.game_id == SportsGame.id)
    )
    player_stats_exists = exists(
        select(1).where(SportsPlayerBoxscore.game_id == SportsGame.id)
    )
    odds_exists = exists(
        select(1).where(SportsGameOdds.game_id == SportsGame.id)
    )
    social_exists = exists(
        select(1).where(
            TeamSocialPost.game_id == SportsGame.id,
            TeamSocialPost.mapping_status == "mapped",
        )
    )
    pbp_exists_agg = exists(
        select(1).where(SportsGamePlay.game_id == SportsGame.id)
    )
    flow_exists_agg = exists(
        select(1).where(
            SportsGameFlow.game_id == SportsGame.id,
            SportsGameFlow.moments_json.isnot(None),
        )
    )

    def _sum_when(condition):
        # Postgres-portable equivalent of COUNT(*) FILTER (WHERE …) — works
        # with SQLAlchemy ``case`` and is supported on all backends used here.
        return func.coalesce(func.sum(case((condition, 1), else_=0)), 0)

    counts_stmt = select(
        func.count(SportsGame.id).label("total"),
        _sum_when(boxscore_exists).label("with_boxscore"),
        _sum_when(player_stats_exists).label("with_player_stats"),
        _sum_when(odds_exists).label("with_odds"),
        _sum_when(social_exists).label("with_social"),
        _sum_when(pbp_exists_agg).label("with_pbp"),
        _sum_when(flow_exists_agg).label("with_flow"),
        _sum_when(SportsGame.last_advanced_stats_at.isnot(None)).label(
            "with_advanced_stats"
        ),
    )
    counts_stmt = apply_game_filters(
        counts_stmt,
        leagues=league,
        season=season,
        team=team,
        start_date=startDate,
        end_date=endDate,
        missing_boxscore=missingBoxscore,
        missing_player_stats=missingPlayerStats,
        missing_odds=missingOdds,
        missing_social=missingSocial,
        missing_any=missingAny,
        final_only=finalOnly,
    )
    if hasPbp:
        counts_stmt = counts_stmt.where(pbp_exists_agg)
    if safe:
        conflict_exists_count = exists(
            select(1)
            .where(SportsGameConflict.resolved_at.is_(None))
            .where(
                or_(
                    SportsGameConflict.game_id == SportsGame.id,
                    SportsGameConflict.conflict_game_id == SportsGame.id,
                )
            )
        )
        counts_stmt = counts_stmt.where(not_(conflict_exists_count))
        counts_stmt = counts_stmt.where(
            SportsGame.home_team_id.isnot(None),
            SportsGame.away_team_id.isnot(None),
        )

    counts_row = (await session.execute(counts_stmt)).one()
    total = int(counts_row.total)
    with_boxscore_count = int(counts_row.with_boxscore)
    with_player_stats_count = int(counts_row.with_player_stats)
    with_odds_count = int(counts_row.with_odds)
    with_social_count = int(counts_row.with_social)
    with_pbp_count = int(counts_row.with_pbp)
    with_flow_count = int(counts_row.with_flow)
    with_advanced_stats_count = int(counts_row.with_advanced_stats)

    # Look up which games have a flow (small IN list, no per-game subquery).
    game_ids = [game.id for game in games]
    if game_ids:
        flow_check_stmt = select(SportsGameFlow.game_id).where(
            SportsGameFlow.game_id.in_(game_ids),
            SportsGameFlow.moments_json.isnot(None),
        )
        flow_result = await session.execute(flow_check_stmt)
        games_with_flow = set(flow_result.scalars().all())
    else:
        games_with_flow = set()

    # Latest play snapshot for live games only — avoids loading PBP for the
    # 95%+ of listed games that are pregame or final. One DISTINCT ON query
    # returns the row with the highest play_index per game in a single round
    # trip (Postgres-specific; matches the rest of this codebase).
    live_game_ids = [
        game.id
        for game in games
        if (game.status or "").lower().strip() in LIVE_STATUSES
    ]
    latest_play_by_game: dict[int, tuple[int | None, str | None]] = {}
    if live_game_ids:
        latest_play_stmt = (
            select(
                SportsGamePlay.game_id,
                SportsGamePlay.quarter,
                SportsGamePlay.game_clock,
            )
            .where(SportsGamePlay.game_id.in_(live_game_ids))
            .order_by(SportsGamePlay.game_id, desc(SportsGamePlay.play_index))
            .distinct(SportsGamePlay.game_id)
        )
        for game_id, quarter, clock in (await session.execute(latest_play_stmt)).all():
            latest_play_by_game[game_id] = (quarter, clock)

    next_offset = offset + limit if offset + limit < total else None
    summaries = [
        summarize_game(
            game,
            has_flow=game.id in games_with_flow,
            flags=flags_by_id.get(game.id),
            latest_play_period=latest_play_by_game.get(game.id, (None, None))[0],
            latest_play_clock=latest_play_by_game.get(game.id, (None, None))[1],
        )
        for game in games
    ]

    payload = GameListResponse(
        games=summaries,
        total=total,
        next_offset=next_offset,
        with_boxscore_count=with_boxscore_count,
        with_player_stats_count=with_player_stats_count,
        with_odds_count=with_odds_count,
        with_social_count=with_social_count,
        with_pbp_count=with_pbp_count,
        with_flow_count=with_flow_count,
        with_advanced_stats_count=with_advanced_stats_count,
    )

    if cache_key is not None:
        # Cache the wire shape (camelCase aliases) so the hit path doesn't
        # need to re-serialize through the response model.
        set_cached(
            cache_key,
            payload.model_dump(by_alias=True, mode="json"),
            ttl_seconds=_GAMES_LIST_CACHE_TTL_SECONDS,
        )
    response.headers["Cache-Control"] = (
        f"public, max-age={_GAMES_LIST_CACHE_TTL_SECONDS}"
    )
    if cache_bypass:
        response.headers["X-Cache"] = "BYPASS"
    elif cache_status()["open"]:
        # Redis circuit breaker tripped — every request is a cold miss until
        # the breaker resets. Emit DISABLED so devtools shows the cause.
        response.headers["X-Cache"] = "DISABLED"
    else:
        response.headers["X-Cache"] = "MISS"
    return payload


@router.post("/games/{game_id}/resync", response_model=JobResponse)
async def resync_game(game_id: int, session: AsyncSession = Depends(get_db)) -> JobResponse:
    """Resync all data for a game: boxscores, player stats, odds, PBP, advanced stats."""
    game = await session.get(SportsGame, game_id)
    if not game:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Game not found")
    return await enqueue_single_game_resync(session, game)
