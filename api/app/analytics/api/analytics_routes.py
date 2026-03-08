"""Analytics API endpoints.

Provides REST endpoints for team analysis, player analysis, matchup
comparison, game simulation, and feature loadout management.

Routes:
    GET  /api/analytics/team          — Team analytical profile
    GET  /api/analytics/player        — Player analytical profile
    GET  /api/analytics/matchup       — Head-to-head matchup analysis
    POST /api/analytics/simulate      — Full Monte Carlo simulation
    POST /api/analytics/live-simulate — Live game simulation from state
    Feature Loadout CRUD:
        GET    /api/analytics/feature-configs       — List all loadouts
        GET    /api/analytics/feature-config/{id}   — Get loadout by ID
        POST   /api/analytics/feature-config        — Create new loadout
        PUT    /api/analytics/feature-config/{id}   — Update loadout
        DELETE /api/analytics/feature-config/{id}   — Delete loadout
        POST   /api/analytics/feature-config/{id}/clone — Clone loadout
        GET    /api/analytics/available-features    — List available features
    Training:
        POST   /api/analytics/train                 — Start training job
        GET    /api/analytics/training-jobs         — List training jobs
        GET    /api/analytics/training-job/{id}     — Get training job details
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.core.model_calibration import ModelCalibration
from app.analytics.core.model_metrics import ModelMetrics
from app.analytics.core.prediction_repository import PredictionRepository
from app.analytics.core.simulation_cache import SimulationCache
from app.analytics.core.simulation_job_manager import SimulationJobManager
from app.analytics.core.simulation_repository import SimulationRepository
from app.analytics.inference.model_inference_engine import ModelInferenceEngine
from app.analytics.models.core.model_registry import ModelRegistry
from app.analytics.services.analytics_service import AnalyticsService
from app.analytics.services.model_service import ModelService
from app.db import get_db
from app.db.analytics import AnalyticsFeatureConfig

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

_service = AnalyticsService()
_cache = SimulationCache()
_repository = SimulationRepository()
_job_manager = SimulationJobManager(cache=_cache, repository=_repository)
_prediction_repo = PredictionRepository()
_calibration = ModelCalibration()
_model_metrics = ModelMetrics()
_model_registry = ModelRegistry()
_model_service = ModelService(registry=_model_registry)
_inference_engine = ModelInferenceEngine(registry=_model_registry)


class LiveSimulateRequest(BaseModel):
    """Request body for POST /api/analytics/live-simulate."""
    sport: str = Field(..., description="Sport code (e.g., mlb)")
    inning: int = Field(1, ge=1, le=20, description="Current inning")
    half: str = Field("top", description="top or bottom")
    outs: int = Field(0, ge=0, le=2, description="Current outs")
    bases: dict[str, bool] = Field(
        default_factory=lambda: {"first": False, "second": False, "third": False},
        description="Base runner state",
    )
    score: dict[str, int] = Field(
        default_factory=lambda: {"home": 0, "away": 0},
        description="Current score",
    )
    iterations: int = Field(2000, ge=1, le=50000, description="Simulation iterations")
    seed: int | None = Field(None, description="Optional seed for determinism")
    home_probabilities: dict[str, float] | None = Field(
        None, description="Custom home team probability distribution",
    )
    away_probabilities: dict[str, float] | None = Field(
        None, description="Custom away team probability distribution",
    )
    probability_mode: str | None = Field(
        None, description="Probability source: rule_based or ml",
    )


class SimulateRequest(BaseModel):
    """Request body for POST /api/analytics/simulate."""
    sport: str = Field(..., description="Sport code (e.g., mlb)")
    home_team: str = Field(..., description="Home team identifier")
    away_team: str = Field(..., description="Away team identifier")
    iterations: int = Field(5000, ge=1, le=100000, description="Simulation iterations")
    seed: int | None = Field(None, description="Optional seed for determinism")
    home_probabilities: dict[str, float] | None = Field(
        None, description="Custom home team probability distribution",
    )
    away_probabilities: dict[str, float] | None = Field(
        None, description="Custom away team probability distribution",
    )
    probability_mode: str | None = Field(
        None, description="Probability source: rule_based or ml",
    )
    sportsbook: dict[str, Any] | None = Field(
        None, description="Optional sportsbook lines for comparison",
    )


@router.get("/team")
async def get_team_analytics(
    sport: str = Query(..., description="Sport code (e.g., mlb, nba)"),
    team_id: str = Query(..., description="Team identifier"),
) -> dict[str, Any]:
    """Get analytical profile for a team."""
    profile = _service.get_team_analysis(sport, team_id)
    return {
        "sport": profile.sport,
        "team_id": profile.team_id,
        "name": profile.name,
        "metrics": profile.metrics,
    }


@router.get("/player")
async def get_player_analytics(
    sport: str = Query(..., description="Sport code (e.g., mlb, nba)"),
    player_id: str = Query(..., description="Player identifier"),
) -> dict[str, Any]:
    """Get analytical profile for a player."""
    profile = _service.get_player_analysis(sport, player_id)
    return {
        "sport": profile.sport,
        "player_id": profile.player_id,
        "name": profile.name,
        "metrics": profile.metrics,
    }


@router.get("/matchup")
async def get_matchup_analytics(
    sport: str = Query(..., description="Sport code (e.g., mlb, nba)"),
    entity_a: str = Query(..., description="First entity identifier"),
    entity_b: str = Query(..., description="Second entity identifier"),
) -> dict[str, Any]:
    """Get head-to-head matchup analysis."""
    profile = _service.get_matchup_analysis(sport, entity_a, entity_b)
    return {
        "sport": profile.sport,
        "entity_a": profile.entity_a_id,
        "entity_b": profile.entity_b_id,
        "probabilities": profile.probabilities,
        "comparison": profile.comparison,
        "advantages": profile.advantages,
    }


@router.post("/simulate")
async def post_simulate(req: SimulateRequest) -> dict[str, Any]:
    """Run a full Monte Carlo simulation with analysis.

    Accepts team identifiers and optional custom probability
    distributions. Returns win probabilities, score distributions,
    and optional sportsbook comparison.
    """
    game_context: dict[str, Any] = {
        "home_team": req.home_team,
        "away_team": req.away_team,
    }

    if req.home_probabilities:
        game_context["home_probabilities"] = req.home_probabilities
    if req.away_probabilities:
        game_context["away_probabilities"] = req.away_probabilities
    if req.probability_mode:
        game_context["probability_mode"] = req.probability_mode

    result = _service.run_full_simulation(
        sport=req.sport,
        game_context=game_context,
        iterations=req.iterations,
        seed=req.seed,
        sportsbook=req.sportsbook,
    )

    response = {
        "sport": req.sport,
        "home_team": req.home_team,
        "away_team": req.away_team,
        **result,
    }

    # Auto-store prediction for calibration
    _prediction_repo.save_prediction({
        "sport": req.sport,
        "home_team": req.home_team,
        "away_team": req.away_team,
        "model_output": {
            "home_win_probability": result.get("home_win_probability", 0),
            "away_win_probability": result.get("away_win_probability", 0),
            "expected_home_score": result.get("average_home_score", 0),
            "expected_away_score": result.get("average_away_score", 0),
        },
        "sportsbook_lines": req.sportsbook,
    })

    return response


@router.post("/live-simulate")
async def post_live_simulate(req: LiveSimulateRequest) -> dict[str, Any]:
    """Run a simulation from a live game state.

    Accepts current inning, outs, base runners, and score. Returns
    win probabilities and expected final score.
    """
    game_state: dict[str, Any] = {
        "inning": req.inning,
        "half": req.half,
        "outs": req.outs,
        "bases": req.bases,
        "score": req.score,
    }

    if req.home_probabilities:
        game_state["home_probabilities"] = req.home_probabilities
    if req.away_probabilities:
        game_state["away_probabilities"] = req.away_probabilities
    if req.probability_mode:
        game_state["probability_mode"] = req.probability_mode

    result = _service.run_live_simulation(
        sport=req.sport,
        game_state=game_state,
        iterations=req.iterations,
        seed=req.seed,
    )

    return {"sport": req.sport, **result}


@router.post("/simulate-job")
async def post_simulate_job(req: SimulateRequest) -> dict[str, Any]:
    """Submit a simulation as a background job.

    Returns a job_id immediately. Poll ``/simulation-result`` to
    retrieve the result once complete.
    """
    params: dict[str, Any] = {
        "sport": req.sport,
        "home_team": req.home_team,
        "away_team": req.away_team,
        "iterations": req.iterations,
        "mode": "pregame",
    }
    if req.seed is not None:
        params["seed"] = req.seed
    if req.home_probabilities:
        params["home_probabilities"] = req.home_probabilities
    if req.away_probabilities:
        params["away_probabilities"] = req.away_probabilities
    if req.sportsbook:
        params["sportsbook"] = req.sportsbook

    job_id = _job_manager.submit_job(params, sync=True)
    status = _job_manager.get_job_status(job_id)
    return status


@router.post("/live-simulate-job")
async def post_live_simulate_job(req: LiveSimulateRequest) -> dict[str, Any]:
    """Submit a live simulation as a background job."""
    params: dict[str, Any] = {
        "sport": req.sport,
        "inning": req.inning,
        "half": req.half,
        "outs": req.outs,
        "bases": req.bases,
        "score": req.score,
        "iterations": req.iterations,
        "mode": "live",
    }
    if req.seed is not None:
        params["seed"] = req.seed
    if req.home_probabilities:
        params["home_probabilities"] = req.home_probabilities
    if req.away_probabilities:
        params["away_probabilities"] = req.away_probabilities

    job_id = _job_manager.submit_job(params, sync=True)
    status = _job_manager.get_job_status(job_id)
    return status


@router.get("/simulation-result")
async def get_simulation_result(
    job_id: str = Query(..., description="Job ID from simulate-job endpoint"),
) -> dict[str, Any]:
    """Poll for simulation job result.

    Returns the job status and result if complete.
    """
    status = _job_manager.get_job_status(job_id)
    result = _job_manager.get_job_result(job_id)

    if result is not None:
        return {**status, "result": result}
    return status


@router.get("/simulation-history")
async def get_simulation_history(
    sport: str = Query(None, description="Filter by sport code"),
    limit: int = Query(50, ge=1, le=200, description="Max results"),
) -> dict[str, Any]:
    """List stored simulation results."""
    records = _repository.list_simulations(sport=sport, limit=limit)
    return {"simulations": records, "count": len(records)}


class RecordOutcomeRequest(BaseModel):
    """Request body for POST /api/analytics/record-outcome."""
    prediction_id: str = Field(..., description="Prediction to update")
    home_score: int = Field(..., ge=0, description="Actual home score")
    away_score: int = Field(..., ge=0, description="Actual away score")


@router.post("/record-outcome")
async def post_record_outcome(req: RecordOutcomeRequest) -> dict[str, Any]:
    """Record an actual game outcome for a stored prediction."""
    actual = {"home_score": req.home_score, "away_score": req.away_score}
    updated = _prediction_repo.record_outcome(req.prediction_id, actual)
    if not updated:
        return {"status": "not_found", "prediction_id": req.prediction_id}

    pred = _prediction_repo.get_prediction(req.prediction_id)
    evaluation = _calibration.evaluate_prediction(pred, actual)
    return {"status": "recorded", **evaluation}


@router.get("/model-performance")
async def get_model_performance(
    sport: str = Query(None, description="Filter by sport code"),
) -> dict[str, Any]:
    """Get aggregate model performance metrics.

    Returns Brier score, log loss, MAE, accuracy, bias, and
    calibration buckets.
    """
    predictions = _prediction_repo.get_evaluated_predictions(sport=sport)

    if not predictions:
        report = _calibration._empty_report()
        metrics = _model_metrics._empty_metrics()
    else:
        report = _calibration.calibration_report(predictions)
        metrics = _model_metrics.compute_all(predictions)

    return {
        **report,
        "log_loss": metrics.get("log_loss", 0.0),
        "mae_score": metrics.get("mae_score", 0.0),
        "mae_total": metrics.get("mae_total", 0.0),
        "calibration_buckets": metrics.get("calibration_buckets", []),
    }


@router.get("/predictions")
async def get_predictions(
    sport: str = Query(None, description="Filter by sport code"),
    limit: int = Query(100, ge=1, le=500, description="Max results"),
) -> dict[str, Any]:
    """List stored predictions."""
    records = _prediction_repo.list_predictions(sport=sport, limit=limit)
    return {"predictions": records, "count": len(records)}


# ---------------------------------------------------------------------------
# Feature Loadout CRUD endpoints (DB-backed)
# ---------------------------------------------------------------------------


class FeatureLoadoutCreateRequest(BaseModel):
    """Request body for POST /api/analytics/feature-config."""
    name: str = Field(..., description="Loadout name")
    sport: str = Field(..., description="Sport code (e.g., mlb)")
    model_type: str = Field(..., description="Model type (e.g., plate_appearance, game)")
    features: list[dict[str, Any]] = Field(
        ..., description="Array of {name, enabled, weight} dicts",
    )
    is_default: bool = Field(False, description="Whether this is the default loadout")


class FeatureLoadoutUpdateRequest(BaseModel):
    """Request body for PUT /api/analytics/feature-config/{id}."""
    name: str | None = Field(None, description="New loadout name")
    sport: str | None = Field(None, description="Sport code")
    model_type: str | None = Field(None, description="Model type")
    features: list[dict[str, Any]] | None = Field(
        None, description="Array of {name, enabled, weight} dicts",
    )
    is_default: bool | None = Field(None, description="Default flag")


def _serialize_loadout(row: AnalyticsFeatureConfig) -> dict[str, Any]:
    """Serialize a DB feature config row to API response dict."""
    features = row.features or []
    enabled = [f["name"] for f in features if f.get("enabled", True)]
    return {
        "id": row.id,
        "name": row.name,
        "sport": row.sport,
        "model_type": row.model_type,
        "features": features,
        "is_default": row.is_default,
        "enabled_count": len(enabled),
        "total_count": len(features),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("/feature-configs")
async def list_feature_configs(
    sport: str = Query(None, description="Filter by sport"),
    model_type: str = Query(None, description="Filter by model type"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List all saved feature loadouts."""
    stmt = select(AnalyticsFeatureConfig).order_by(
        AnalyticsFeatureConfig.updated_at.desc()
    )
    if sport:
        stmt = stmt.where(AnalyticsFeatureConfig.sport == sport)
    if model_type:
        stmt = stmt.where(AnalyticsFeatureConfig.model_type == model_type)

    result = await db.execute(stmt)
    rows = result.scalars().all()
    loadouts = [_serialize_loadout(r) for r in rows]

    return {
        "loadouts": loadouts,
        "count": len(loadouts),
    }


