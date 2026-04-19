"""Pipeline run management endpoints.

Start, re-run, execute individual stages, continue, and run full pipeline.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select

from ....db import AsyncSession, get_db
from ....db.pipeline import GamePipelineRun
from ....services.pipeline import PipelineExecutor
from ....services.pipeline.executor import PipelineExecutionError
from ....services.pipeline.models import PipelineStage
from .helpers import (
    build_run_response,
    get_run_with_stages,
    get_stage_record,
    summarize_output,
    validate_pipeline_stage,
)
from .models import (
    ContinuePipelineResponse,
    ExecuteStageRequest,
    ExecuteStageResponse,
    RerunPipelineRequest,
    RerunPipelineResponse,
    RunFullPipelineRequest,
    RunFullPipelineResponse,
    StartPipelineRequest,
    StartPipelineResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "/pipeline/{game_id}/start",
    response_model=StartPipelineResponse,
    summary="Start new pipeline run",
    description="Create a new pipeline run for a game.",
)
async def start_pipeline(
    game_id: int,
    request: StartPipelineRequest,
    session: AsyncSession = Depends(get_db),
) -> StartPipelineResponse:
    """Start a new pipeline run for a game."""
    executor = PipelineExecutor(session)

    try:
        run = await executor.start_pipeline(
            game_id=game_id,
            triggered_by=request.triggered_by,
            auto_chain=request.auto_chain,
        )
        await session.commit()

        run = await get_run_with_stages(session, run.id)
        response = build_run_response(run)

        return StartPipelineResponse(
            run_id=run.id,
            run_uuid=str(run.run_uuid),
            game_id=run.game_id,
            status=run.status,
            auto_chain=run.auto_chain,
            stages=response.stages,
            next_stage=PipelineStage.NORMALIZE_PBP.value,
            message=f"Pipeline run created. Execute {PipelineStage.NORMALIZE_PBP.value} to begin.",
        )

    except PipelineExecutionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("start_pipeline_error", extra={"game_id": game_id})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to start pipeline. See server logs for details.",
        )


@router.post(
    "/pipeline/{game_id}/rerun",
    response_model=RerunPipelineResponse,
    summary="Re-run pipeline (creates new run)",
    description="Create a new pipeline run and optionally execute stages.",
)
async def rerun_pipeline(
    game_id: int,
    request: RerunPipelineRequest,
    session: AsyncSession = Depends(get_db),
) -> RerunPipelineResponse:
    """Re-run a pipeline for a game by creating a NEW run."""
    executor = PipelineExecutor(session)

    count_result = await session.execute(
        select(func.count(GamePipelineRun.id)).where(GamePipelineRun.game_id == game_id)
    )
    previous_runs = count_result.scalar() or 0

    try:
        run = await executor.start_pipeline(
            game_id=game_id,
            triggered_by=request.triggered_by,
            auto_chain=False,
        )
        await session.flush()

        stages_executed: list[str] = []
        stages_pending = [s.value for s in PipelineStage.ordered_stages()]

        if request.execute_through_stage:
            try:
                target_stage = PipelineStage(request.execute_through_stage)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid stage: {request.execute_through_stage}",
                )

            for stage in PipelineStage.ordered_stages():
                result = await executor.execute_stage(run.id, stage)
                if result.success:
                    stages_executed.append(stage.value)
                    stages_pending.remove(stage.value)
                else:
                    break

                if stage == target_stage:
                    break

        await session.commit()

        run = await get_run_with_stages(session, run.id)

        return RerunPipelineResponse(
            new_run_id=run.id,
            new_run_uuid=str(run.run_uuid),
            game_id=game_id,
            previous_runs_count=previous_runs,
            status=run.status,
            stages_executed=stages_executed,
            stages_pending=stages_pending,
            message=f"New run created. {len(stages_executed)} stages executed. "
            f"Previous runs preserved ({previous_runs} total).",
        )

    except PipelineExecutionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        logger.exception("rerun_pipeline_error", extra={"game_id": game_id})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to re-run pipeline. See server logs for details.",
        )


@router.post(
    "/pipeline/run/{run_id}/execute/{stage}",
    response_model=ExecuteStageResponse,
    summary="Execute specific stage",
    description="Execute a specific stage within a pipeline run.",
)
async def execute_stage(
    run_id: int,
    stage: str,
    request: ExecuteStageRequest = ExecuteStageRequest(),
    session: AsyncSession = Depends(get_db),
) -> ExecuteStageResponse:
    """Execute a specific stage of a pipeline run."""
    pipeline_stage = validate_pipeline_stage(stage)

    executor = PipelineExecutor(session)

    try:
        result = await executor.execute_stage(run_id, pipeline_stage)
        await session.commit()

        run = await get_run_with_stages(session, run_id)
        next_stage = pipeline_stage.next_stage()

        output_summary = None
        stage_record = get_stage_record(run, stage, raise_not_found=False)
        if stage_record and stage_record.output_json:
            output_summary = summarize_output(stage, stage_record.output_json)

        return ExecuteStageResponse(
            run_id=run_id,
            run_uuid=str(run.run_uuid),
            stage=stage,
            status=stage_record.status if stage_record else "unknown",
            success=result.success,
            duration_seconds=result.duration_seconds,
            error=result.error,
            output_summary=output_summary,
            next_stage=next_stage.value if next_stage else None,
            pipeline_status=run.status,
            message=(
                "Stage completed successfully"
                if result.success
                else f"Stage failed: {result.error}"
            ),
        )

    except PipelineExecutionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        logger.exception("execute_stage_error", extra={"run_id": run_id, "stage": stage})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Stage execution failed. See server logs for details.",
        )


@router.post(
    "/pipeline/run/{run_id}/continue",
    response_model=ContinuePipelineResponse,
    summary="Continue pipeline",
    description="Execute the next pending stage in the pipeline.",
)
async def continue_pipeline(
    run_id: int,
    session: AsyncSession = Depends(get_db),
) -> ContinuePipelineResponse:
    """Continue a paused pipeline by executing the next pending stage."""
    executor = PipelineExecutor(session)

    try:
        result = await executor.execute_next_stage(run_id)
        await session.commit()

        run = await get_run_with_stages(session, run_id)
        response = build_run_response(run)

        if result is None:
            return ContinuePipelineResponse(
                run_id=run_id,
                run_uuid=str(run.run_uuid),
                stage_executed=None,
                success=True,
                duration_seconds=None,
                pipeline_status=run.status,
                stages_completed=response.stages_completed,
                stages_remaining=response.stages_pending,
                next_stage=response.next_stage,
                message="Pipeline already complete or no pending stages",
            )

        return ContinuePipelineResponse(
            run_id=run_id,
            run_uuid=str(run.run_uuid),
            stage_executed=result.stage.value,
            success=result.success,
            duration_seconds=result.duration_seconds,
            pipeline_status=run.status,
            stages_completed=response.stages_completed,
            stages_remaining=response.stages_pending,
            next_stage=response.next_stage,
            message=f"Executed {result.stage.value}: {'success' if result.success else 'failed'}",
        )

    except PipelineExecutionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        logger.exception("continue_pipeline_error", extra={"run_id": run_id})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to continue pipeline. See server logs for details.",
        )


@router.post(
    "/pipeline/{game_id}/run-full",
    response_model=RunFullPipelineResponse,
    summary="Run complete pipeline",
    description="Create a new run and execute all stages.",
)
async def run_full_pipeline(
    game_id: int,
    request: RunFullPipelineRequest,
    session: AsyncSession = Depends(get_db),
) -> RunFullPipelineResponse:
    """Run the complete pipeline for a game in one request."""
    executor = PipelineExecutor(session)

    try:
        run = await executor.run_full_pipeline(
            game_id=game_id,
            triggered_by=request.triggered_by,
            regen_attempt=request.regen_attempt,
            failure_reasons=request.failure_reasons,
        )
        await session.commit()

        run = await get_run_with_stages(session, run.id)

        completed = sum(1 for s in run.stages if s.status == "success")
        failed = sum(1 for s in run.stages if s.status == "failed")

        duration = None
        if run.started_at and run.finished_at:
            duration = (run.finished_at - run.started_at).total_seconds()

        artifact_id = None
        finalize_stage = next(
            (s for s in run.stages if s.stage == "FINALIZE_MOMENTS"),
            None,
        )
        if finalize_stage and finalize_stage.output_json:
            artifact_id = finalize_stage.output_json.get("artifact_id")

        return RunFullPipelineResponse(
            run_id=run.id,
            run_uuid=str(run.run_uuid),
            game_id=run.game_id,
            status=run.status,
            stages_completed=completed,
            stages_failed=failed,
            duration_seconds=duration,
            artifact_id=artifact_id,
            message=f"Pipeline {run.status} with {completed}/{len(run.stages)} stages completed",
        )

    except PipelineExecutionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        logger.exception("run_full_pipeline_error", extra={"game_id": game_id})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Pipeline execution failed. See server logs for details.",
        )
