"""Analytics API endpoints.

Provides REST endpoints for team analysis, player analysis, matchup
comparison, and game simulation. All endpoints return structured JSON
and delegate to the AnalyticsService layer.

Routes:
    GET  /api/analytics/team          — Team analytical profile
    GET  /api/analytics/player        — Player analytical profile
    GET  /api/analytics/matchup       — Head-to-head matchup analysis
    GET  /api/analytics/simulation    — Game simulation results (legacy)
    POST /api/analytics/simulate      — Full Monte Carlo simulation
    POST /api/analytics/live-simulate — Live game simulation from state
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.analytics.core.model_calibration import ModelCalibration
from app.analytics.core.model_metrics import ModelMetrics
from app.analytics.core.prediction_repository import PredictionRepository
from app.analytics.core.simulation_cache import SimulationCache
from app.analytics.core.simulation_job_manager import SimulationJobManager
from app.analytics.core.simulation_repository import SimulationRepository
from app.analytics.features.config.feature_config_loader import FeatureConfigLoader
from app.analytics.features.config.feature_config_registry import FeatureConfigRegistry
from app.analytics.inference.model_inference_engine import ModelInferenceEngine
from app.analytics.models.core.model_registry import ModelRegistry
from app.analytics.services.analytics_service import AnalyticsService
from app.analytics.services.model_service import ModelService

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

_service = AnalyticsService()
_cache = SimulationCache()
_repository = SimulationRepository()
_job_manager = SimulationJobManager(cache=_cache, repository=_repository)
_prediction_repo = PredictionRepository()
_calibration = ModelCalibration()
_model_metrics = ModelMetrics()
_feature_config_loader = FeatureConfigLoader()
_feature_config_registry = FeatureConfigRegistry(loader=_feature_config_loader)
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


@router.get("/simulation")
async def get_simulation(
    sport: str = Query(..., description="Sport code (e.g., mlb, nba)"),
    iterations: int = Query(1000, ge=1, le=100000, description="Simulation iterations"),
) -> dict[str, Any]:
    """Run a game simulation and return results (legacy endpoint)."""
    result = _service.run_simulation(sport, game_context={}, iterations=iterations)
    return {
        "sport": result.sport,
        "iterations": result.iterations,
        "summary": result.summary,
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
# Feature Configuration endpoints
# ---------------------------------------------------------------------------


class FeatureConfigUpdateRequest(BaseModel):
    """Request body for POST /api/analytics/feature-config."""
    model: str = Field(..., description="Config model name (e.g., mlb_pa_model_v1)")
    sport: str = Field(..., description="Sport code")
    features: dict[str, dict[str, Any]] = Field(
        ..., description="Feature definitions with enabled/weight",
    )


@router.get("/feature-config")
async def get_feature_config(
    model: str = Query(..., description="Config name (e.g., mlb_pa_model)"),
) -> dict[str, Any]:
    """Get a feature configuration by model name."""
    config = _feature_config_registry.get_config(model)
    if config is None:
        return {"status": "not_found", "model": model}

    return {
        "model": config.model,
        "sport": config.sport,
        "enabled_features": config.get_enabled_features(),
        "weights": config.get_weights(),
        "features": config.features,
    }


@router.get("/feature-configs")
async def list_feature_configs() -> dict[str, Any]:
    """List all available feature configurations."""
    available = _feature_config_registry.list_available()
    registered = _feature_config_registry.list_configs()
    return {"available": available, "registered": registered}


@router.post("/feature-config")
async def post_feature_config(req: FeatureConfigUpdateRequest) -> dict[str, Any]:
    """Register or update a feature configuration.

    Accepts a full feature config and registers it in the registry.
    """
    config = _feature_config_loader.load_from_dict(req.model_dump())
    _feature_config_registry.register(req.model, config)
    return {
        "status": "registered",
        "model": config.model,
        "sport": config.sport,
        "enabled_features": config.get_enabled_features(),
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
    sort_by: str = Query(None, description="Sort key (created_at, accuracy, log_loss, brier_score, version)"),
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
) -> dict[str, Any]:
    """Get full details for a single registered model."""
    details = _model_service.get_model_details(model_id)
    if details is None:
        return {"status": "not_found", "model_id": model_id}
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
