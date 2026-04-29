"""Celery tasks for analytics model training and backtesting.

Dispatched from the models UI when a user kicks off model training
or backtesting. Runs pipelines asynchronously and updates DB job rows
with results.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from datetime import UTC, datetime

from app.celery_app import celery_app
from app.tasks._task_infra import _complete_job_run, _start_job_run, _task_db

logger = logging.getLogger(__name__)


@celery_app.task(name="train_analytics_model", bind=True, max_retries=0)
def train_analytics_model(self, job_id: int) -> dict:
    """Train an analytics model for the given training job.

    Reads the job configuration from the DB, runs the training pipeline,
    and writes results back to the DB.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run_training(job_id, self.request.id))
    finally:
        loop.close()


async def _run_training(job_id: int, celery_task_id: str | None = None) -> dict:
    """Async implementation of the training pipeline."""
    from app.db.analytics import AnalyticsFeatureConfig, AnalyticsTrainingJob

    async with _task_db() as sf:
        # Register in the shared job-runs table
        run_id = await _start_job_run(
            sf, "analytics_train", celery_task_id,
            summary_data={"analytics_job_id": job_id},
        )

        async with sf() as db:
            job = await db.get(AnalyticsTrainingJob, job_id)
            if job is None:
                await _complete_job_run(sf, run_id, "error", "job_not_found")
                return {"error": "job_not_found", "job_id": job_id}

            # Mark as running
            job.status = "running"
            if celery_task_id:
                job.celery_task_id = celery_task_id
            await db.commit()

            # Load feature config if set
            feature_config = None
            if job.feature_config_id:
                feature_config = await db.get(AnalyticsFeatureConfig, job.feature_config_id)

        # Run training outside the DB session (it may take minutes)
        try:
            result = await _execute_training(
                sf=sf,
                sport=job.sport,
                model_type=job.model_type,
                algorithm=job.algorithm,
                test_split=job.test_split,
                random_state=job.random_state,
                date_start=job.date_start,
                date_end=job.date_end,
                rolling_window=getattr(job, "rolling_window", 30),
                feature_config=feature_config,
            )
        except Exception as exc:
            logger.exception("training_failed", extra={"job_id": job_id})
            async with sf() as db:
                job = await db.get(AnalyticsTrainingJob, job_id)
                if job:
                    job.status = "failed"
                    job.error_message = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
                    job.completed_at = datetime.now(UTC)
                    await db.commit()
            await _complete_job_run(sf, run_id, "error", str(exc)[:500])
            return {"error": str(exc), "job_id": job_id}

        # Write results back
        async with sf() as db:
            job = await db.get(AnalyticsTrainingJob, job_id)
            if job:
                if "error" in result:
                    job.status = "failed"
                    job.error_message = result.get("error", "unknown")
                else:
                    job.status = "completed"
                    job.model_id = result.get("model_id")
                    job.artifact_path = result.get("artifact_path")
                    job.metrics = result.get("metrics")
                    job.train_count = result.get("train_count")
                    job.test_count = result.get("test_count")
                    job.feature_names = result.get("feature_names")
                    job.feature_importance = result.get("feature_importance")
                job.completed_at = datetime.now(UTC)
                await db.commit()

        summary = {
            "analytics_job_id": job_id,
            "model_id": result.get("model_id"),
            "train_count": result.get("train_count"),
            "test_count": result.get("test_count"),
        }
        final_status = "error" if "error" in result else "success"
        await _complete_job_run(sf, run_id, final_status, summary_data=summary)

    return result


def _feature_config_to_dict(
    feature_config: object | None,
) -> dict[str, dict] | None:
    """Convert a DB AnalyticsFeatureConfig to the dict format expected by FeatureBuilder.

    DB format (JSONB array): [{"name": "feat", "enabled": true, "weight": 1.0}, ...]
    FeatureBuilder format:   {"feat": {"enabled": True, "weight": 1.0}, ...}
    """
    if feature_config is None:
        return None
    features = getattr(feature_config, "features", None)
    if not features:
        return None
    return {
        f["name"]: {"enabled": f.get("enabled", True), "weight": f.get("weight", 1.0)}
        for f in features
        if "name" in f
    }


