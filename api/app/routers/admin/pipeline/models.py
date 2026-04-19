"""Pipeline router request and response models.

This module contains all Pydantic models used by the pipeline endpoints.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

# =============================================================================
# ENUMS FOR FRONTEND
# =============================================================================


class PipelineRunStatusEnum(str, Enum):
    """Pipeline run status values."""

    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    paused = "paused"


class StageStatusEnum(str, Enum):
    """Stage execution status values."""

    pending = "pending"
    running = "running"
    success = "success"
    failed = "failed"
    skipped = "skipped"


# =============================================================================
# REQUEST MODELS
# =============================================================================


class StartPipelineRequest(BaseModel):
    """Request to start a new pipeline run for a game."""

    triggered_by: str = Field(
        default="admin",
        description="Who triggered the run: admin, manual, backfill, prod_auto",
    )
    auto_chain: bool | None = Field(
        default=None,
        description="Auto-proceed to next stage on success.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "triggered_by": "admin",
                "auto_chain": False,
            }
        }
    }


class RerunPipelineRequest(BaseModel):
    """Request to re-run a pipeline for a game."""

    triggered_by: str = Field(
        default="admin",
        description="Who triggered the re-run",
    )
    execute_through_stage: str | None = Field(
        default=None,
        description="Execute all stages up to and including this stage.",
    )
    reason: str | None = Field(
        default=None,
        description="Optional reason for re-running (for audit trail)",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "triggered_by": "admin",
                "execute_through_stage": "GENERATE_MOMENTS",
                "reason": "Testing new threshold values",
            }
        }
    }


class ExecuteStageRequest(BaseModel):
    """Request to execute a specific stage."""

    force: bool = Field(
        default=False,
        description="If True, re-execute even if already succeeded",
    )


class RunFullPipelineRequest(BaseModel):
    """Request to run the complete pipeline."""

    triggered_by: str = Field(
        default="admin",
        description="Who triggered the run",
    )
    regen_attempt: int = Field(
        default=0,
        description=(
            "Quality-gate regen counter. 0 = first pipeline pass; "
            "1 = first regen (triggers template_fallback on second gate failure). "
            "Set automatically by grade_gate_regen triggers."
        ),
    )
    failure_reasons: list[str] = Field(
        default_factory=list,
        description=(
            "Structured failure reasons from the previous grade_flow_task. "
            "Injected into game_context so the next RENDER_BLOCKS pass can "
            "address specific quality weaknesses."
        ),
    )


# =============================================================================
# RESPONSE MODELS - Stage Level
# =============================================================================


class StageStatusResponse(BaseModel):
    """Status of a single pipeline stage."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    stage: str = Field(description="Stage name (e.g., NORMALIZE_PBP)")
    stage_order: int = Field(description="Execution order (1-5)")
    status: str = Field(description="pending, running, success, failed, skipped")
    started_at: str | None = Field(description="ISO timestamp when stage started")
    finished_at: str | None = Field(description="ISO timestamp when stage finished")
    duration_seconds: float | None = Field(description="Execution time in seconds")
    error_details: str | None = Field(description="Error message if failed")
    has_output: bool = Field(description="Whether stage has output data")
    output_summary: dict[str, Any] | None = Field(
        description="Summary of output (counts, key metrics)"
    )
    log_count: int = Field(description="Number of log entries")
    can_execute: bool = Field(description="Whether this stage can be executed now")


class StageOutputResponse(BaseModel):
    """Full output from a pipeline stage."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    run_id: int
    run_uuid: str
    stage: str
    status: str
    output_json: dict[str, Any] | None = Field(description="Full stage output data")
    output_summary: dict[str, Any] = Field(description="Summary metrics from output")
    generated_at: str | None = Field(description="When output was generated")


class StageLogsResponse(BaseModel):
    """Logs from a pipeline stage."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    run_id: int
    run_uuid: str
    stage: str
    status: str
    logs: list[dict[str, Any]] = Field(
        description="Array of log entries with timestamp, level, message"
    )
    log_count: int


# =============================================================================
# RESPONSE MODELS - Run Level
# =============================================================================


class PipelineRunResponse(BaseModel):
    """Full status of a pipeline run."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    run_id: int
    run_uuid: str
    game_id: int
    triggered_by: str
    auto_chain: bool
    status: str
    current_stage: str | None
    started_at: str | None
    finished_at: str | None
    duration_seconds: float | None
    created_at: str
    stages: list[StageStatusResponse]
    stages_completed: int
    stages_failed: int
    stages_pending: int
    progress_percent: int = Field(description="Overall progress as percentage (0-100)")
    can_continue: bool = Field(description="Whether pipeline can be continued")
    next_stage: str | None = Field(description="Next stage to execute, if any")


class PipelineRunSummary(BaseModel):
    """Summary of a pipeline run for listing."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    run_id: int
    run_uuid: str
    game_id: int
    triggered_by: str
    status: str
    current_stage: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None
    stages_completed: int
    stages_total: int
    progress_percent: int
    stages: list[StageStatusResponse] = Field(
        default_factory=list,
        description="Per-stage detail for expandable UI rows",
    )


