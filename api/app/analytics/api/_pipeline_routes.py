"""Training, backtest, and batch simulation endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db

router = APIRouter()


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------


class TrainModelRequest(BaseModel):
    """Request body for POST /api/analytics/train."""
    feature_config_id: int | None = Field(None, description="Feature loadout ID from DB")
    sport: str = Field("mlb", description="Sport code")
    model_type: str = Field("game", description="Model type")
    date_start: str | None = Field(None, description="Training data start date (YYYY-MM-DD)")
    date_end: str | None = Field(None, description="Training data end date (YYYY-MM-DD)")
    test_split: float = Field(0.2, ge=0.05, le=0.5, description="Test set fraction")
    algorithm: str = Field("gradient_boosting", description="Algorithm: gradient_boosting, random_forest, xgboost")
    random_state: int = Field(42, description="Random seed for reproducibility")
    rolling_window: int = Field(30, ge=5, le=162, description="Rolling window size (prior games for profile aggregation)")


def _serialize_training_job(job) -> dict[str, Any]:
    """Serialize a training job row to API response."""
    return {
        "id": job.id,
        "feature_config_id": job.feature_config_id,
        "sport": job.sport,
        "model_type": job.model_type,
        "algorithm": job.algorithm,
        "date_start": job.date_start,
        "date_end": job.date_end,
        "test_split": job.test_split,
        "random_state": job.random_state,
        "rolling_window": getattr(job, "rolling_window", 30),
        "status": job.status,
        "celery_task_id": job.celery_task_id,
        "model_id": job.model_id,
        "artifact_path": job.artifact_path,
        "metrics": job.metrics,
        "train_count": job.train_count,
        "test_count": job.test_count,
        "feature_names": job.feature_names,
        "feature_importance": getattr(job, "feature_importance", None),
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


@router.post("/train")
async def start_training(
    req: TrainModelRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Start a model training job.

    Creates a training job record and dispatches a Celery task.
    """
    from app.db.analytics import AnalyticsTrainingJob

    try:
        job = AnalyticsTrainingJob(
            feature_config_id=req.feature_config_id,
            sport=req.sport.lower(),
            model_type=req.model_type,
            algorithm=req.algorithm,
            date_start=req.date_start,
            date_end=req.date_end,
            test_split=req.test_split,
            random_state=req.random_state,
            rolling_window=req.rolling_window,
            status="pending",
        )
        db.add(job)
        await db.flush()
        await db.refresh(job)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create training job: {exc}",
        )

    try:
        from app.tasks.training_tasks import train_analytics_model
        task = train_analytics_model.delay(job.id)
        job.celery_task_id = task.id
        job.status = "queued"
        await db.flush()
    except Exception as exc:
        job.status = "failed"
        job.error_message = f"Failed to dispatch task: {exc}"
        await db.flush()

    # Refresh after second flush so server-side onupdate columns
    # (updated_at) are loaded — avoids MissingGreenlet on serialize.
    await db.refresh(job)

    return {"status": "submitted", "job": _serialize_training_job(job)}


