"""Pipeline stage detail and metadata endpoints.

Get stage logs, outputs, compare across runs, and list available stages.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ....db import AsyncSession, get_db
from ....services.pipeline.models import PipelineStage
from .helpers import (
    get_run_with_stages,
    get_stage_description,
    get_stage_record,
    summarize_output,
    validate_pipeline_stage,
)
from .models import (
    StageComparisonResponse,
    StageLogsResponse,
    StageOutputResponse,
)

router = APIRouter()


@router.get(
    "/pipeline/run/{run_id}/stage/{stage}/logs",
    response_model=StageLogsResponse,
    summary="Get stage logs",
    description="Get all log entries from a specific stage execution.",
)
async def get_stage_logs(
    run_id: int,
    stage: str,
    session: AsyncSession = Depends(get_db),
) -> StageLogsResponse:
    """Get logs from a specific stage."""
    validate_pipeline_stage(stage)

    run = await get_run_with_stages(session, run_id)
    stage_record = get_stage_record(run, stage)

    logs = stage_record.logs_json or []

    return StageLogsResponse(
        run_id=run_id,
        run_uuid=str(run.run_uuid),
        stage=stage,
        status=stage_record.status,
        logs=logs,
        log_count=len(logs),
    )


@router.get(
    "/pipeline/run/{run_id}/stage/{stage}/output",
    response_model=StageOutputResponse,
    summary="Get stage output",
    description="Get the full output data from a specific stage execution.",
)
async def get_stage_output(
    run_id: int,
    stage: str,
    session: AsyncSession = Depends(get_db),
) -> StageOutputResponse:
    """Get full output from a specific stage."""
    validate_pipeline_stage(stage)

    run = await get_run_with_stages(session, run_id)
    stage_record = get_stage_record(run, stage)

    output = stage_record.output_json
    summary = summarize_output(stage, output) if output else {}

    return StageOutputResponse(
        run_id=run_id,
        run_uuid=str(run.run_uuid),
        stage=stage,
        status=stage_record.status,
        output_json=output,
        output_summary=summary,
        generated_at=(stage_record.finished_at.isoformat() if stage_record.finished_at else None),
    )


@router.get(
    "/pipeline/game/{game_id}/compare/{stage}",
    response_model=StageComparisonResponse,
    summary="Compare stage outputs",
    description="Compare a stage's output between two runs.",
)
async def compare_stage_outputs(
    game_id: int,
    stage: str,
    run_a_id: int = Query(..., description="First run ID"),
    run_b_id: int = Query(..., description="Second run ID"),
    session: AsyncSession = Depends(get_db),
) -> StageComparisonResponse:
    """Compare a stage's output between two runs."""
    validate_pipeline_stage(stage)

    run_a = await get_run_with_stages(session, run_a_id)
    run_b = await get_run_with_stages(session, run_b_id)

    if run_a.game_id != game_id or run_b.game_id != game_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Both runs must be for the specified game",
        )

    stage_a = get_stage_record(run_a, stage, raise_not_found=False)
    stage_b = get_stage_record(run_b, stage, raise_not_found=False)

    if not stage_a or not stage_b:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Stage {stage} not found in one or both runs",
        )

    output_a = stage_a.output_json or {}
    output_b = stage_b.output_json or {}

    differences: dict[str, Any] = {}

    if stage == "GENERATE_SUMMARY":
        a_paragraphs = len(output_a.get("summary", []) or [])
        b_paragraphs = len(output_b.get("summary", []) or [])
        differences["paragraph_count_delta"] = b_paragraphs - a_paragraphs
        differences["model_a"] = output_a.get("model_used")
        differences["model_b"] = output_b.get("model_used")

    return StageComparisonResponse(
        game_id=game_id,
        stage=stage,
        run_a={
            "run_id": run_a.id,
            "run_uuid": str(run_a.run_uuid),
            "created_at": run_a.created_at.isoformat(),
            "status": stage_a.status,
            "output_summary": summarize_output(stage, output_a),
        },
        run_b={
            "run_id": run_b.id,
            "run_uuid": str(run_b.run_uuid),
            "created_at": run_b.created_at.isoformat(),
            "status": stage_b.status,
            "output_summary": summarize_output(stage, output_b),
        },
        differences=differences,
    )


@router.get(
    "/pipeline/stages",
    summary="List pipeline stages",
    description="Get the ordered list of pipeline stages with descriptions.",
)
async def list_pipeline_stages() -> dict[str, Any]:
    """List all pipeline stages with metadata."""
    stages = []
    for i, stage in enumerate(PipelineStage.ordered_stages()):
        stages.append(
            {
                "name": stage.value,
                "order": i + 1,
                "description": get_stage_description(stage),
                "next_stage": stage.next_stage().value if stage.next_stage() else None,
                "previous_stage": (
                    stage.previous_stage().value if stage.previous_stage() else None
                ),
            }
        )

    return {
        "stages": stages,
        "total_stages": len(stages),
    }
