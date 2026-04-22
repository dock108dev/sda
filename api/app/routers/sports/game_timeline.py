"""Timeline and game flow endpoints."""

from __future__ import annotations

import logging
import math
from datetime import timedelta, timezone
from datetime import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ...db import AsyncSession, get_db
from ...db.flow import SportsGameFlow, SportsGameTimelineArtifact
from ...db.sports import GameStatus, SportsGame, SportsGamePlay
from ...services.team_colors import get_matchup_colors
from ...services.timeline_generator import (
    TimelineGenerationError,
    generate_timeline_artifact,
)
from ...services.timeline_types import DEFAULT_TIMELINE_VERSION
from .schemas import (
    FlowStatusResponse,
    GameFlowBlock,
    GameFlowContent,
    GameFlowMoment,
    GameFlowPlay,
    GameFlowResponse,
    ScoreObject,
    TimelineArtifactResponse,
)
from .schemas.common import _score_obj

router = APIRouter()
logger = logging.getLogger(__name__)

# Flow version identifiers. See docs/gameflow/version-semantics.md.
FLOW_VERSION = "v2-blocks"

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
    now = dt.now(timezone.utc)
    end = game.end_time
    if end is not None and end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    eta_dt = (end if end else now) + timedelta(minutes=15)
    return max(0, math.ceil((eta_dt - now).total_seconds() / 60))


def _to_score(raw: list | None) -> ScoreObject:
    """Convert [home, away] list from pipeline JSON to ScoreObject."""
    if raw and len(raw) >= 2:
        return ScoreObject(home=raw[0], away=raw[1])
    return ScoreObject(home=0, away=0)


def _block_clock(
    moments: list[dict], block: dict, edge: str,
) -> str | None:
    """Derive block start/end clock from its moments (fallback for older flows)."""
    indices = block.get("moment_indices", [])
    if not indices:
        return None
    idx = indices[0] if edge == "start" else indices[-1]
    if idx < 0 or idx >= len(moments):
        return None
    m = moments[idx]
    return m.get("start_clock") if edge == "start" else m.get("end_clock")


@router.get("/games/{game_id}/timeline", response_model=TimelineArtifactResponse)
async def get_game_timeline(
    game_id: int,
    timeline_version: str = Query(DEFAULT_TIMELINE_VERSION),
    session: AsyncSession = Depends(get_db),
) -> TimelineArtifactResponse:
    """Retrieve a persisted timeline artifact for a game.

    Returns the timeline exactly as persisted. Use the POST generate
    endpoint to create or regenerate a timeline.
    """
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
    """Generate and store a finalized timeline artifact for any league.

    Social data is optional and gracefully degrades to empty for leagues
    without social scraping configured (NHL, NCAAB).
    """
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