@router.get("/training-jobs")
async def list_training_jobs(
    sport: str = Query(None, description="Filter by sport"),
    status: str = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List training jobs with optional filtering."""
    from app.db.analytics import AnalyticsTrainingJob

    stmt = select(AnalyticsTrainingJob).order_by(
        AnalyticsTrainingJob.created_at.desc()
    ).limit(limit)

    if sport:
        stmt = stmt.where(AnalyticsTrainingJob.sport == sport)
    if status:
        stmt = stmt.where(AnalyticsTrainingJob.status == status)

    result = await db.execute(stmt)
    jobs = result.scalars().all()
    return {
        "jobs": [_serialize_training_job(j) for j in jobs],
        "count": len(jobs),
    }


@router.get("/training-job/{job_id}")
async def get_training_job(
    job_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get details for a specific training job."""
    from app.db.analytics import AnalyticsTrainingJob

    job = await db.get(AnalyticsTrainingJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Training job not found")
    return _serialize_training_job(job)


@router.post("/training-job/{job_id}/cancel")
async def cancel_training_job(
    job_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Cancel a queued or running training job."""
    from app.db.analytics import AnalyticsTrainingJob

    job = await db.get(AnalyticsTrainingJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Training job not found")

    if job.status not in ("pending", "queued", "running"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel job with status '{job.status}'",
        )

    # Revoke the Celery task if we have a task ID
    if job.celery_task_id:
        try:
            from app.celery_app import celery_app
            celery_app.control.revoke(job.celery_task_id, terminate=True)
        except Exception:
            pass  # best-effort revocation

    job.status = "failed"
    job.error_message = "Canceled by user"
    await db.flush()
    await db.refresh(job)
    return {"status": "canceled", **_serialize_training_job(job)}


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------


class BacktestRequest(BaseModel):
    """Request body for POST /api/analytics/backtest."""
    model_id: str = Field(..., description="Model ID to backtest")
    artifact_path: str = Field(..., description="Path to model .pkl artifact")
    sport: str = Field("mlb", description="Sport code")
    model_type: str = Field("game", description="Model type")
    date_start: str | None = Field(None, description="Backtest start date (YYYY-MM-DD)")
    date_end: str | None = Field(None, description="Backtest end date (YYYY-MM-DD)")
    rolling_window: int = Field(30, ge=5, le=162, description="Rolling window for profile aggregation")


def _serialize_backtest_job(job) -> dict[str, Any]:
    """Serialize a backtest job row to API response."""
    return {
        "id": job.id,
        "model_id": job.model_id,
        "artifact_path": job.artifact_path,
        "sport": job.sport,
        "model_type": job.model_type,
        "date_start": job.date_start,
        "date_end": job.date_end,
        "rolling_window": getattr(job, "rolling_window", 30),
        "status": job.status,
        "celery_task_id": job.celery_task_id,
        "game_count": job.game_count,
        "correct_count": job.correct_count,
        "metrics": job.metrics,
        "predictions": job.predictions,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


@router.post("/backtest")
async def start_backtest(
    req: BacktestRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Start a model backtest job."""
    from app.db.analytics import AnalyticsBacktestJob

    job = AnalyticsBacktestJob(
        model_id=req.model_id,
        artifact_path=req.artifact_path,
        sport=req.sport.lower(),
        model_type=req.model_type,
        date_start=req.date_start,
        date_end=req.date_end,
        rolling_window=req.rolling_window,
        status="pending",
    )
    db.add(job)
    await db.flush()
    await db.refresh(job)

    try:
        from app.tasks.training_tasks import backtest_analytics_model
        task = backtest_analytics_model.delay(job.id)
        job.celery_task_id = task.id
        job.status = "queued"
        await db.flush()
    except Exception as exc:
        job.status = "failed"
        job.error_message = f"Failed to dispatch task: {exc}"
        await db.flush()

    await db.refresh(job)

    return {"status": "submitted", "job": _serialize_backtest_job(job)}


@router.get("/backtest-jobs")
async def list_backtest_jobs(
    model_id: str = Query(None, description="Filter by model ID"),
    sport: str = Query(None, description="Filter by sport"),
    status: str = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List backtest jobs with optional filtering."""
    from app.db.analytics import AnalyticsBacktestJob

    stmt = select(AnalyticsBacktestJob).order_by(
        AnalyticsBacktestJob.created_at.desc()
    ).limit(limit)

    if model_id:
        stmt = stmt.where(AnalyticsBacktestJob.model_id == model_id)
    if sport:
        stmt = stmt.where(AnalyticsBacktestJob.sport == sport)
    if status:
        stmt = stmt.where(AnalyticsBacktestJob.status == status)

    result = await db.execute(stmt)
    jobs = result.scalars().all()
    return {
        "jobs": [_serialize_backtest_job(j) for j in jobs],
        "count": len(jobs),
    }


@router.get("/backtest-job/{job_id}")
async def get_backtest_job(
    job_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get details for a specific backtest job."""
    from app.db.analytics import AnalyticsBacktestJob

    job = await db.get(AnalyticsBacktestJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Backtest job not found")
    return _serialize_backtest_job(job)


# ---------------------------------------------------------------------------
# Batch Simulation
# ---------------------------------------------------------------------------


class BatchSimulateRequest(BaseModel):
    """Request body for POST /api/analytics/batch-simulate."""
    sport: str = Field(..., description="Sport code (e.g., mlb)")
    probability_mode: str = Field("ml", description="Probability source: ml, rule_based, ensemble")
    iterations: int = Field(5000, ge=100, le=50000, description="Monte Carlo iterations per game")
    rolling_window: int = Field(30, ge=5, le=162, description="Rolling window for profile building")
    date_start: str | None = Field(None, description="Start date (YYYY-MM-DD)")
    date_end: str | None = Field(None, description="End date (YYYY-MM-DD)")


@router.post("/batch-simulate")
async def post_batch_simulate(
    req: BatchSimulateRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Kick off a batch simulation of upcoming games."""
    from app.db.analytics import AnalyticsBatchSimJob
    from app.tasks.batch_sim_tasks import batch_simulate_games

    job = AnalyticsBatchSimJob(
        sport=req.sport,
        probability_mode=req.probability_mode,
        iterations=req.iterations,
        rolling_window=req.rolling_window,
        date_start=req.date_start,
        date_end=req.date_end,
        status="pending",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    task = batch_simulate_games.delay(job.id)
    job.celery_task_id = task.id
    job.status = "queued"
    await db.commit()
    await db.refresh(job)

    return {"job": _serialize_batch_sim_job(job)}


@router.get("/batch-simulate-jobs")
async def list_batch_simulate_jobs(
    sport: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List batch simulation jobs."""
    from app.db.analytics import AnalyticsBatchSimJob

    stmt = select(AnalyticsBatchSimJob).order_by(AnalyticsBatchSimJob.id.desc())
    if sport:
        stmt = stmt.where(AnalyticsBatchSimJob.sport == sport)
    result = await db.execute(stmt)
    jobs = list(result.scalars().all())

    return {
        "jobs": [_serialize_batch_sim_job(j) for j in jobs],
        "count": len(jobs),
    }


@router.get("/batch-simulate-job/{job_id}")
async def get_batch_simulate_job(
    job_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get details for a specific batch simulation job."""
    from app.db.analytics import AnalyticsBatchSimJob

    job = await db.get(AnalyticsBatchSimJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Batch sim job not found")
    return _serialize_batch_sim_job(job)


def _serialize_batch_sim_job(job: Any) -> dict[str, Any]:
    return {
        "id": job.id,
        "sport": job.sport,
        "probability_mode": job.probability_mode,
        "iterations": job.iterations,
        "rolling_window": job.rolling_window,
        "date_start": job.date_start,
        "date_end": job.date_end,
        "status": job.status,
        "celery_task_id": job.celery_task_id,
        "game_count": job.game_count,
        "results": job.results,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


# ---------------------------------------------------------------------------
# Experiment Suite
# ---------------------------------------------------------------------------


class ExperimentSuiteRequest(BaseModel):
    """Request body for POST /api/analytics/experiments."""
    name: str = Field(..., description="Experiment suite name")
    description: str | None = Field(None, description="Optional description")
    sport: str = Field("mlb")
    model_type: str = Field("player_plate_appearance", description="Model type to sweep")
    parameter_grid: dict[str, Any] = Field(
        ...,
        description="Grid of parameters to sweep: algorithms, rolling_windows, feature_config_ids, etc.",
    )
    tags: list[str] | None = Field(None, description="Optional tags")


def _serialize_experiment_suite(s: Any) -> dict[str, Any]:
    return {
        "id": s.id,
        "name": s.name,
        "description": s.description,
        "sport": s.sport,
        "model_type": s.model_type,
        "parameter_grid": s.parameter_grid,
        "tags": s.tags,
        "total_variants": s.total_variants,
        "completed_variants": s.completed_variants,
        "failed_variants": s.failed_variants,
        "status": s.status,
        "leaderboard": s.leaderboard,
        "promoted_model_id": s.promoted_model_id,
        "promoted_at": s.promoted_at.isoformat() if s.promoted_at else None,
        "error_message": s.error_message,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "completed_at": s.completed_at.isoformat() if s.completed_at else None,
    }


def _serialize_variant(v: Any) -> dict[str, Any]:
    return {
        "id": v.id,
        "suite_id": v.suite_id,
        "variant_index": v.variant_index,
        "algorithm": v.algorithm,
        "rolling_window": v.rolling_window,
        "feature_config_id": v.feature_config_id,
        "training_date_start": v.training_date_start,
        "training_date_end": v.training_date_end,
        "test_split": v.test_split,
        "extra_params": v.extra_params,
        "training_job_id": v.training_job_id,
        "replay_job_id": v.replay_job_id,
        "model_id": v.model_id,
        "status": v.status,
        "training_metrics": v.training_metrics,
        "replay_metrics": v.replay_metrics,
        "rank": v.rank,
        "error_message": v.error_message,
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "completed_at": v.completed_at.isoformat() if v.completed_at else None,
    }


@router.post("/experiments")
async def create_experiment_suite(
    req: ExperimentSuiteRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create and launch an experiment suite."""
    from app.db.analytics import AnalyticsExperimentSuite

    suite = AnalyticsExperimentSuite(
        name=req.name,
        description=req.description,
        sport=req.sport.lower(),
        model_type=req.model_type,
        parameter_grid=req.parameter_grid,
        tags=req.tags,
        status="pending",
    )
    db.add(suite)
    await db.flush()
    await db.refresh(suite)

    try:
        from app.tasks.experiment_tasks import run_experiment_suite
        task = run_experiment_suite.delay(suite.id)
        suite.celery_task_id = task.id
        suite.status = "queued"
        await db.flush()
    except Exception as exc:
        suite.status = "failed"
        suite.error_message = f"Failed to dispatch: {exc}"
        await db.flush()

    await db.refresh(suite)
    return {"status": "submitted", "suite": _serialize_experiment_suite(suite)}


@router.get("/experiments")
async def list_experiment_suites(
    sport: str | None = None,
    status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List experiment suites."""
    from app.db.analytics import AnalyticsExperimentSuite

    stmt = select(AnalyticsExperimentSuite).order_by(
        AnalyticsExperimentSuite.created_at.desc()
    ).limit(limit)
    if sport:
        stmt = stmt.where(AnalyticsExperimentSuite.sport == sport)
    if status:
        stmt = stmt.where(AnalyticsExperimentSuite.status == status)

    result = await db.execute(stmt)
    suites = result.scalars().all()
    return {
        "suites": [_serialize_experiment_suite(s) for s in suites],
        "count": len(suites),
    }


@router.get("/experiments/{suite_id}")
async def get_experiment_suite(
    suite_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get experiment suite with its variants."""
    from app.db.analytics import AnalyticsExperimentSuite, AnalyticsExperimentVariant

    suite = await db.get(AnalyticsExperimentSuite, suite_id)
    if suite is None:
        raise HTTPException(status_code=404, detail="Experiment suite not found")

    # Load variants
    stmt = (
        select(AnalyticsExperimentVariant)
        .where(AnalyticsExperimentVariant.suite_id == suite_id)
        .order_by(AnalyticsExperimentVariant.variant_index)
    )
    result = await db.execute(stmt)
    variants = result.scalars().all()

    data = _serialize_experiment_suite(suite)
    data["variants"] = [_serialize_variant(v) for v in variants]
    return data


@router.post("/experiments/{suite_id}/promote/{variant_id}")
async def promote_experiment_variant(
    suite_id: int,
    variant_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Promote a winning variant's model to active in the registry."""
    from app.db.analytics import AnalyticsExperimentSuite, AnalyticsExperimentVariant

    suite = await db.get(AnalyticsExperimentSuite, suite_id)
    if suite is None:
        raise HTTPException(status_code=404, detail="Suite not found")

    variant = await db.get(AnalyticsExperimentVariant, variant_id)
    if variant is None or variant.suite_id != suite_id:
        raise HTTPException(status_code=404, detail="Variant not found in suite")

    if not variant.model_id:
        raise HTTPException(status_code=400, detail="Variant has no trained model")

    # Activate in model registry
    from app.analytics.models.core.model_registry import ModelRegistry
    registry = ModelRegistry()
    registry.activate_model(suite.sport, suite.model_type, variant.model_id)

    suite.promoted_model_id = variant.model_id
    suite.promoted_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(suite)

    return {
        "status": "promoted",
        "model_id": variant.model_id,
        "suite": _serialize_experiment_suite(suite),
    }


# ---------------------------------------------------------------------------
# Historical Replay
# ---------------------------------------------------------------------------


class ReplayRequest(BaseModel):
    """Request body for POST /api/analytics/replay."""
    sport: str = Field("mlb")
    model_id: str = Field(..., description="Model ID to evaluate")
    model_type: str = Field("plate_appearance")
    date_start: str | None = Field(None, description="Replay start date")
    date_end: str | None = Field(None, description="Replay end date")
    game_count: int | None = Field(None, ge=1, le=500, description="Max games to replay")
    rolling_window: int = Field(30, ge=5, le=162)
    probability_mode: str = Field("ml")
    iterations: int = Field(5000, ge=100, le=50000)
    suite_id: int | None = Field(None, description="Optional link to experiment suite")


def _serialize_replay_job(job: Any) -> dict[str, Any]:
    return {
        "id": job.id,
        "sport": job.sport,
        "model_id": job.model_id,
        "model_type": job.model_type,
        "date_start": job.date_start,
        "date_end": job.date_end,
        "game_count_requested": job.game_count_requested,
        "rolling_window": job.rolling_window,
        "probability_mode": job.probability_mode,
        "iterations": job.iterations,
        "suite_id": job.suite_id,
        "status": job.status,
        "celery_task_id": job.celery_task_id,
        "game_count": job.game_count,
        "results": job.results,
        "metrics": job.metrics,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


@router.post("/replay")
async def start_replay(
    req: ReplayRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Start a historical replay job."""
    from app.db.analytics import AnalyticsReplayJob

    job = AnalyticsReplayJob(
        sport=req.sport.lower(),
        model_id=req.model_id,
        model_type=req.model_type,
        date_start=req.date_start,
        date_end=req.date_end,
        game_count_requested=req.game_count,
        rolling_window=req.rolling_window,
        probability_mode=req.probability_mode,
        iterations=req.iterations,
        suite_id=req.suite_id,
        status="pending",
    )
    db.add(job)
    await db.flush()
    await db.refresh(job)

    try:
        from app.tasks.replay_tasks import replay_historical_games
        task = replay_historical_games.delay(job.id)
        job.celery_task_id = task.id
        job.status = "queued"
        await db.flush()
    except Exception as exc:
        job.status = "failed"
        job.error_message = f"Failed to dispatch: {exc}"
        await db.flush()

    await db.refresh(job)
    return {"status": "submitted", "job": _serialize_replay_job(job)}


@router.get("/replay-jobs")
async def list_replay_jobs(
    sport: str | None = None,
    suite_id: int | None = None,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List replay jobs."""
    from app.db.analytics import AnalyticsReplayJob

    stmt = select(AnalyticsReplayJob).order_by(
        AnalyticsReplayJob.created_at.desc()
    ).limit(limit)
    if sport:
        stmt = stmt.where(AnalyticsReplayJob.sport == sport)
    if suite_id is not None:
        stmt = stmt.where(AnalyticsReplayJob.suite_id == suite_id)

    result = await db.execute(stmt)
    jobs = result.scalars().all()
    return {
        "jobs": [_serialize_replay_job(j) for j in jobs],
        "count": len(jobs),
    }


@router.get("/replay-job/{job_id}")
async def get_replay_job(
    job_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get details for a specific replay job."""
    from app.db.analytics import AnalyticsReplayJob

    job = await db.get(AnalyticsReplayJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Replay job not found")
    return _serialize_replay_job(job)


# ---------------------------------------------------------------------------
# MLB Data Coverage
# ---------------------------------------------------------------------------


@router.get("/mlb-data-coverage")
async def get_mlb_data_coverage(
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return MLB data family coverage status.

    Reports independent readiness for PA, Pitch, and Fielding data.
    """
    from sqlalchemy import func

    from app.db.mlb_advanced import (
        MLBGameAdvancedStats,
        MLBPitcherGameStats,
        MLBPlayerAdvancedStats,
        MLBPlayerFieldingStats,
    )
    from app.db.sports import SportsGamePlay

    # PA data: based on MLBPlayerAdvancedStats count
    pa_count_result = await db.execute(
        select(func.count()).select_from(MLBPlayerAdvancedStats)
    )
    pa_count = pa_count_result.scalar() or 0

    # Pitch data: based on MLBPitcherGameStats + MLBGameAdvancedStats
    pitcher_count_result = await db.execute(
        select(func.count()).select_from(MLBPitcherGameStats)
    )
    pitcher_count = pitcher_count_result.scalar() or 0

    team_stats_count_result = await db.execute(
        select(func.count()).select_from(MLBGameAdvancedStats)
    )
    team_stats_count = team_stats_count_result.scalar() or 0

    # Fielding data: based on MLBPlayerFieldingStats
    fielding_count_result = await db.execute(
        select(func.count()).select_from(MLBPlayerFieldingStats)
    )
    fielding_count = fielding_count_result.scalar() or 0

    def _status(count: int, threshold_ready: int = 100, threshold_partial: int = 1) -> str:
        if count >= threshold_ready:
            return "ready"
        if count >= threshold_partial:
            return "partial"
        return "missing"

    return {
        "advanced_data_coverage": {
            "pa": _status(pa_count),
            "pitch": _status(pitcher_count + team_stats_count),
            "fielding": _status(fielding_count, threshold_ready=30),
        },
        "counts": {
            "player_advanced_stats": pa_count,
            "pitcher_game_stats": pitcher_count,
            "team_advanced_stats": team_stats_count,
            "fielding_stats": fielding_count,
        },
    }
