"""PBP comparison and resolution issue endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from ...db import AsyncSession, get_db
from ...db.resolution import PBPSnapshot
from ...db.sports import SportsGamePlay
from .pbp_helpers import build_resolution_issues
from .pbp_models import PBPComparisonResponse

router = APIRouter()


# =============================================================================
# ENDPOINTS - Comparison
# =============================================================================


@router.get(
    "/pbp/game/{game_id}/compare",
    response_model=PBPComparisonResponse,
    summary="Compare current PBP with snapshot",
    description="Compare current PBP data with a specific snapshot.",
)
async def compare_pbp(
    game_id: int,
    snapshot_id: int = Query(..., description="Snapshot to compare against"),
    session: AsyncSession = Depends(get_db),
) -> PBPComparisonResponse:
    """Compare current PBP with a snapshot.

    Useful for debugging differences between raw and processed data.
    """
    # Get current play count
    current_count_result = await session.execute(
        select(func.count(SportsGamePlay.id)).where(
            SportsGamePlay.game_id == game_id
        )
    )
    current_count = current_count_result.scalar() or 0

    # Get snapshot
    snapshot_result = await session.execute(
        select(PBPSnapshot).where(PBPSnapshot.id == snapshot_id)
    )
    snapshot = snapshot_result.scalar_one_or_none()

    if not snapshot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"PBP snapshot {snapshot_id} not found",
        )

    if snapshot.game_id != game_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Snapshot does not belong to this game",
        )

    # Calculate differences
    differences = {
        "play_count_delta": current_count - snapshot.play_count,
        "snapshot_type": snapshot.snapshot_type,
        "snapshot_created_at": snapshot.created_at.isoformat(),
    }

    # If counts differ, check for missing/extra plays
    if current_count != snapshot.play_count:
        differences["note"] = (
            f"Current has {abs(current_count - snapshot.play_count)} "
            f"{'more' if current_count > snapshot.play_count else 'fewer'} plays"
        )

    return PBPComparisonResponse(
        game_id=game_id,
        comparison_type=f"current_vs_{snapshot.snapshot_type}",
        current_play_count=current_count,
        snapshot_play_count=snapshot.play_count,
        differences=differences,
    )


# =============================================================================
# ENDPOINTS - Resolution Issues
# =============================================================================


@router.get(
    "/pbp/game/{game_id}/resolution-issues",
    summary="Get PBP resolution issues",
    description="List plays with resolution issues (missing team, player, etc.).",
)
async def get_resolution_issues(
    game_id: int,
    issue_type: str = Query(
        default="all",
        description="Type of issue: team, player, score, all",
    ),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get plays with resolution issues.

    Helps debug data quality problems in PBP ingestion.
    """
    # Fetch all plays
    plays_result = await session.execute(
        select(SportsGamePlay)
        .options(selectinload(SportsGamePlay.team))
        .where(SportsGamePlay.game_id == game_id)
        .order_by(SportsGamePlay.play_index)
    )
    plays = list(plays_result.scalars().all())

    result = build_resolution_issues(plays, issue_type)

    return {
        "game_id": game_id,
        "total_plays": len(plays),
        "issue_type_filter": issue_type,
        **result,
    }