@router.get(
    "/games/{game_id}/flow",
    deprecated=True,
    summary="Get game flow (admin — deprecated, use /api/v1/games/{id}/flow)",
)
async def get_game_flow(
    game_id: int,
    session: AsyncSession = Depends(get_db),
) -> GameFlowResponse | FlowStatusResponse:
    """Get the persisted Game Flow for a game.

    .. deprecated::
        Use ``GET /api/v1/games/{game_id}/flow`` instead. This admin endpoint
        returns pipeline-internal fields (validationPassed, validationErrors)
        and will be removed in a future release.

    When a flow is not yet available:
    - FINAL game with no flow → 200 with {status: RECAP_PENDING, etaMinutes: N}
    - Non-final game → 200 with {status: PREGAME | IN_PROGRESS | ...}
    - Unknown game → 404

    Returns:
        GameFlowResponse with moments, plays, blocks, and validation status,
        or FlowStatusResponse when the flow is not yet available.

    Raises:
        HTTPException 404: If the game does not exist
    """
    flow_result = await session.execute(
        select(SportsGameFlow).where(
            SportsGameFlow.game_id == game_id,
            SportsGameFlow.story_version == FLOW_VERSION,
            SportsGameFlow.blocks_json.isnot(None),
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
        flow_status = _GAME_STATUS_TO_FLOW_STATUS.get(game_row.status, game_row.status.upper())
        return FlowStatusResponse(gameId=game_id, status=flow_status)

    # Load game with teams and league for color/metadata fields
    game_result = await session.execute(
        select(SportsGame).options(
            selectinload(SportsGame.home_team),
            selectinload(SportsGame.away_team),
            selectinload(SportsGame.league),
        ).where(SportsGame.id == game_id)
    )
    game = game_result.scalar_one_or_none()

    matchup_colors = get_matchup_colors(
        game.home_team.color_light_hex if game and game.home_team else None,
        game.home_team.color_dark_hex if game and game.home_team else None,
        game.away_team.color_light_hex if game and game.away_team else None,
        game.away_team.color_dark_hex if game and game.away_team else None,
        away_secondary_light=game.away_team.color_secondary_light_hex if game and game.away_team else None,
        away_secondary_dark=game.away_team.color_secondary_dark_hex if game and game.away_team else None,
    )

    # Get moments from persisted data (no transformation)
    moments_data = flow_record.moments_json or []

    # Collect all play_ids referenced by moments
    all_play_ids: set[int] = set()
    for moment in moments_data:
        all_play_ids.update(moment.get("play_ids", []))

    # Load plays by play_ids
    plays_result = await session.execute(
        select(SportsGamePlay).where(
            SportsGamePlay.game_id == game_id,
            SportsGamePlay.play_index.in_(all_play_ids),
        )
    )
    plays_records = plays_result.scalars().all()

    # Build play lookup for ordering
    play_lookup = {p.play_index: p for p in plays_records}

    # Build response moments (exact data, no transformation)
    response_moments = [
        GameFlowMoment(
            playIds=moment.get("play_ids", []),
            explicitlyNarratedPlayIds=moment.get("explicitly_narrated_play_ids", []),
            period=moment.get("period", 1),
            startClock=moment.get("start_clock"),
            endClock=moment.get("end_clock"),
            scoreBefore=_to_score(moment.get("score_before")),
            scoreAfter=_to_score(moment.get("score_after")),
            narrative=moment.get("narrative"),
            cumulativeBoxScore=moment.get("cumulative_box_score"),
        )
        for moment in moments_data
    ]

    # Build response plays (only those referenced by moments, ordered by play_index)
    # NOTE: playId uses play_index (not DB id) to match moment.playIds contract
    response_plays = [
        GameFlowPlay(
            playId=play.play_index,
            playIndex=play.play_index,
            period=play.quarter or 1,
            clock=play.game_clock,
            playType=play.play_type,
            description=play.description,
            score=_score_obj(play.home_score, play.away_score),
        )
        for play_index in sorted(all_play_ids)
        if (play := play_lookup.get(play_index))
    ]

    # Build response blocks if present
    response_blocks: list[GameFlowBlock] | None = None
    total_words: int | None = None

    blocks_data = flow_record.blocks_json
    if blocks_data:
        response_blocks = []
        for idx, block in enumerate(blocks_data):
            role = block.get("role")
            if not role:
                logger.warning(
                    "Block %d missing required 'role', skipping",
                    idx,
                    extra={"game_id": game_id},
                )
                continue
            response_blocks.append(
                GameFlowBlock(
                    blockIndex=block.get("block_index", idx),
                    role=role,
                    momentIndices=block.get("moment_indices", []),
                    periodStart=block.get("period_start", 1),
                    periodEnd=block.get("period_end", 1),
                    scoreBefore=_to_score(block.get("score_before")),
                    scoreAfter=_to_score(block.get("score_after")),
                    playIds=block.get("play_ids", []),
                    keyPlayIds=block.get("key_play_ids", []),
                    narrative=block.get("narrative"),
                    miniBox=block.get("mini_box"),
                    embeddedSocialPostId=block.get("embedded_social_post_id"),
                    startClock=block.get("start_clock") or _block_clock(moments_data, block, "start"),
                    endClock=block.get("end_clock") or _block_clock(moments_data, block, "end"),
                )
            )
        # Calculate total words from accepted block narratives
        total_words = sum(
            len((b.narrative or "").split())
            for b in response_blocks
        )

    # Validation status from persisted data
    validation_passed = flow_record.validated_at is not None

    return GameFlowResponse(
        gameId=game_id,
        flow=GameFlowContent(moments=response_moments),
        plays=response_plays,
        validationPassed=validation_passed,
        validationErrors=[],
        blocks=response_blocks,
        totalWords=total_words,
        homeTeam=game.home_team.name if game and game.home_team else None,
        awayTeam=game.away_team.name if game and game.away_team else None,
        homeTeamAbbr=game.home_team.abbreviation if game and game.home_team else None,
        awayTeamAbbr=game.away_team.abbreviation if game and game.away_team else None,
        homeTeamColorLight=matchup_colors["homeLightHex"],
        homeTeamColorDark=matchup_colors["homeDarkHex"],
        awayTeamColorLight=matchup_colors["awayLightHex"],
        awayTeamColorDark=matchup_colors["awayDarkHex"],
        leagueCode=game.league.code if game and game.league else None,
    )
