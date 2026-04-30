"""Pipeline status and info endpoints.

Get run status, list runs for a game, and get pipeline summary.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from ....db import AsyncSession, get_db
from ....db.flow import SportsGameTimelineArtifact
from ....db.pipeline import GamePipelineRun
from ....db.sports import GameStatus, SportsGame, SportsGamePlay
from .helpers import (
    build_run_response,
    build_run_summary,
    get_run_with_stages,
)
from .models import (
    GamePipelineRunsResponse,
    GamePipelineSummary,
    PipelineRunResponse,
)

router = APIRouter()


@router.get(
    "/pipeline/run/{run_id}",
    response_model=PipelineRunResponse,
    summary="Get run status",
    description="Get detailed status of a pipeline run including all stages.",
)
async def get_run_status(
    run_id: int,
    session: AsyncSession = Depends(get_db),
) -> PipelineRunResponse:
    """Get detailed status of a pipeline run."""
    run = await get_run_with_stages(session, run_id)
    return build_run_response(run)


@router.get(
    "/pipeline/game/{game_id}",
    response_model=GamePipelineRunsResponse,
    summary="List runs for game",
    description="List all pipeline runs for a game, most recent first.",
)
async def get_game_pipeline_runs(
    game_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    include_game_info: bool = Query(default=True),
    session: AsyncSession = Depends(get_db),
) -> GamePipelineRunsResponse:
    """List all pipeline runs for a game."""
    result = await session.execute(
        select(GamePipelineRun)
        .options(selectinload(GamePipelineRun.stages))
        .where(GamePipelineRun.game_id == game_id)
        .order_by(GamePipelineRun.created_at.desc())
        .limit(limit)
    )
    runs = result.scalars().all()

    game_info: dict[str, Any] = {}
    latest_artifact_at = None

    if include_game_info:
        game_result = await session.execute(
            select(SportsGame)
            .options(
                selectinload(SportsGame.home_team),
                selectinload(SportsGame.away_team),
            )
            .where(SportsGame.id == game_id)
        )
        game = game_result.scalar_one_or_none()

        if game:
            game_info = {
                "game_id": game.id,
                "game_date": game.game_date.isoformat() if game.game_date else None,
                "home_team": game.home_team.name if game.home_team else "Unknown",
                "away_team": game.away_team.name if game.away_team else "Unknown",
                "status": game.status,
            }

            artifact_result = await session.execute(
                select(SportsGameTimelineArtifact)
                .where(SportsGameTimelineArtifact.game_id == game_id)
                .order_by(SportsGameTimelineArtifact.generated_at.desc())
                .limit(1)
            )
            artifact = artifact_result.scalar_one_or_none()
            if artifact:
                latest_artifact_at = artifact.generated_at.isoformat()

    has_successful = any(r.status == "completed" for r in runs)

    return GamePipelineRunsResponse(
        game_id=game_id,
        game_info=game_info,
        runs=[build_run_summary(r) for r in runs],
        total_runs=len(runs),
        has_successful_run=has_successful,
        latest_artifact_at=latest_artifact_at,
    )


@router.get(
    "/pipeline/game/{game_id}/summary",
    response_model=GamePipelineSummary,
    summary="Get game pipeline summary",
    description="Quick overview of pipeline state for a game.",
)
async def get_game_pipeline_summary(
    game_id: int,
    session: AsyncSession = Depends(get_db),
) -> GamePipelineSummary:
    """Get a quick summary of pipeline state for a game."""
    game_result = await session.execute(
        select(SportsGame)
        .options(
            selectinload(SportsGame.home_team),
            selectinload(SportsGame.away_team),
        )
        .where(SportsGame.id == game_id)
    )
    game = game_result.scalar_one_or_none()

    if not game:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Game {game_id} not found",
        )

    pbp_result = await session.execute(
        select(func.count(SportsGamePlay.id)).where(SportsGamePlay.game_id == game_id)
    )
    has_pbp = (pbp_result.scalar() or 0) > 0

    artifact_result = await session.execute(
        select(SportsGameTimelineArtifact)
        .where(SportsGameTimelineArtifact.game_id == game_id)
        .order_by(SportsGameTimelineArtifact.generated_at.desc())
        .limit(1)
    )
    artifact = artifact_result.scalar_one_or_none()

    runs_result = await session.execute(
        select(GamePipelineRun)
        .options(selectinload(GamePipelineRun.stages))
        .where(GamePipelineRun.game_id == game_id)
        .order_by(GamePipelineRun.created_at.desc())
    )
    runs = runs_result.scalars().all()

    latest_run = build_run_summary(runs[0]) if runs else None

    return GamePipelineSummary(
        game_id=game_id,
        game_date=game.game_date.isoformat() if game.game_date else "",
        home_team=game.home_team.name if game.home_team else "Unknown",
        away_team=game.away_team.name if game.away_team else "Unknown",
        game_status=game.status,
        has_pbp=has_pbp,
        has_timeline_artifact=artifact is not None,
        latest_artifact_at=artifact.generated_at.isoformat() if artifact else None,
        total_pipeline_runs=len(runs),
        latest_run=latest_run,
        can_run_pipeline=GameStatus.is_final_or_post_final_status(game.status) and has_pbp,
    )