class StartPipelineResponse(BaseModel):
    """Response after starting a pipeline run."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    run_id: int
    run_uuid: str
    game_id: int
    status: str
    auto_chain: bool
    stages: list[StageStatusResponse]
    next_stage: str
    message: str


class ExecuteStageResponse(BaseModel):
    """Response after executing a stage."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    run_id: int
    run_uuid: str
    stage: str
    status: str
    success: bool
    duration_seconds: float
    error: str | None = None
    output_summary: dict[str, Any] | None = None
    next_stage: str | None = None
    pipeline_status: str
    message: str


class ContinuePipelineResponse(BaseModel):
    """Response after continuing a pipeline."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    run_id: int
    run_uuid: str
    stage_executed: str | None
    success: bool
    duration_seconds: float | None
    pipeline_status: str
    stages_completed: int
    stages_remaining: int
    next_stage: str | None
    message: str


class RerunPipelineResponse(BaseModel):
    """Response after re-running a pipeline."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    new_run_id: int
    new_run_uuid: str
    game_id: int
    previous_runs_count: int
    status: str
    stages_executed: list[str]
    stages_pending: list[str]
    message: str


class RunFullPipelineResponse(BaseModel):
    """Response after running the full pipeline."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    run_id: int
    run_uuid: str
    game_id: int
    status: str
    stages_completed: int
    stages_failed: int
    duration_seconds: float | None
    artifact_id: int | None = Field(description="Timeline artifact ID if finalization succeeded")
    message: str


# =============================================================================
# RESPONSE MODELS - Game Level
# =============================================================================


class GamePipelineRunsResponse(BaseModel):
    """List of pipeline runs for a game."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    game_id: int
    game_info: dict[str, Any] = Field(description="Basic game info")
    runs: list[PipelineRunSummary]
    total_runs: int
    has_successful_run: bool
    latest_artifact_at: str | None = Field(
        description="When the latest timeline artifact was generated"
    )


class GamePipelineSummary(BaseModel):
    """Quick summary of pipeline state for a game."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    game_id: int
    game_date: str
    home_team: str
    away_team: str
    game_status: str
    has_pbp: bool
    has_timeline_artifact: bool
    latest_artifact_at: str | None
    total_pipeline_runs: int
    latest_run: PipelineRunSummary | None
    can_run_pipeline: bool = Field(description="Whether a new pipeline can be started")


class StageComparisonResponse(BaseModel):
    """Compare a stage's output between two runs."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    game_id: int
    stage: str
    run_a: dict[str, Any]
    run_b: dict[str, Any]
    differences: dict[str, Any] = Field(description="Key differences between outputs")


# =============================================================================
# BULK GENERATION MODELS
# =============================================================================


class BulkGenerateRequest(BaseModel):
    """Request to start bulk game flow generation across multiple games."""

    start_date: str = Field(description="Start date (YYYY-MM-DD)")
    end_date: str = Field(description="End date (YYYY-MM-DD)")
    leagues: list[str] = Field(description="Leagues to include (NBA, NHL, NCAAB)")
    force: bool = Field(
        default=False,
        description="If True, regenerate game flows even if they already exist",
    )
    max_games: int | None = Field(
        default=None,
        description="Maximum number of games to process (None = no limit)",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "start_date": "2024-01-01",
                "end_date": "2024-01-07",
                "leagues": ["NBA", "NHL"],
                "force": False,
                "max_games": None,
            }
        }
    }


class BulkGenerateAsyncResponse(BaseModel):
    """Response after starting an async bulk generation job."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    job_id: str = Field(description="Unique job identifier for tracking progress")
    message: str = Field(description="Status message")
    status_url: str = Field(description="URL to poll for job status")


class BulkGenerateStatusResponse(BaseModel):
    """Status of a bulk generation job."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    job_id: str = Field(description="Job identifier")
    state: str = Field(description="Job state: PENDING, PROGRESS, SUCCESS, FAILURE")
    current: int = Field(description="Current game being processed (1-indexed)")
    total: int = Field(description="Total games to process")
    successful: int = Field(description="Number of games successfully processed")
    failed: int = Field(description="Number of games that failed")
    skipped: int = Field(description="Number of games skipped (already have flow)")
    result: dict[str, Any] | None = Field(
        default=None,
        description="Final result when job completes",
    )


# =============================================================================
# BACKFILL EMBEDDED TWEETS MODELS
# =============================================================================


class BackfillEmbeddedTweetsResponse(BaseModel):
    """Response from backfilling embedded tweets into game flows."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    total_checked: int = Field(description="Number of flows checked")
    total_backfilled: int = Field(description="Number of flows that were backfilled")
    results: list[dict[str, Any]] = Field(description="Per-game result details")
    message: str = Field(description="Summary message")