async def _execute_training(
    *,
    sf,
    sport: str,
    model_type: str,
    algorithm: str,
    test_split: float,
    random_state: int,
    date_start: str | None,
    date_end: str | None,
    rolling_window: int = 30,
    feature_config: object | None,
) -> dict:
    """Execute the actual training pipeline.

    Loads historical data from the DB, builds the dataset using the
    feature config, trains the model, and returns results.
    """
    import uuid

    from app.analytics.training.core.training_pipeline import TrainingPipeline

    model_id = f"{sport}_{model_type}_{uuid.uuid4().hex[:8]}"
    config_dict = _feature_config_to_dict(feature_config)

    pipeline = TrainingPipeline(
        sport=sport,
        model_type=model_type,
        config_name="",  # We'll pass records directly
        model_id=model_id,
        random_state=random_state,
        test_size=test_split,
        feature_config=config_dict,
    )

    # Load training data from DB using the task's session factory
    async with sf() as db:
        records = await _load_training_data_from_db(
            sport=sport,
            model_type=model_type,
            date_start=date_start,
            date_end=date_end,
            rolling_window=rolling_window,
            db=db,
        )

    if not records:
        return {"error": "no_training_data", "model_id": model_id}

    # Get sklearn model based on algorithm choice
    sklearn_model = _get_sklearn_model(algorithm, model_type, random_state)

    # Run pipeline
    result = pipeline.run(records=records, sklearn_model=sklearn_model)
    return result


# ---------------------------------------------------------------------------
# Backtest task
# ---------------------------------------------------------------------------


