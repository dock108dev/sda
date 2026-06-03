"""Pipeline Executor - Orchestrates game pipeline stages.

The PipelineExecutor is responsible for:
1. Creating and managing pipeline runs
2. Executing individual stages
3. Managing stage transitions and auto-chaining
4. Accumulating outputs between stages
5. Tracking status and logs

Key behaviors:
- Admin/manual triggers always disable auto-chain
- Prod triggers can enable auto-chain
- Each stage's output is persisted before proceeding
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.metrics import pipeline_stage_failures_total

from ...db import AsyncSession
from ...db.pipeline import GamePipelineRun, GamePipelineStage
from ...db.sports import GameStatus, SportsGame
from ...utils.datetime_utils import now_utc
from .executor_context import accumulate_outputs, get_game_context, resolve_league_code
from .helpers.flow_debug_logger import (
    get_or_create_logger as get_or_create_flow_debug_logger,
)
from .helpers.flow_debug_logger import pop_logger as pop_flow_debug_logger
from .metrics import increment_published, record_stage_duration
from .models import PipelineStage, StageInput, StageOutput, StageResult
from .stages import (
    execute_classify_game_shape,
    execute_finalize_summary,
    execute_generate_summary,
    execute_normalize_pbp,
)

logger = logging.getLogger(__name__)


class PipelineExecutionError(Exception):
    """Raised when pipeline execution fails."""

    def __init__(self, message: str, stage: PipelineStage | None = None):
        super().__init__(message)
        self.stage = stage


class PipelineExecutor:
    """Orchestrates game pipeline execution.

    The executor manages the lifecycle of pipeline runs and stage executions.
    It handles:
    - Creating new pipeline runs
    - Executing individual stages
    - Managing auto-chain behavior
    - Accumulating outputs between stages
    """

    def __init__(self, session: AsyncSession):
        """Initialize executor with a database session.

        Args:
            session: Async database session
        """
        self.session = session

    async def start_pipeline(
        self,
        game_id: int,
        triggered_by: str,
        auto_chain: bool | None = None,
    ) -> GamePipelineRun:
        """Start a new pipeline run for a game.

        Args:
            game_id: Game to process
            triggered_by: Who triggered the run (prod_auto, admin, manual, backfill)
            auto_chain: Whether to auto-proceed (None = infer from triggered_by)

        Returns:
            Created GamePipelineRun record
        """
        # Infer auto_chain from trigger type if not specified
        if auto_chain is None:
            # Only prod_auto gets auto-chain by default
            auto_chain = triggered_by == "prod_auto"

        # Admin and manual NEVER auto-chain
        if triggered_by in ("admin", "manual"):
            auto_chain = False

        logger.info(
            "pipeline_starting",
            extra={
                "game_id": game_id,
                "triggered_by": triggered_by,
                "auto_chain": auto_chain,
            },
        )

        # Verify game exists
        game_result = await self.session.execute(
            select(SportsGame)
            .options(
                selectinload(SportsGame.league),
                selectinload(SportsGame.home_team),
                selectinload(SportsGame.away_team),
            )
            .where(SportsGame.id == game_id)
        )
        game = game_result.scalar_one_or_none()

        if not game:
            raise PipelineExecutionError(f"Game {game_id} not found")

        if not GameStatus.is_final_or_post_final_status(game.status):
            raise PipelineExecutionError(f"Game {game_id} is not final (status: {game.status})")

        # Create pipeline run
        run = GamePipelineRun(
            game_id=game_id,
            triggered_by=triggered_by,
            auto_chain=auto_chain,
            status="pending",
        )
        self.session.add(run)
        await self.session.flush()

        # Create stage records
        for stage in PipelineStage.ordered_stages():
            stage_record = GamePipelineStage(
                run_id=run.id,
                stage=stage.value,
                status="pending",
            )
            self.session.add(stage_record)

        await self.session.flush()

        logger.info(
            "pipeline_created",
            extra={
                "run_id": run.id,
                "run_uuid": str(run.run_uuid),
                "game_id": game_id,
            },
        )

        return run

    async def _get_run(self, run_id: int) -> GamePipelineRun:
        """Fetch pipeline run with stages."""
        result = await self.session.execute(
            select(GamePipelineRun)
            .options(selectinload(GamePipelineRun.stages))
            .where(GamePipelineRun.id == run_id)
        )
        run = result.scalar_one_or_none()

        if not run:
            raise PipelineExecutionError(f"Pipeline run {run_id} not found")

        return run

    async def _get_stage_record(
        self,
        run_id: int,
        stage: PipelineStage,
    ) -> GamePipelineStage:
        """Fetch a specific stage record."""
        result = await self.session.execute(
            select(GamePipelineStage).where(
                GamePipelineStage.run_id == run_id,
                GamePipelineStage.stage == stage.value,
            )
        )
        stage_record = result.scalar_one_or_none()

        if not stage_record:
            raise PipelineExecutionError(f"Stage {stage.value} not found for run {run_id}")

        return stage_record

    async def execute_stage(
        self,
        run_id: int,
        stage: PipelineStage,
    ) -> StageResult:
        """Execute a specific stage of the pipeline.

        Args:
            run_id: Pipeline run ID
            stage: Stage to execute

        Returns:
            StageResult with success/failure and output
        """
        start_time = datetime.utcnow()

        logger.info(
            "stage_starting",
            extra={"run_id": run_id, "stage": stage.value},
        )

        # Fetch run and stage record
        run = await self._get_run(run_id)
        stage_record = await self._get_stage_record(run_id, stage)

        # Validate stage can be executed
        if stage_record.status == "success":
            return StageResult(
                stage=stage,
                success=True,
                output=StageOutput(data=stage_record.output_json or {}),
                duration_seconds=0,
            )

        if stage_record.status == "running":
            raise PipelineExecutionError(f"Stage {stage.value} is already running")

        # Check prerequisites - previous stage must be complete
        prev_stage = stage.previous_stage()
        if prev_stage:
            prev_record = await self._get_stage_record(run_id, prev_stage)
            if prev_record.status != "success":
                raise PipelineExecutionError(
                    f"Cannot execute {stage.value}: previous stage {prev_stage.value} "
                    f"has status {prev_record.status}"
                )

        # Update run and stage status
        run.status = "running"
        run.current_stage = stage.value
        if run.started_at is None:
            run.started_at = now_utc()

        stage_record.status = "running"
        stage_record.started_at = now_utc()
        await self.session.flush()

        # Build stage input
        game_context = await get_game_context(self.session, run.game_id)
        accumulated = accumulate_outputs(run, stage)

        stage_input = StageInput(
            game_id=run.game_id,
            run_id=run_id,
            previous_output=accumulated if accumulated else None,
            game_context=game_context,
        )

        try:
            # Execute the stage
            if stage == PipelineStage.NORMALIZE_PBP:
                output = await execute_normalize_pbp(self.session, stage_input, run_id)
            elif stage == PipelineStage.CLASSIFY_GAME_SHAPE:
                output = await execute_classify_game_shape(stage_input)
            elif stage == PipelineStage.GENERATE_SUMMARY:
                output = await execute_generate_summary(stage_input)
            elif stage == PipelineStage.FINALIZE_SUMMARY:
                output = await execute_finalize_summary(
                    self.session, stage_input, str(run.run_uuid)
                )
            else:
                raise PipelineExecutionError(
                    f"Stage {stage.value} is not part of the active pipeline"
                )

            # Update stage record with success
            stage_record.status = "success"
            stage_record.output_json = output.data
            stage_record.logs_json = output.logs
            stage_record.finished_at = now_utc()

            # Calculate duration
            end_time = datetime.utcnow()
            duration = (end_time - start_time).total_seconds()

            # Emit OTel metrics
            sport = game_context.get("sport", "UNKNOWN")
            record_stage_duration(stage.value, sport, duration * 1000)
            if stage == PipelineStage.FINALIZE_SUMMARY:
                increment_published(sport)

            # Check if pipeline is complete
            if stage == PipelineStage.FINALIZE_SUMMARY:
                run.status = "completed"
                run.finished_at = now_utc()
            elif not run.auto_chain:
                run.status = "paused"

            await self.session.flush()

            logger.info(
                "stage_completed",
                extra={
                    "run_id": run_id,
                    "stage": stage.value,
                    "duration_seconds": duration,
                },
            )

            return StageResult(
                stage=stage,
                success=True,
                output=output,
                duration_seconds=duration,
            )

        # Orchestration boundary: every stage's failures funnel here. We
        # MUST catch ``Exception`` (not narrow further) because any stage's
        # uncaught error needs to leave the run/stage in a consistent
        # ``failed`` state and emit metrics. The full traceback is preserved
        # via ``exc_info=True`` below; nothing is silently swallowed.
        except Exception as e:
            pipeline_stage_failures_total.labels(stage.value).inc()
            # Update stage record with failure
            stage_record.status = "failed"
            stage_record.error_details = str(e)
            stage_record.finished_at = now_utc()

            run.status = "failed"
            run.finished_at = now_utc()

            await self.session.flush()

            end_time = datetime.utcnow()
            duration = (end_time - start_time).total_seconds()

            logger.error(
                "stage_failed",
                extra={
                    "run_id": run_id,
                    "stage": stage.value,
                    "error": str(e),
                    "duration_seconds": duration,
                },
                exc_info=True,
            )

            return StageResult(
                stage=stage,
                success=False,
                error=str(e),
                duration_seconds=duration,
            )

    async def execute_next_stage(self, run_id: int) -> StageResult | None:
        """Execute the next pending stage in the pipeline.

        Args:
            run_id: Pipeline run ID

        Returns:
            StageResult if a stage was executed, None if pipeline is complete
        """
        run = await self._get_run(run_id)

        if not run.can_continue:
            return None

        # Find next pending stage
        for stage in PipelineStage.ordered_stages():
            stage_record = next(
                (s for s in run.stages if s.stage == stage.value),
                None,
            )

            if stage_record and stage_record.status == "pending":
                return await self.execute_stage(run_id, stage)

        return None

    async def run_full_pipeline(
        self,
        game_id: int,
        triggered_by: str = "prod_auto",
    ) -> GamePipelineRun:
        """Run the complete pipeline for a game.

        This is a convenience method that creates a run and executes
        all stages in sequence, regardless of auto_chain setting.

        Args:
            game_id: Game to process
            triggered_by: Who triggered the run

        Returns:
            Completed GamePipelineRun record
        """
        # Start pipeline
        run = await self.start_pipeline(game_id, triggered_by, auto_chain=True)

        # Determine league early so the structured debug logger always carries
        # it (even if the pipeline aborts before any stage records data).
        league_code = await resolve_league_code(self.session, game_id)
        flow_debug = get_or_create_flow_debug_logger(run.id, game_id, league_code)

        try:
            # Execute all stages
            for stage in PipelineStage.ordered_stages():
                result = await self.execute_stage(run.id, stage)

                if not result.success:
                    logger.error(
                        "pipeline_failed",
                        extra={
                            "run_id": run.id,
                            "stage": stage.value,
                            "error": result.error,
                        },
                    )
                    break

            # Refresh run to get final status
            run = await self._get_run(run.id)

            logger.info(
                "pipeline_finished",
                extra={
                    "run_id": run.id,
                    "run_uuid": str(run.run_uuid),
                    "game_id": game_id,
                    "status": run.status,
                },
            )

            flow_debug.set_final_status(run.status)
            return run
        finally:
            popped = pop_flow_debug_logger(run.id)
            if popped is not None:
                popped.emit()

    async def get_run_status(self, run_id: int) -> dict[str, Any]:
        """Get detailed status of a pipeline run.

        Args:
            run_id: Pipeline run ID

        Returns:
            Dict with run status and stage details
        """
        run = await self._get_run(run_id)

        active_order = {s: i for i, s in enumerate(PipelineStage.ordered_stages())}

        def _sort_key(stage_record: GamePipelineStage) -> tuple[int, int]:
            try:
                stage_enum = PipelineStage(stage_record.stage)
            except ValueError:
                return (1, 0)
            return (0, active_order.get(stage_enum, len(active_order)))

        stages = []
        for stage_record in sorted(run.stages, key=_sort_key):
            stages.append(
                {
                    "stage": stage_record.stage,
                    "status": stage_record.status,
                    "started_at": stage_record.started_at.isoformat()
                    if stage_record.started_at
                    else None,
                    "finished_at": stage_record.finished_at.isoformat()
                    if stage_record.finished_at
                    else None,
                    "error_details": stage_record.error_details,
                    "has_output": stage_record.output_json is not None,
                    "log_count": len(stage_record.logs_json or []),
                }
            )

        return {
            "run_id": run.id,
            "run_uuid": str(run.run_uuid),
            "game_id": run.game_id,
            "triggered_by": run.triggered_by,
            "auto_chain": run.auto_chain,
            "status": run.status,
            "current_stage": run.current_stage,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "stages": stages,
        }