@router.get("/feature-config/{config_id}")
async def get_feature_config_by_id(
    config_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get a feature loadout by ID."""
    row = await db.get(AnalyticsFeatureConfig, config_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Feature config not found")
    return _serialize_loadout(row)


@router.post("/feature-config")
async def create_feature_config(
    req: FeatureLoadoutCreateRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create a new feature loadout."""
    row = AnalyticsFeatureConfig(
        name=req.name,
        sport=req.sport.lower(),
        model_type=req.model_type,
        features=req.features,
        is_default=req.is_default,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return {"status": "created", **_serialize_loadout(row)}


@router.put("/feature-config/{config_id}")
async def update_feature_config(
    config_id: int,
    req: FeatureLoadoutUpdateRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Update an existing feature loadout."""
    row = await db.get(AnalyticsFeatureConfig, config_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Feature config not found")

    if req.name is not None:
        row.name = req.name
    if req.sport is not None:
        row.sport = req.sport.lower()
    if req.model_type is not None:
        row.model_type = req.model_type
    if req.features is not None:
        row.features = req.features
    if req.is_default is not None:
        row.is_default = req.is_default

    await db.flush()
    await db.refresh(row)
    return {"status": "updated", **_serialize_loadout(row)}


@router.delete("/feature-config/{config_id}")
async def delete_feature_config(
    config_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Delete a feature loadout."""
    row = await db.get(AnalyticsFeatureConfig, config_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Feature config not found")
    name = row.name
    await db.delete(row)
    return {"status": "deleted", "id": config_id, "name": name}


@router.post("/feature-config/{config_id}/clone")
async def clone_feature_config(
    config_id: int,
    name: str = Query(None, description="Name for the cloned loadout"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Clone an existing feature loadout."""
    row = await db.get(AnalyticsFeatureConfig, config_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Feature config not found")

    clone_name = name or f"{row.name} (copy)"
    clone = AnalyticsFeatureConfig(
        name=clone_name,
        sport=row.sport,
        model_type=row.model_type,
        features=list(row.features),
        is_default=False,
    )
    db.add(clone)
    await db.flush()
    await db.refresh(clone)
    return {"status": "cloned", **_serialize_loadout(clone)}


@router.get("/available-features")
async def get_available_features(
    sport: str = Query("mlb", description="Sport code"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List available features from data for a given sport.

    Returns feature definitions with descriptions, data types,
    and coverage stats from the database.
    """
    if sport.lower() == "mlb":
        return await _get_mlb_available_features(db)
    return {"sport": sport, "features": [], "message": "Sport not supported yet"}


async def _get_mlb_available_features(db: AsyncSession) -> dict[str, Any]:
    """Get available MLB features from the MLBFeatureBuilder and DB stats."""
    from app.analytics.features.sports.mlb_features import _PA_FEATURES, _GAME_FEATURES
    from app.db.mlb_advanced import MLBGameAdvancedStats

    # Count total games with advanced stats for coverage calculation
    from sqlalchemy import func as sa_func
    count_result = await db.execute(
        select(sa_func.count(MLBGameAdvancedStats.id))
    )
    total_games = count_result.scalar() or 0

    # Build feature catalog from the MLBFeatureBuilder specs
    pa_features = []
    for feat_name, entity, source_key in _PA_FEATURES:
        pa_features.append({
            "name": feat_name,
            "entity": entity,
            "source_key": source_key,
            "description": _feature_description(feat_name, source_key),
            "data_type": "float",
            "model_types": ["plate_appearance"],
        })

    game_features = []
    for feat_name, entity, source_key in _GAME_FEATURES:
        game_features.append({
            "name": feat_name,
            "entity": entity,
            "source_key": source_key,
            "description": _feature_description(feat_name, source_key),
            "data_type": "float",
            "model_types": ["game"],
        })

    return {
        "sport": "mlb",
        "total_games_with_data": total_games,
        "plate_appearance_features": pa_features,
        "game_features": game_features,
        "all_features": pa_features + game_features,
    }


def _feature_description(feat_name: str, source_key: str) -> str:
    """Generate a human-readable description for a feature."""
    descriptions: dict[str, str] = {
        "contact_rate": "Rate of contact made on swings",
        "power_index": "Composite power metric based on exit velocity and barrel rate",
        "barrel_rate": "Percentage of batted balls classified as barrels",
        "hard_hit_rate": "Percentage of batted balls with exit velocity >= 95 mph",
        "swing_rate": "Percentage of pitches swung at",
        "whiff_rate": "Percentage of swings that miss (swinging strikes / swings)",
        "avg_exit_velocity": "Average exit velocity on batted balls (mph)",
        "expected_slug": "Expected slugging percentage based on quality of contact",
    }
    prefix = feat_name.split("_")[0]
    entity_label = {
        "batter": "Batter's", "pitcher": "Pitcher's",
        "home": "Home team's", "away": "Away team's",
    }.get(prefix, "")
    base_desc = descriptions.get(source_key, source_key.replace("_", " "))
    return f"{entity_label} {base_desc}".strip()


# ---------------------------------------------------------------------------
# Training Pipeline endpoints
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
    Returns the job ID for polling.
    """
    from app.db.analytics import AnalyticsTrainingJob

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

    # Dispatch Celery task
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


# ---------------------------------------------------------------------------
# Backtest endpoints
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
    """Start a model backtest job.

    Creates a backtest job record and dispatches a Celery task.
    The task loads the model, runs predictions on games in the
    date range, and stores per-game results.
    """
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
    """Get details for a specific backtest job, including per-game predictions."""
    from app.db.analytics import AnalyticsBacktestJob

    job = await db.get(AnalyticsBacktestJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Backtest job not found")
    return _serialize_backtest_job(job)


# ---------------------------------------------------------------------------
# Batch Simulation endpoints
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
    from app.tasks.training_tasks import batch_simulate_games

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
    """List batch simulation jobs, optionally filtered by sport."""
    from sqlalchemy import select

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
# Model Inference endpoints
# ---------------------------------------------------------------------------


class ModelPredictRequest(BaseModel):
    """Request body for POST /api/analytics/model-predict."""
    sport: str = Field(..., description="Sport code (e.g., mlb)")
    model_type: str = Field(..., description="Model type (e.g., plate_appearance, game)")
    profiles: dict[str, Any] = Field(
        ..., description="Entity profiles for prediction",
    )
    config_name: str | None = Field(
        None, description="Optional feature config name",
    )


@router.post("/model-predict")
async def post_model_predict(req: ModelPredictRequest) -> dict[str, Any]:
    """Generate a prediction using the active ML model.

    Builds features from profiles, runs inference, and returns
    structured probability output.
    """
    probs = _inference_engine.predict_proba(
        sport=req.sport,
        model_type=req.model_type,
        profiles=req.profiles,
        config_name=req.config_name,
    )
    return {
        "sport": req.sport,
        "model_type": req.model_type,
        "probabilities": probs,
    }


@router.get("/model-predict")
async def get_model_predict(
    sport: str = Query(..., description="Sport code"),
    model_type: str = Query(..., description="Model type"),
) -> dict[str, Any]:
    """Get model info and sample prediction with empty profiles."""
    probs = _inference_engine.predict_proba(
        sport=sport,
        model_type=model_type,
        profiles={},
    )
    return {
        "sport": sport,
        "model_type": model_type,
        "probabilities": probs,
    }


# ---------------------------------------------------------------------------
# Model Registry endpoints
# ---------------------------------------------------------------------------


class ModelActivateRequest(BaseModel):
    """Request body for POST /api/analytics/models/activate."""
    sport: str = Field(..., description="Sport code (e.g., mlb)")
    model_type: str = Field(..., description="Model type (e.g., plate_appearance)")
    model_id: str = Field(..., description="Model ID to activate")


@router.get("/models")
async def get_models(
    sport: str = Query(None, description="Filter by sport code"),
    model_type: str = Query(None, description="Filter by model type"),
    sort_by: str = Query(
        None, description="Sort key (created_at, accuracy, log_loss, brier_score, version)",
    ),
    sort_desc: bool = Query(True, description="Sort descending"),
    active_only: bool = Query(False, description="Only show active models"),
) -> dict[str, Any]:
    """List registered models with active status, filtering, and sorting."""
    return _model_service.list_models(
        sport=sport,
        model_type=model_type,
        sort_by=sort_by,
        sort_desc=sort_desc,
        active_only=active_only,
    )


@router.get("/models/details")
async def get_model_details(
    model_id: str = Query(..., description="Model ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get full details for a single registered model.

    Enriches registry data with feature importance from the
    training job if available.
    """
    details = _model_service.get_model_details(model_id)
    if details is None:
        return {"status": "not_found", "model_id": model_id}

    # Look up feature importance from the training job
    from app.db.analytics import AnalyticsTrainingJob

    stmt = (
        select(AnalyticsTrainingJob)
        .where(AnalyticsTrainingJob.model_id == model_id)
        .order_by(AnalyticsTrainingJob.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    training_job = result.scalar_one_or_none()
    if training_job:
        fi = getattr(training_job, "feature_importance", None)
        if fi:
            details["feature_importance"] = fi

    return details


@router.get("/models/compare")
async def get_model_compare(
    sport: str = Query(..., description="Sport code"),
    model_type: str = Query(..., description="Model type"),
    model_ids: str = Query(..., description="Comma-separated model IDs"),
) -> dict[str, Any]:
    """Compare evaluation metrics across model versions."""
    ids = [mid.strip() for mid in model_ids.split(",") if mid.strip()]
    return _model_service.compare_models(sport, model_type, ids)


@router.post("/models/activate")
async def post_activate_model(req: ModelActivateRequest) -> dict[str, Any]:
    """Activate a registered model.

    Validates the model exists, verifies artifact/metadata paths,
    updates the registry, and clears the inference cache so the
    new model is loaded on the next request.
    """
    result = _model_service.activate_model(
        sport=req.sport,
        model_type=req.model_type,
        model_id=req.model_id,
    )
    if result["status"] == "success":
        # Clear inference cache so the new model is loaded on next request
        _inference_engine._cache.clear()
    return result


@router.get("/models/active")
async def get_active_models(
    sport: str = Query(..., description="Sport code"),
    model_type: str = Query(..., description="Model type"),
) -> dict[str, Any]:
    """Get the currently active model for a sport + model type."""
    active = _model_registry.get_active_model(sport, model_type)
    if active is None:
        return {
            "sport": sport,
            "model_type": model_type,
            "active_model": None,
        }
    return {
        "sport": sport,
        "model_type": model_type,
        "active_model": active["model_id"],
        "version": active.get("version"),
        "metrics": active.get("metrics", {}),
    }


@router.get("/model-metrics")
async def get_model_metrics(
    model_id: str = Query(None, description="Filter by model ID"),
    sport: str = Query(None, description="Filter by sport code"),
    model_type: str = Query(None, description="Filter by model type"),
) -> dict[str, Any]:
    """Get evaluation metrics for registered models.

    Returns metrics from the model registry. If model_id is specified,
    returns metrics for that model. Otherwise returns metrics for all
    models matching the filters.
    """
    models = _model_registry.list_models(sport=sport, model_type=model_type)

    if model_id:
        models = [m for m in models if m["model_id"] == model_id]

    if not models:
        return {"models": [], "count": 0}

    results = []
    for m in models:
        results.append({
            "model_id": m["model_id"],
            "sport": m.get("sport", ""),
            "model_type": m.get("model_type", ""),
            "version": m.get("version"),
            "active": m.get("active", False),
            "metrics": m.get("metrics", {}),
        })

    return {"models": results, "count": len(results)}


# ---------------------------------------------------------------------------
# Ensemble Configuration endpoints
# ---------------------------------------------------------------------------


class EnsembleConfigRequest(BaseModel):
    """Request body for POST /api/analytics/ensemble-config."""
    sport: str = Field(..., description="Sport code (e.g., mlb)")
    model_type: str = Field(..., description="Model type (e.g., plate_appearance)")
    providers: list[dict[str, Any]] = Field(
        ..., description="List of {name, weight} dicts",
    )


@router.get("/ensemble-config")
async def get_ensemble_config_endpoint(
    sport: str = Query(..., description="Sport code"),
    model_type: str = Query(..., description="Model type"),
) -> dict[str, Any]:
    """Get the ensemble configuration for a sport + model type."""
    from app.analytics.ensemble.ensemble_config import get_ensemble_config
    config = get_ensemble_config(sport, model_type)
    return config.to_dict()


@router.get("/ensemble-configs")
async def list_ensemble_configs_endpoint() -> dict[str, Any]:
    """List all ensemble configurations."""
    from app.analytics.ensemble.ensemble_config import list_ensemble_configs
    configs = list_ensemble_configs()
    return {"configs": [c.to_dict() for c in configs], "count": len(configs)}


@router.post("/ensemble-config")
async def post_ensemble_config(req: EnsembleConfigRequest) -> dict[str, Any]:
    """Update ensemble configuration for a sport + model type."""
    from app.analytics.ensemble.ensemble_config import (
        EnsembleConfig,
        ProviderWeight,
        set_ensemble_config,
    )

    providers = [
        ProviderWeight(name=p["name"], weight=float(p["weight"]))
        for p in req.providers
    ]
    config = EnsembleConfig(
        sport=req.sport,
        model_type=req.model_type,
        providers=providers,
    )
    set_ensemble_config(config)
    return {"status": "updated", **config.to_dict()}


# ---------------------------------------------------------------------------
# MLB Advanced Model endpoints
# ---------------------------------------------------------------------------


@router.get("/mlb/pitch-model")
async def get_pitch_model(
    pitcher_k_rate: float = Query(0.22, description="Pitcher K rate"),
    batter_contact_rate: float = Query(0.80, description="Batter contact rate"),
    count_balls: int = Query(0, ge=0, le=3, description="Balls"),
    count_strikes: int = Query(0, ge=0, le=2, description="Strikes"),
) -> dict[str, Any]:
    """Get pitch outcome probabilities from the pitch model."""
    from app.analytics.models.sports.mlb.pitch_model import MLBPitchOutcomeModel

    model = MLBPitchOutcomeModel()
    probs = model.predict_proba({
        "pitcher_k_rate": pitcher_k_rate,
        "batter_contact_rate": batter_contact_rate,
        "count_balls": count_balls,
        "count_strikes": count_strikes,
    })
    return {"pitch_probabilities": probs}


@router.get("/mlb/pitch-sim")
async def get_pitch_sim(
    pitcher_k_rate: float = Query(0.22, description="Pitcher K rate"),
    batter_contact_rate: float = Query(0.80, description="Batter contact rate"),
) -> dict[str, Any]:
    """Simulate a single plate appearance at the pitch level."""
    from app.analytics.simulation.mlb.pitch_simulator import PitchSimulator

    sim = PitchSimulator()
    result = sim.simulate_plate_appearance({
        "pitcher_k_rate": pitcher_k_rate,
        "batter_contact_rate": batter_contact_rate,
    })
    return result


@router.get("/mlb/run-expectancy")
async def get_run_expectancy(
    base_state: int = Query(0, ge=0, le=7, description="Base state (0-7)"),
    outs: int = Query(0, ge=0, le=2, description="Outs"),
    batter_quality: float = Query(0.0, description="Batter quality (0-1)"),
    pitcher_quality: float = Query(0.0, description="Pitcher quality (0-1)"),
) -> dict[str, Any]:
    """Get run expectancy for a given game state."""
    from app.analytics.models.sports.mlb.run_expectancy_model import (
        MLBRunExpectancyModel,
    )

    model = MLBRunExpectancyModel()
    result = model.predict({
        "base_state": base_state,
        "outs": outs,
        "batter_quality": batter_quality,
        "pitcher_quality": pitcher_quality,
    })
    return result
