"""Admin endpoints for game pipeline management.

PIPELINE CONTROL SURFACE
========================

These endpoints provide a complete control surface for the admin UI to:
- Start and manage pipeline runs for specific games
- Execute individual pipeline stages with full control
- Re-run stages without deleting prior outputs (creates new runs)
- View detailed status, logs, and outputs for each stage

SAFETY GUARANTEES
=================

1. IMMUTABILITY: Previous runs are NEVER mutated. Re-running a stage
   creates a NEW pipeline run, preserving the complete history.

2. IDEMPOTENCY: Starting a pipeline or executing a stage is NOT idempotent.
   Each call creates new records. Use GET endpoints to check status before
   triggering new executions.

3. ISOLATION: Each run is independent. Failed runs don't affect other runs.

4. AUDITABILITY: All executions are logged with timestamps and full output.
"""

from fastapi import APIRouter

from .backfill_endpoints import router as backfill_router
from .bulk_endpoints import router as bulk_router
from .models import (
    BackfillEmbeddedTweetsResponse,
    BulkGenerateAsyncResponse,
    BulkGenerateRequest,
    BulkGenerateStatusResponse,
    ContinuePipelineResponse,
    ExecuteStageRequest,
    ExecuteStageResponse,
    GamePipelineRunsResponse,
    GamePipelineSummary,
    PipelineRunResponse,
    PipelineRunStatusEnum,
    PipelineRunSummary,
    RerunPipelineRequest,
    RerunPipelineResponse,
    RunFullPipelineRequest,
    RunFullPipelineResponse,
    StageComparisonResponse,
    StageLogsResponse,
    StageOutputResponse,
    StageStatusEnum,
    StageStatusResponse,
    StartPipelineRequest,
    StartPipelineResponse,
)
from .run_endpoints import router as run_router
from .stage_endpoints import router as stage_router
from .status_endpoints import router as status_router

# Create the main router and include the endpoints
router = APIRouter()
router.include_router(run_router)
router.include_router(status_router)
router.include_router(stage_router)
router.include_router(bulk_router)
router.include_router(backfill_router)

__all__ = [
    "router",
    # Enums
    "PipelineRunStatusEnum",
    "StageStatusEnum",
    # Request models
    "StartPipelineRequest",
    "RerunPipelineRequest",
    "ExecuteStageRequest",
    "RunFullPipelineRequest",
    "BulkGenerateRequest",
    # Response models
    "StageStatusResponse",
    "StageOutputResponse",
    "StageLogsResponse",
    "PipelineRunResponse",
    "PipelineRunSummary",
    "StartPipelineResponse",
    "ExecuteStageResponse",
    "ContinuePipelineResponse",
    "RerunPipelineResponse",
    "RunFullPipelineResponse",
    "GamePipelineRunsResponse",
    "GamePipelineSummary",
    "StageComparisonResponse",
    "BulkGenerateAsyncResponse",
    "BulkGenerateStatusResponse",
    "BackfillEmbeddedTweetsResponse",
]
