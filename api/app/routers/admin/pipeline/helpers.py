"""Pipeline router helper functions.

This module contains helper functions used across pipeline endpoints.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ....db import AsyncSession
from ....db.pipeline import GamePipelineRun, GamePipelineStage
from ....services.pipeline.models import PipelineStage
from .models import (
    PipelineRunResponse,
    PipelineRunSummary,
    StageStatusResponse,
)


def build_stage_status(
    stage_record: GamePipelineStage,
    stage_order: int,
    can_execute: bool,
) -> StageStatusResponse:
    """Build a StageStatusResponse from a stage record."""
    duration = None
    if stage_record.started_at and stage_record.finished_at:
        duration = (stage_record.finished_at - stage_record.started_at).total_seconds()

    output_summary = None
    if stage_record.output_json:
        output_summary = summarize_output(stage_record.stage, stage_record.output_json)

    return StageStatusResponse(
        stage=stage_record.stage,
        stage_order=stage_order,
        status=stage_record.status,
        started_at=(stage_record.started_at.isoformat() if stage_record.started_at else None),
        finished_at=(stage_record.finished_at.isoformat() if stage_record.finished_at else None),
        duration_seconds=duration,
        error_details=stage_record.error_details,
        has_output=stage_record.output_json is not None,
        output_summary=output_summary,
        log_count=len(stage_record.logs_json or []),
        can_execute=can_execute,
    )


def summarize_output(stage: str, output: dict[str, Any]) -> dict[str, Any]:
    """Create a summary of stage output for quick viewing."""
    if stage == "NORMALIZE_PBP":
        return {
            "total_plays": output.get("total_plays", 0),
            "has_overtime": output.get("has_overtime", False),
            "phases": list(output.get("phase_boundaries", {}).keys()),
        }
    elif stage == "GENERATE_MOMENTS":
        moments = output.get("moments", [])
        if not moments:
            return {"moment_count": 0}
        sizes = [len(m.get("play_ids", [])) for m in moments]
        narrated = [len(m.get("explicitly_narrated_play_ids", [])) for m in moments]
        scoring = sum(1 for m in moments if m.get("score_before") != m.get("score_after"))
        total_narrated = sum(narrated)
        total_plays = sum(sizes)
        return {
            "moment_count": len(moments),
            "play_count": total_plays,
            "avg_moment_size": round(sum(sizes) / len(sizes), 1) if sizes else 0,
            "scoring_moments": scoring,
            "narrated_plays": total_narrated,
            "narration_pct": round(total_narrated / total_plays * 100, 1) if total_plays else 0,
        }
    elif stage == "VALIDATE_MOMENTS":
        return {
            "validated": output.get("validated", False),
            "error_count": len(output.get("errors", [])),
        }
    elif stage == "CLASSIFY_GAME_SHAPE":
        return {
            "shape_classified": output.get("shape_classified", False),
            "archetype": output.get("archetype"),
        }
    elif stage == "GROUP_BLOCKS":
        # Format: {"blocks_grouped": true, "blocks": [...], "block_count": N}
        return {
            "blocks_grouped": output.get("blocks_grouped", False),
            "block_count": output.get("block_count", 0),
            "lead_changes": output.get("lead_changes", 0),
        }
    elif stage == "RENDER_BLOCKS":
        # Format: {"blocks_rendered": true, "blocks": [...], "total_words": N}
        blocks = output.get("blocks", [])
        return {
            "blocks_rendered": output.get("blocks_rendered", False),
            "block_count": len(blocks),
            "total_words": output.get("total_words", 0),
            "openai_calls": output.get("openai_calls", 0),
        }
    elif stage == "VALIDATE_BLOCKS":
        # Format: {"blocks_validated": true/false, "errors": [...]}
        return {
            "blocks_validated": output.get("blocks_validated", False),
            "error_count": len(output.get("errors", [])),
            "total_words": output.get("total_words", 0),
        }
    elif stage == "FINALIZE_MOMENTS":
        return {
            "finalized": output.get("finalized", False),
            "flow_id": output.get("flow_id"),
            "story_version": output.get("story_version"),
            "moment_count": output.get("moment_count", 0),
        }
    return {}


async def get_run_with_stages(
    session: AsyncSession,
    run_id: int,
) -> GamePipelineRun:
    """Fetch a run with its stages loaded."""
    result = await session.execute(
        select(GamePipelineRun)
        .options(selectinload(GamePipelineRun.stages))
        .where(GamePipelineRun.id == run_id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pipeline run {run_id} not found",
        )
    return run


def build_run_response(run: GamePipelineRun) -> PipelineRunResponse:
    """Build a full PipelineRunResponse from a run."""
    ordered_stages = PipelineStage.ordered_stages()
    stage_map = {s.stage: s for s in run.stages}

    stages = []
    prev_succeeded = True
    completed = 0
    failed = 0
    pending = 0
    next_stage = None

    for i, stage_enum in enumerate(ordered_stages):
        stage_record = stage_map.get(stage_enum.value)
        if not stage_record:
            continue

        is_pending = stage_record.status == "pending"
        can_execute = prev_succeeded and is_pending

        if can_execute and next_stage is None:
            next_stage = stage_enum.value

        stages.append(build_stage_status(stage_record, i + 1, can_execute))

        if stage_record.status == "success":
            completed += 1
            prev_succeeded = True
        elif stage_record.status == "failed":
            failed += 1
            prev_succeeded = False
        elif stage_record.status == "pending":
            pending += 1
        else:
            prev_succeeded = False

    total_stages = len(ordered_stages)
    progress = int((completed / total_stages) * 100) if total_stages > 0 else 0

    duration = None
    if run.started_at and run.finished_at:
        duration = (run.finished_at - run.started_at).total_seconds()

    return PipelineRunResponse(
        run_id=run.id,
        run_uuid=str(run.run_uuid),
        game_id=run.game_id,
        triggered_by=run.triggered_by,
        auto_chain=run.auto_chain,
        status=run.status,
        current_stage=run.current_stage,
        started_at=run.started_at.isoformat() if run.started_at else None,
        finished_at=run.finished_at.isoformat() if run.finished_at else None,
        duration_seconds=duration,
        created_at=run.created_at.isoformat(),
        stages=stages,
        stages_completed=completed,
        stages_failed=failed,
        stages_pending=pending,
        progress_percent=progress,
        can_continue=run.status in ("pending", "paused", "running") and pending > 0,
        next_stage=next_stage,
    )


def build_run_summary(run: GamePipelineRun) -> PipelineRunSummary:
    """Build a PipelineRunSummary from a run, including per-stage detail."""
    ordered_stages = PipelineStage.ordered_stages()
    stage_map = {s.stage: s for s in run.stages}

    stages: list[StageStatusResponse] = []
    prev_succeeded = True
    completed = 0

    for i, stage_enum in enumerate(ordered_stages):
        stage_record = stage_map.get(stage_enum.value)
        if not stage_record:
            continue

        is_pending = stage_record.status == "pending"
        can_execute = prev_succeeded and is_pending
        stages.append(build_stage_status(stage_record, i + 1, can_execute))

        if stage_record.status == "success":
            completed += 1
            prev_succeeded = True
        elif stage_record.status in ("failed", "running"):
            prev_succeeded = False

    total = len(run.stages)
    progress = int((completed / total) * 100) if total > 0 else 0

    return PipelineRunSummary(
        run_id=run.id,
        run_uuid=str(run.run_uuid),
        game_id=run.game_id,
        triggered_by=run.triggered_by,
        status=run.status,
        current_stage=run.current_stage,
        created_at=run.created_at.isoformat(),
        started_at=run.started_at.isoformat() if run.started_at else None,
        finished_at=run.finished_at.isoformat() if run.finished_at else None,
        stages_completed=completed,
        stages_total=total,
        progress_percent=progress,
        stages=stages,
    )


def validate_pipeline_stage(stage: str) -> PipelineStage:
    """Validate a stage string and return the corresponding PipelineStage.

    Raises HTTPException 400 if the stage is invalid.
    """
    try:
        return PipelineStage(stage)
    except ValueError as exc:
        valid_stages = [s.value for s in PipelineStage]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid stage: {stage}. Valid stages: {valid_stages}",
        ) from exc


def get_stage_record(
    run: GamePipelineRun,
    stage: str,
    *,
    raise_not_found: bool = True,
) -> GamePipelineStage | None:
    """Find a stage record in a run's stages.

    If raise_not_found is True (default), raises HTTPException 404 when stage
    is not found.  Otherwise returns None.
    """
    record = next((s for s in run.stages if s.stage == stage), None)
    if record is None and raise_not_found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Stage {stage} not found for run {run.id}",
        )
    return record


def get_stage_description(stage: PipelineStage) -> str:
    """Get human-readable description for a stage."""
    descriptions = {
        PipelineStage.NORMALIZE_PBP: "Read PBP data from database and normalize with phase assignments",
        PipelineStage.GENERATE_MOMENTS: "Segment plays into condensed moments with explicit narration targets",
        PipelineStage.VALIDATE_MOMENTS: "Validate moment structure, ordering, and coverage",
        PipelineStage.ANALYZE_DRAMA: "Compute deterministic per-quarter drama weights for block distribution",
        PipelineStage.CLASSIFY_GAME_SHAPE: "Deterministically classify the game's archetype (wire-to-wire, comeback, blowout, etc.)",
        PipelineStage.GROUP_BLOCKS: "Group moments into 4-7 narrative blocks with semantic roles",
        PipelineStage.RENDER_BLOCKS: "Generate short narratives for each block using OpenAI",
        PipelineStage.VALIDATE_BLOCKS: "Validate block count, word limits, and constraints",
        PipelineStage.FINALIZE_MOMENTS: "Persist moments and blocks to game flow tables",
    }
    return descriptions.get(stage, "Unknown stage")
