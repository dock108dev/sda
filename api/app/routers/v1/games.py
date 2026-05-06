"""Consumer game endpoints — /api/v1/games/*."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db import AsyncSession, get_db
from app.db.flow import SportsGameFlow
from app.db.sports import GameStatus, SportsGame, SportsGamePlay
from app.routers.sports.game_timeline import (
    _GAME_STATUS_TO_FLOW_STATUS,
    FLOW_VERSION,
    _compute_eta_minutes,
    _to_score,
)
from app.routers.sports.schemas import (
    ConsumerGameFlowResponse,
    FlowStatusResponse,
    GameFlowBlock,
    GameFlowPlay,
)
from app.routers.sports.schemas.common import _score_obj
from app.services.team_colors import get_matchup_colors

router = APIRouter()
logger = logging.getLogger(__name__)


def _consumer_validation_view(
    validation: dict | None,
) -> dict | None:
    """Strip pipeline-internal warning detail from the consumer validation block.

    The persisted `validation` JSONB carries `{status, warnings}` where the
    `warnings` list can quote specific narrative substrings that tripped the
    banned-phrase / speculation gates (e.g. "Block 2: banned phrases detected
    — ['set the tone']"). That detail is useful for admin debugging but
    leaking it on the public consumer endpoint discloses internal validator
    design and gives an exploitable signal for adversarial prompt crafting
    against the LLM stage. Only the coarse status is consumer-safe.
    """
    if not validation:
        return validation
    status_value = validation.get("status")
    return {"status": status_value} if status_value is not None else None


@router.get(
    "/games/{game_id}/flow",
    summary="Get game flow (consumer)",
    responses={
        200: {
            "description": (
                "Flow data when available, or status object (RECAP_PENDING / "
                "PREGAME / IN_PROGRESS / POSTPONED / CANCELED) when not."
            ),
        },
        404: {"description": "Game not found"},
    },
)
async def get_game_flow(
    game_id: int,
    session: AsyncSession = Depends(get_db),
) -> ConsumerGameFlowResponse | FlowStatusResponse:
    """Retrieve the consumer-safe Game Flow for a game.

    Returns:
        ConsumerGameFlowResponse when flow data is available.
        FlowStatusResponse when the game exists but flow is not yet ready.

    Raises:
        HTTPException 404: Game not found.
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

    matchup_colors = get_matchup_colors(
        game.home_team.color_light_hex if game and game.home_team else None,
        game.home_team.color_dark_hex if game and game.home_team else None,
        game.away_team.color_light_hex if game and game.away_team else None,
        game.away_team.color_dark_hex if game and game.away_team else None,
        away_secondary_light=game.away_team.color_secondary_light_hex if game and game.away_team else None,
        away_secondary_dark=game.away_team.color_secondary_dark_hex if game and game.away_team else None,
    )

    blocks_data = flow_record.blocks_json or []

    all_play_ids: set[int] = set()
    for block in blocks_data:
        all_play_ids.update(block.get("play_ids", []))

    plays_result = await session.execute(
        select(SportsGamePlay).where(
            SportsGamePlay.game_id == game_id,
            SportsGamePlay.play_index.in_(all_play_ids),
        )
    )
    plays_records = plays_result.scalars().all()
    play_lookup = {p.play_index: p for p in plays_records}

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

    response_blocks: list[GameFlowBlock] = []
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
                startClock=block.get("start_clock"),
                endClock=block.get("end_clock"),
                reason=block.get("reason"),
                label=block.get("label"),
                leadBefore=block.get("lead_before"),
                leadAfter=block.get("lead_after"),
                evidence=block.get("evidence"),
                storyRole=block.get("story_role"),
                leverage=block.get("leverage"),
                periodRange=block.get("period_range"),
                featuredPlayers=block.get("featured_players"),
                scoreContext=block.get("score_context"),
            )
        )
    total_words = sum(len((b.narrative or "").split()) for b in response_blocks)

    return ConsumerGameFlowResponse(
        gameId=game_id,
        plays=response_plays,
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
        version=flow_record.version,
        archetype=flow_record.archetype,
        winnerTeamId=flow_record.winner_team_id,
        sourceCounts=flow_record.source_counts,
        validation=_consumer_validation_view(flow_record.validation),
    )
