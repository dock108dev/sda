"""Game list and action endpoints for sports admin."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, exists, func, not_, or_, select
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
from .game_detail import router as detail_router
from .game_helpers import (
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


@router.get("/games", response_model=GameListResponse)
async def list_games(
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
) -> GameListResponse:
    base_stmt = select(SportsGame).options(
        selectinload(SportsGame.league),
        selectinload(SportsGame.home_team),
        selectinload(SportsGame.away_team),
        selectinload(SportsGame.team_boxscores),
        selectinload(SportsGame.player_boxscores),
        selectinload(SportsGame.odds),
        selectinload(SportsGame.social_posts),
        selectinload(SportsGame.plays),
        selectinload(SportsGame.timeline_artifacts),
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
    results = await session.execute(stmt)
    games = results.scalars().unique().all()

    count_stmt = select(func.count(SportsGame.id))
    count_stmt = apply_game_filters(
        count_stmt,
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

    # Apply hasPbp filter to count query
    if hasPbp:
        pbp_exists_count = exists(select(1).where(SportsGamePlay.game_id == SportsGame.id))
        count_stmt = count_stmt.where(pbp_exists_count)

    # Apply same safety filtering to count query
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
        count_stmt = count_stmt.where(not_(conflict_exists_count))
        count_stmt = count_stmt.where(
            SportsGame.home_team_id.isnot(None),
            SportsGame.away_team_id.isnot(None),
        )

    total = (await session.execute(count_stmt)).scalar_one()

    with_boxscore_count_stmt = count_stmt.where(
        exists(select(1).where(SportsTeamBoxscore.game_id == SportsGame.id))
    )
    with_player_stats_count_stmt = count_stmt.where(
        exists(select(1).where(SportsPlayerBoxscore.game_id == SportsGame.id))
    )
    with_odds_count_stmt = count_stmt.where(
        exists(select(1).where(SportsGameOdds.game_id == SportsGame.id))
    )
    with_social_count_stmt = count_stmt.where(
        exists(
            select(1).where(
                TeamSocialPost.game_id == SportsGame.id,
                TeamSocialPost.mapping_status == "mapped",
            )
        )
    )
    with_pbp_count_stmt = count_stmt.where(
        exists(select(1).where(SportsGamePlay.game_id == SportsGame.id))
    )
    with_flow_count_stmt = count_stmt.where(
        exists(
            select(1).where(
                SportsGameFlow.game_id == SportsGame.id,
                SportsGameFlow.moments_json.isnot(None),
            )
        )
    )

    with_boxscore_count = (await session.execute(with_boxscore_count_stmt)).scalar_one()
    with_player_stats_count = (await session.execute(with_player_stats_count_stmt)).scalar_one()
    with_odds_count = (await session.execute(with_odds_count_stmt)).scalar_one()
    with_social_count = (await session.execute(with_social_count_stmt)).scalar_one()
    with_pbp_count = (await session.execute(with_pbp_count_stmt)).scalar_one()
    with_flow_count = (await session.execute(with_flow_count_stmt)).scalar_one()

    with_advanced_stats_count_stmt = count_stmt.where(SportsGame.last_advanced_stats_at.isnot(None))
    with_advanced_stats_count = (await session.execute(with_advanced_stats_count_stmt)).scalar_one()

    # Query which games have flows in SportsGameFlow table
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

    next_offset = offset + limit if offset + limit < total else None
    summaries = [summarize_game(game, has_flow=game.id in games_with_flow) for game in games]

    return GameListResponse(
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


@router.post("/games/{game_id}/resync", response_model=JobResponse)
async def resync_game(game_id: int, session: AsyncSession = Depends(get_db)) -> JobResponse:
    """Resync all data for a game: boxscores, player stats, odds, PBP, advanced stats."""
    game = await session.get(SportsGame, game_id)
    if not game:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Game not found")
    return await enqueue_single_game_resync(session, game)