@celery_app.task(name="backtest_analytics_model", bind=True, max_retries=0)
def backtest_analytics_model(self, job_id: int) -> dict:
    """Backtest a trained model against held-out games.

    Loads the model artifact, runs predictions on games in the
    configured date range, and compares to actual outcomes.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run_backtest(job_id, self.request.id))
    finally:
        loop.close()


async def _run_backtest(job_id: int, celery_task_id: str | None = None) -> dict:
    """Async implementation of the backtest pipeline."""
    from app.db.analytics import AnalyticsBacktestJob

    async with _task_db() as sf:
        run_id = await _start_job_run(
            sf, "analytics_backtest", celery_task_id,
            summary_data={"analytics_job_id": job_id},
        )

        async with sf() as db:
            job = await db.get(AnalyticsBacktestJob, job_id)
            if job is None:
                await _complete_job_run(sf, run_id, "error", "job_not_found")
                return {"error": "job_not_found", "job_id": job_id}

            job.status = "running"
            if celery_task_id:
                job.celery_task_id = celery_task_id
            await db.commit()

        try:
            result = await _execute_backtest(
                sf=sf,
                model_id=job.model_id,
                artifact_path=job.artifact_path,
                sport=job.sport,
                model_type=job.model_type,
                date_start=job.date_start,
                date_end=job.date_end,
                rolling_window=getattr(job, "rolling_window", 30),
            )
        except Exception as exc:
            logger.exception("backtest_failed", extra={"job_id": job_id})
            async with sf() as db:
                job = await db.get(AnalyticsBacktestJob, job_id)
                if job:
                    job.status = "failed"
                    job.error_message = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
                    job.completed_at = datetime.now(UTC)
                    await db.commit()
            await _complete_job_run(sf, run_id, "error", str(exc)[:500])
            return {"error": str(exc), "job_id": job_id}

        async with sf() as db:
            job = await db.get(AnalyticsBacktestJob, job_id)
            if job:
                if "error" in result:
                    job.status = "failed"
                    job.error_message = result.get("error", "unknown")
                else:
                    job.status = "completed"
                    job.game_count = result.get("game_count")
                    job.correct_count = result.get("correct_count")
                    job.metrics = result.get("metrics")
                    job.predictions = result.get("predictions")
                job.completed_at = datetime.now(UTC)
                await db.commit()

        summary = {
            "analytics_job_id": job_id,
            "game_count": result.get("game_count"),
            "accuracy": result.get("metrics", {}).get("accuracy"),
        }
        final_status = "error" if "error" in result else "success"
        await _complete_job_run(sf, run_id, final_status, summary_data=summary)

    return result


async def _execute_backtest(
    *,
    sf,
    model_id: str,
    artifact_path: str,
    sport: str,
    model_type: str,
    date_start: str | None,
    date_end: str | None,
    rolling_window: int = 30,
) -> dict:
    """Run model predictions against held-out games and compare to actuals."""
    # 1. Validate and load model artifact
    from pathlib import Path as _Path

    import joblib
    import numpy as np

    from app.analytics.features.core.feature_builder import FeatureBuilder
    from app.analytics.training.sports.mlb_training import MLBTrainingPipeline
    artifact = _Path(artifact_path) if artifact_path else None
    if not artifact or not artifact.exists():
        return {"error": f"Model artifact not found: {artifact_path}"}
    if not artifact.is_file():
        return {"error": f"Model artifact path is not a file: {artifact_path}"}
    try:
        from app.analytics.models.core.artifact_signing import verify_artifact
        verify_artifact(str(artifact))
        sklearn_model = joblib.load(str(artifact))
    except Exception as exc:
        return {"error": f"Failed to load model artifact: {exc}"}

    # 2. Load games with rolling profiles (same as training data loader)
    async with sf() as db:
        records = await _load_training_data_from_db(
            sport=sport,
            model_type=model_type,
            date_start=date_start,
            date_end=date_end,
            rolling_window=rolling_window,
            db=db,
        )

    if not records:
        return {"error": "no_backtest_data", "model_id": model_id}

    # 3. Build features and run predictions
    feature_builder = FeatureBuilder()
    mlb_pipeline = MLBTrainingPipeline()
    if model_type == "game":
        label_fn = mlb_pipeline.game_label_fn
    elif model_type == "plate_appearance":
        label_fn = mlb_pipeline.pa_label_fn
    else:
        label_fn = None

    predictions = []
    correct = 0
    brier_scores = []

    for record in records:
        # Build feature vector
        vec = feature_builder.build_features(sport, record, model_type)
        features = vec.to_array()

        if not features:
            continue

        # Get actual label
        actual_label = label_fn(record) if label_fn else record.get("home_win")
        if actual_label is None:
            continue

        # Run prediction
        try:
            features_2d = np.array([features])
            y_pred = sklearn_model.predict(features_2d)[0]

            # Get probability if available
            pred_proba = None
            if hasattr(sklearn_model, "predict_proba"):
                proba = sklearn_model.predict_proba(features_2d)[0]
                classes = list(sklearn_model.classes_)
                pred_proba = {str(c): round(float(p), 4) for c, p in zip(classes, proba, strict=False)}

            is_correct = y_pred == actual_label
            if is_correct:
                correct += 1

            # Brier score
            if pred_proba:
                if model_type == "game":
                    # Binary: home_win probability vs actual
                    home_win_prob = pred_proba.get("1", pred_proba.get(1, 0.5))
                    brier = (home_win_prob - float(actual_label)) ** 2
                    brier_scores.append(brier)
                elif model_type == "plate_appearance":
                    # Multi-class: sum of squared errors across all classes
                    brier = sum(
                        (float(p) - (1.0 if str(c) == str(actual_label) else 0.0)) ** 2
                        for c, p in pred_proba.items()
                    )
                    brier_scores.append(brier)

            pred_entry = {
                "predicted": int(y_pred) if hasattr(y_pred, "__int__") else y_pred,
                "actual": int(actual_label) if hasattr(actual_label, "__int__") else actual_label,
                "correct": bool(is_correct),
                "home_score": record.get("home_score"),
                "away_score": record.get("away_score"),
            }
            if pred_proba:
                pred_entry["probabilities"] = pred_proba

            predictions.append(pred_entry)
        except Exception as exc:
            logger.warning("backtest_prediction_error", extra={"error": str(exc)})
            continue

    if not predictions:
        return {"error": "no_valid_predictions", "model_id": model_id}

    game_count = len(predictions)
    accuracy = correct / game_count if game_count > 0 else 0.0
    avg_brier = sum(brier_scores) / len(brier_scores) if brier_scores else None

    metrics = {
        "accuracy": round(accuracy, 4),
        "correct": correct,
        "total": game_count,
    }
    if avg_brier is not None:
        metrics["brier_score"] = round(avg_brier, 6)

    logger.info(
        "backtest_complete",
        extra={
            "model_id": model_id,
            "game_count": game_count,
            "accuracy": accuracy,
        },
    )

    return {
        "model_id": model_id,
        "game_count": game_count,
        "correct_count": correct,
        "metrics": metrics,
        "predictions": predictions,
    }


# ---------------------------------------------------------------------------
# Shared helpers — imported from _training_helpers to keep this file focused
# on Celery task orchestration.
# ---------------------------------------------------------------------------

from app.tasks._training_data import (  # noqa: E402
    load_training_data_from_db as _load_training_data_from_db,
)
from app.tasks._training_helpers import (  # noqa: E402
    get_sklearn_model as _get_sklearn_model,
)
