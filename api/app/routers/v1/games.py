"""Consumer game endpoints — /api/v1/games/*."""

from __future__ import annotations

import logging
import math
from datetime import UTC, timedelta
from datetime import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db import AsyncSession, get_db
from app.db.flow import SportsGameFlow
from app.db.sports import GameStatus, SportsGame
from app.routers.sports.schemas import (
    FlowStatusResponse,
    GameSummaryResponse,
    SummaryFinalScore,
)
from app.services.pipeline.stages.finalize_summary import SUMMARY_STORY_VERSION

router = APIRouter()
logger = logging.getLogger(__name__)


_GAME_STATUS_TO_FLOW_STATUS: dict[str, str] = {
    GameStatus.live.value: "IN_PROGRESS",
    GameStatus.pregame.value: "PREGAME",
    GameStatus.scheduled.value: "PREGAME",
    GameStatus.postponed.value: "POSTPONED",
    GameStatus.CANCELLED.value: "CANCELED",
    GameStatus.archived.value: "RECAP_PENDING",
}


def _compute_eta_minutes(game: SportsGame) -> int:
    """Minutes until recap is expected (clamped to 0 when overdue)."""
    now = dt.now(UTC)
    end = game.end_time
    if end is not None and end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    eta_dt = (end if end else now) + timedelta(minutes=15)
    return max(0, math.ceil((eta_dt - now).total_seconds() / 60))


@router.get(
    "/games/{game_id}/summary",
    summary="Get the catch-up summary for a completed game",
    responses={
        200: {
            "description": (
                "Summary when available, or status object (RECAP_PENDING / "
                "PREGAME / IN_PROGRESS / POSTPONED / CANCELED) when not."
            ),
        },
        404: {"description": "Game not found"},
    },
)
async def get_game_summary(
    game_id: int,
    session: AsyncSession = Depends(get_db),
) -> GameSummaryResponse | FlowStatusResponse:
    """Return the cached catch-up summary for a completed game.

    The summary is generated once per game and cached indefinitely. Calls
    after the first generation are served from sports_game_stories.
    """
    flow_result = await session.execute(
        select(SportsGameFlow).where(
            SportsGameFlow.game_id == game_id,
            SportsGameFlow.story_version == SUMMARY_STORY_VERSION,
            SportsGameFlow.summary_json.isnot(None),
        )
    )
    flow_record = flow_result.scalar_one_or_none()

    if not flow_record:
        game_result = await session.execute(
            select(SportsGame).where(SportsGame.id == game_id)
        )
        game_row = game_result.scalar_one_or_none()
        if not game_row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Game {game_id} not found",
            )
        if game_row.status == GameStatus.final.value:
            return FlowStatusResponse(
                gameId=game_id,
                status="RECAP_PENDING",
                etaMinutes=_compute_eta_minutes(game_row),
            )
        flow_status = _GAME_STATUS_TO_FLOW_STATUS.get(
            game_row.status, game_row.status.upper()
        )
        return FlowStatusResponse(gameId=game_id, status=flow_status)

    game_result = await session.execute(
        select(SportsGame)
        .options(
            selectinload(SportsGame.home_team),
            selectinload(SportsGame.away_team),
            selectinload(SportsGame.league),
        )
        .where(SportsGame.id == game_id)
    )
    game = game_result.scalar_one_or_none()

    payload = flow_record.summary_json or {}
    summary_paragraphs: list[str] = list(payload.get("summary") or [])
    referenced_play_ids: list[int] = list(payload.get("referenced_play_ids") or [])
    home_final = int(payload.get("home_final") or 0)
    away_final = int(payload.get("away_final") or 0)

    return GameSummaryResponse(
        gameId=game_id,
        sport=flow_record.sport,
        finalScore=SummaryFinalScore(
            home=home_final,
            away=away_final,
            homeAbbr=game.home_team.abbreviation if game and game.home_team else None,
            awayAbbr=game.away_team.abbreviation if game and game.away_team else None,
        ),
        summary=summary_paragraphs,
        referencedPlayIds=referenced_play_ids,
        archetype=flow_record.archetype,
        generatedAt=flow_record.generated_at,
        modelUsed=flow_record.ai_model_used,
        storyVersion=flow_record.story_version,
        homeTeam=game.home_team.name if game and game.home_team else None,
        awayTeam=game.away_team.name if game and game.away_team else None,
        leagueCode=game.league.code if game and game.league else None,
    )
