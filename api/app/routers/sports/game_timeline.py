"""Timeline artifact endpoints (admin).

The deprecated game-flow endpoint that previously lived here was removed in
the v3-summary cutover. Consumers use ``GET /api/v1/games/{id}/summary``.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from ...db import AsyncSession, get_db
from ...db.flow import SportsGameTimelineArtifact
from ...services.timeline_generator import (
    TimelineGenerationError,
    generate_timeline_artifact,
)
from ...services.timeline_types import DEFAULT_TIMELINE_VERSION
from .schemas import TimelineArtifactResponse

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/games/{game_id}/timeline", response_model=TimelineArtifactResponse)
async def get_game_timeline(
    game_id: int,
    timeline_version: str = Query(DEFAULT_TIMELINE_VERSION),
    session: AsyncSession = Depends(get_db),
) -> TimelineArtifactResponse:
    """Retrieve a persisted timeline artifact for a game."""
    result = await session.execute(
        select(SportsGameTimelineArtifact).where(
            SportsGameTimelineArtifact.game_id == game_id,
            SportsGameTimelineArtifact.timeline_version == timeline_version,
        )
    )
    artifact = result.scalar_one_or_none()
    if not artifact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No timeline artifact found for game {game_id} (version={timeline_version})",
        )

    return TimelineArtifactResponse(
        game_id=artifact.game_id,
        sport=artifact.sport,
        timeline_version=artifact.timeline_version,
        generated_at=artifact.generated_at,
        timeline=artifact.timeline_json,
        summary=artifact.summary_json,
        game_analysis=artifact.game_analysis_json,
    )


@router.post(
    "/games/{game_id}/timeline/generate", response_model=TimelineArtifactResponse
)
async def generate_game_timeline(
    game_id: int,
    session: AsyncSession = Depends(get_db),
) -> TimelineArtifactResponse:
    """Generate and store a finalized timeline artifact for any league."""
    try:
        artifact = await generate_timeline_artifact(session, game_id)
    except TimelineGenerationError as exc:
        logger.warning(
            "timeline_generation_failed",
            extra={"game_id": game_id, "status_code": exc.status_code, "error": str(exc)},
        )
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    await session.commit()
    return TimelineArtifactResponse(
        game_id=artifact.game_id,
        sport=artifact.sport,
        timeline_version=artifact.timeline_version,
        generated_at=artifact.generated_at,
        timeline=artifact.timeline,
        summary=artifact.summary,
        game_analysis=artifact.game_analysis,
    )
