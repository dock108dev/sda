"""Celery tasks for analytics model training and backtesting.

Dispatched from the workbench UI when a user kicks off model training
or backtesting. Runs pipelines asynchronously and updates DB job rows
with results.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from datetime import datetime, timezone

from contextlib import asynccontextmanager

from app.celery_app import celery_app

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _task_db():
    """Create a fresh async engine + session factory bound to the current loop.

    Celery tasks run in a new event loop per invocation.  The module-level
    engine in ``app.db`` binds its connection-pool futures to the loop that
    created it, so reusing it from a different loop raises
    "Future attached to a different loop".  Following the pattern in
    ``bulk_flow_generation.py``, we create a throwaway engine here and
    dispose of it when the task finishes.

    Yields a session factory — callers open/close individual sessions via
    ``async with sf() as db: ...`` as needed.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.config import settings

    engine = create_async_engine(settings.database_url, echo=False, future=True)
    factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    try:
        yield factory
    finally:
        await engine.dispose()


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
        async with sf() as db:
            job = await db.get(AnalyticsTrainingJob, job_id)
            if job is None:
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
                    job.completed_at = datetime.now(timezone.utc)
                    await db.commit()
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
                job.completed_at = datetime.now(timezone.utc)
                await db.commit()

    return result


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

    pipeline = TrainingPipeline(
        sport=sport,
        model_type=model_type,
        config_name="",  # We'll pass records directly
        model_id=model_id,
        random_state=random_state,
        test_size=test_split,
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
        async with sf() as db:
            job = await db.get(AnalyticsBacktestJob, job_id)
            if job is None:
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
                    job.completed_at = datetime.now(timezone.utc)
                    await db.commit()
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
                job.completed_at = datetime.now(timezone.utc)
                await db.commit()

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
    import joblib
    import numpy as np

    from app.analytics.features.core.feature_builder import FeatureBuilder
    from app.analytics.training.sports.mlb_training import MLBTrainingPipeline

    # 1. Load model artifact
    try:
        sklearn_model = joblib.load(artifact_path)
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
    label_fn = mlb_pipeline.game_label_fn if model_type == "game" else None

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
                pred_proba = {str(c): round(float(p), 4) for c, p in zip(classes, proba)}

            is_correct = y_pred == actual_label
            if is_correct:
                correct += 1

            # Brier score for binary classification
            if pred_proba and model_type == "game":
                # For game model, actual_label is 1 (home_win) or 0
                home_win_prob = pred_proba.get("1", pred_proba.get(1, 0.5))
                brier = (home_win_prob - float(actual_label)) ** 2
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
# Batch simulation task
# ---------------------------------------------------------------------------


@celery_app.task(name="batch_simulate_games", bind=True, max_retries=0)
def batch_simulate_games(self, job_id: int) -> dict:
    """Run Monte Carlo simulations on upcoming games.

    Loads scheduled/pregame games, builds rolling team profiles,
    and runs the SimulationEngine for each game.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run_batch_sim(job_id, self.request.id))
    finally:
        loop.close()


async def _run_batch_sim(job_id: int, celery_task_id: str | None = None) -> dict:
    """Async implementation of batch simulation."""
    from app.db.analytics import AnalyticsBatchSimJob

    async with _task_db() as sf:
        async with sf() as db:
            job = await db.get(AnalyticsBatchSimJob, job_id)
            if job is None:
                return {"error": "job_not_found", "job_id": job_id}

            job.status = "running"
            if celery_task_id:
                job.celery_task_id = celery_task_id
            await db.commit()

        try:
            result = await _execute_batch_sim(
                sf=sf,
                sport=job.sport,
                probability_mode=job.probability_mode,
                iterations=job.iterations,
                rolling_window=getattr(job, "rolling_window", 30),
                date_start=job.date_start,
                date_end=job.date_end,
            )
        except Exception as exc:
            logger.exception("batch_sim_failed", extra={"job_id": job_id})
            async with sf() as db:
                job = await db.get(AnalyticsBatchSimJob, job_id)
                if job:
                    job.status = "failed"
                    job.error_message = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
                    job.completed_at = datetime.now(timezone.utc)
                    await db.commit()
            return {"error": str(exc), "job_id": job_id}

        async with sf() as db:
            job = await db.get(AnalyticsBatchSimJob, job_id)
            if job:
                if "error" in result:
                    job.status = "failed"
                    job.error_message = result.get("error", "unknown")
                else:
                    job.status = "completed"
                    job.game_count = result.get("game_count")
                    job.results = result.get("results")
                    # Save individual predictions for outcome tracking
                    await _save_prediction_outcomes(
                        db, job_id, job.sport, job.probability_mode, result.get("results") or []
                    )
                job.completed_at = datetime.now(timezone.utc)
                await db.commit()

    return result


async def _save_prediction_outcomes(
    db: "AsyncSession",
    batch_sim_job_id: int,
    sport: str,
    probability_mode: str,
    results: list[dict],
) -> None:
    """Persist per-game predictions from a batch sim for later outcome matching."""
    from app.db.analytics import AnalyticsPredictionOutcome

    for game_result in results:
        # Skip error-only entries from failed per-game simulations
        if "error" in game_result or "home_win_probability" not in game_result:
            continue
        outcome = AnalyticsPredictionOutcome(
            game_id=game_result["game_id"],
            sport=sport,
            batch_sim_job_id=batch_sim_job_id,
            home_team=game_result["home_team"],
            away_team=game_result["away_team"],
            predicted_home_wp=game_result["home_win_probability"],
            predicted_away_wp=game_result["away_win_probability"],
            predicted_home_score=game_result.get("average_home_score"),
            predicted_away_score=game_result.get("average_away_score"),
            probability_mode=probability_mode,
            game_date=game_result.get("game_date"),
        )
        db.add(outcome)


# ---------------------------------------------------------------------------
# Auto-record outcomes
# ---------------------------------------------------------------------------


@celery_app.task(name="record_completed_outcomes", bind=True, max_retries=0)
def record_completed_outcomes(self) -> dict:
    """Scan for finalized games and record outcomes against stored predictions.

    Finds predictions in ``analytics_prediction_outcomes`` that have no
    outcome yet, checks whether the corresponding ``SportsGame`` has reached
    ``final`` status, and fills in the actual scores + evaluation metrics.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run_record_outcomes())
    finally:
        loop.close()


async def _run_record_outcomes() -> dict:
    """Match pending predictions against finalized games."""
    from sqlalchemy import select

    from app.db.analytics import AnalyticsPredictionOutcome
    from app.db.sports import SportsGame

    recorded = 0
    skipped = 0

    async with _task_db() as sf:
        async with sf() as db:
            # Find predictions that have not been resolved yet
            stmt = (
                select(AnalyticsPredictionOutcome)
                .where(AnalyticsPredictionOutcome.outcome_recorded_at.is_(None))
                .order_by(AnalyticsPredictionOutcome.id)
                .limit(500)
            )
            result = await db.execute(stmt)
            pending = list(result.scalars().all())

            if not pending:
                return {"recorded": 0, "skipped": 0, "pending": 0}

            # Batch-load the referenced games
            game_ids = list({p.game_id for p in pending})
            games_stmt = select(SportsGame).where(SportsGame.id.in_(game_ids))
            games_result = await db.execute(games_stmt)
            games_by_id: dict[int, SportsGame] = {
                g.id: g for g in games_result.scalars().all()
            }

            for pred in pending:
                game = games_by_id.get(pred.game_id)
                if game is None:
                    skipped += 1
                    continue

                # Only record for games that have reached final (or archived)
                if game.status not in ("final", "archived"):
                    skipped += 1
                    continue

                if game.home_score is None or game.away_score is None:
                    skipped += 1
                    continue

                home_win_actual = game.home_score > game.away_score
                predicted_home_win = pred.predicted_home_wp > 0.5
                correct = predicted_home_win == home_win_actual

                # Brier score: (predicted_probability - actual_outcome)^2
                actual_indicator = 1.0 if home_win_actual else 0.0
                brier = (pred.predicted_home_wp - actual_indicator) ** 2

                pred.actual_home_score = game.home_score
                pred.actual_away_score = game.away_score
                pred.home_win_actual = home_win_actual
                pred.correct_winner = correct
                pred.brier_score = round(brier, 6)
                pred.outcome_recorded_at = datetime.now(timezone.utc)
                recorded += 1

            await db.commit()

    logger.info(
        "record_completed_outcomes_done",
        extra={"recorded": recorded, "skipped": skipped},
    )
    return {"recorded": recorded, "skipped": skipped, "pending": len(pending)}


# ---------------------------------------------------------------------------
# Model degradation detection
# ---------------------------------------------------------------------------

# Thresholds for degradation alerts
_BRIER_WARNING_THRESHOLD = 0.03  # Brier increase of 0.03 triggers warning
_BRIER_CRITICAL_THRESHOLD = 0.06  # Brier increase of 0.06 triggers critical
_MIN_WINDOW_SIZE = 10  # Minimum predictions needed per window


@celery_app.task(name="check_model_degradation", bind=True, max_retries=0)
def check_model_degradation(self, sport: str = "mlb") -> dict:
    """Compare recent prediction accuracy against historical baseline.

    Splits resolved predictions into a baseline (older half) and recent
    (newer half) window. If the recent Brier score exceeds the baseline
    by more than the threshold, creates a degradation alert.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run_degradation_check(sport))
    finally:
        loop.close()


async def _run_degradation_check(sport: str) -> dict:
    """Compute rolling windows and detect Brier score degradation."""
    from sqlalchemy import select

    from app.db.analytics import AnalyticsDegradationAlert, AnalyticsPredictionOutcome

    async with _task_db() as sf:
        async with sf() as db:
            stmt = (
                select(AnalyticsPredictionOutcome)
                .where(
                    AnalyticsPredictionOutcome.outcome_recorded_at.isnot(None),
                    AnalyticsPredictionOutcome.sport == sport,
                    AnalyticsPredictionOutcome.brier_score.isnot(None),
                )
                .order_by(AnalyticsPredictionOutcome.outcome_recorded_at.asc())
            )
            result = await db.execute(stmt)
            outcomes = list(result.scalars().all())

            if len(outcomes) < _MIN_WINDOW_SIZE * 2:
                return {
                    "status": "insufficient_data",
                    "total": len(outcomes),
                    "required": _MIN_WINDOW_SIZE * 2,
                }

            # Split into baseline (first half) and recent (second half)
            midpoint = len(outcomes) // 2
            baseline = outcomes[:midpoint]
            recent = outcomes[midpoint:]

            baseline_brier = sum(o.brier_score for o in baseline) / len(baseline)
            recent_brier = sum(o.brier_score for o in recent) / len(recent)
            baseline_acc = sum(1 for o in baseline if o.correct_winner) / len(baseline)
            recent_acc = sum(1 for o in recent if o.correct_winner) / len(recent)

            delta_brier = recent_brier - baseline_brier
            delta_acc = recent_acc - baseline_acc

            alert_created = False
            severity = None

            if delta_brier >= _BRIER_CRITICAL_THRESHOLD:
                severity = "critical"
            elif delta_brier >= _BRIER_WARNING_THRESHOLD:
                severity = "warning"

            if severity:
                message = (
                    f"{sport.upper()} model degradation detected: "
                    f"Brier score rose from {baseline_brier:.4f} to {recent_brier:.4f} "
                    f"(+{delta_brier:.4f}). "
                    f"Accuracy dropped from {baseline_acc:.1%} to {recent_acc:.1%}. "
                    f"Based on {len(baseline)} baseline vs {len(recent)} recent predictions."
                )
                alert = AnalyticsDegradationAlert(
                    sport=sport,
                    alert_type="brier_degradation",
                    baseline_brier=round(baseline_brier, 6),
                    recent_brier=round(recent_brier, 6),
                    baseline_accuracy=round(baseline_acc, 4),
                    recent_accuracy=round(recent_acc, 4),
                    baseline_count=len(baseline),
                    recent_count=len(recent),
                    delta_brier=round(delta_brier, 6),
                    delta_accuracy=round(delta_acc, 4),
                    severity=severity,
                    message=message,
                )
                db.add(alert)
                await db.commit()
                alert_created = True

                logger.warning(
                    "model_degradation_detected",
                    extra={
                        "sport": sport,
                        "severity": severity,
                        "delta_brier": round(delta_brier, 4),
                    },
                )

    return {
        "status": "alert_created" if alert_created else "healthy",
        "sport": sport,
        "baseline_brier": round(baseline_brier, 4),
        "recent_brier": round(recent_brier, 4),
        "delta_brier": round(delta_brier, 4),
        "baseline_accuracy": round(baseline_acc, 4),
        "recent_accuracy": round(recent_acc, 4),
        "severity": severity,
        "baseline_count": len(baseline),
        "recent_count": len(recent),
    }


async def _execute_batch_sim(
    *,
    sf,
    sport: str,
    probability_mode: str,
    iterations: int,
    rolling_window: int,
    date_start: str | None,
    date_end: str | None,
) -> dict:
    """Run simulations on upcoming games using rolling team profiles."""
    from collections import defaultdict
    from datetime import date

    from sqlalchemy import select

    from app.analytics.core.simulation_engine import SimulationEngine
    from app.db.mlb_advanced import MLBGameAdvancedStats
    from app.db.sports import SportsGame, SportsTeam

    if sport.lower() != "mlb":
        return {"error": "only_mlb_supported"}

    async with sf() as db:
        # 1. Find upcoming games (scheduled or pregame)
        game_stmt = (
            select(SportsGame)
            .where(SportsGame.status.in_(["scheduled", "pregame"]))
            .order_by(SportsGame.game_date.asc())
        )

        # Apply date filters — default to today onward
        if date_start:
            game_stmt = game_stmt.where(SportsGame.game_date >= date_start)
        else:
            game_stmt = game_stmt.where(
                SportsGame.game_date >= date.today().isoformat()
            )
        if date_end:
            game_stmt = game_stmt.where(SportsGame.game_date <= date_end)

        # Filter to MLB games via league join
        from app.db.sports import SportsLeague
        mlb_league = await db.execute(
            select(SportsLeague.id).where(SportsLeague.abbreviation == "MLB")
        )
        mlb_league_id = mlb_league.scalar_one_or_none()
        if mlb_league_id:
            game_stmt = game_stmt.where(SportsGame.league_id == mlb_league_id)

        game_result = await db.execute(game_stmt)
        upcoming_games = game_result.scalars().all()

        if not upcoming_games:
            return {"error": "no_upcoming_games", "game_count": 0, "results": []}

        # 2. Load team names for display
        team_ids = set()
        for g in upcoming_games:
            team_ids.add(g.home_team_id)
            team_ids.add(g.away_team_id)

        team_stmt = select(SportsTeam).where(SportsTeam.id.in_(list(team_ids)))
        team_result = await db.execute(team_stmt)
        teams = {t.id: t for t in team_result.scalars().all()}

        # 3. Load all historical advanced stats for rolling profiles
        all_stats_stmt = (
            select(MLBGameAdvancedStats)
            .join(SportsGame, SportsGame.id == MLBGameAdvancedStats.game_id)
            .where(SportsGame.status == "final")
            .order_by(SportsGame.game_date.asc())
        )
        stats_result = await db.execute(all_stats_stmt)
        all_stats = stats_result.scalars().all()

        # Index by game_id
        stats_by_game: dict[int, list] = defaultdict(list)
        for s in all_stats:
            stats_by_game[s.game_id].append(s)

        # Get dates for all games with stats
        all_game_ids = list(stats_by_game.keys())
        game_dates: dict[int, str] = {}
        if all_game_ids:
            dates_stmt = select(SportsGame.id, SportsGame.game_date).where(
                SportsGame.id.in_(all_game_ids)
            )
            dates_result = await db.execute(dates_stmt)
            for gid, gdate in dates_result:
                game_dates[gid] = str(gdate)

        # Build per-team chronological history
        team_history: dict[int, list[tuple[str, object]]] = defaultdict(list)
        for game_id, stats_list in stats_by_game.items():
            gdate = game_dates.get(game_id, "")
            for s in stats_list:
                team_history[s.team_id].append((gdate, s))

        for tid in team_history:
            team_history[tid].sort(key=lambda x: x[0])

    # 4. Run simulations for each upcoming game
    engine = SimulationEngine(sport)
    sim_results = []

    for game in upcoming_games:
        home_team = teams.get(game.home_team_id)
        away_team = teams.get(game.away_team_id)
        home_name = home_team.name if home_team else f"Team {game.home_team_id}"
        away_name = away_team.name if away_team else f"Team {game.away_team_id}"

        # Build rolling profiles
        game_date_str = str(game.game_date)[:10]  # YYYY-MM-DD
        # Use tomorrow as cutoff so today's completed games are included
        profile_cutoff = game_date_str + "Z"  # Compare as string, anything today or before

        home_profile = _build_rolling_profile(
            team_history.get(game.home_team_id, []),
            before_date=profile_cutoff,
            window=rolling_window,
            min_games=3,
        )
        away_profile = _build_rolling_profile(
            team_history.get(game.away_team_id, []),
            before_date=profile_cutoff,
            window=rolling_window,
            min_games=3,
        )

        # Build game context for SimulationEngine
        game_context: dict = {
            "home_team": home_name,
            "away_team": away_name,
            "probability_mode": probability_mode,
        }

        # If we have profiles, attach them as probability inputs
        if home_profile and away_profile:
            game_context["profiles"] = {
                "home_profile": {"metrics": home_profile},
                "away_profile": {"metrics": away_profile},
            }

        try:
            sim = engine.run_simulation(
                game_context=game_context,
                iterations=iterations,
            )
        except Exception as exc:
            logger.warning(
                "batch_sim_game_error",
                extra={"game_id": game.id, "error": str(exc)},
            )
            sim_results.append({
                "game_id": game.id,
                "game_date": game_date_str,
                "home_team": home_name,
                "away_team": away_name,
                "error": str(exc),
            })
            continue

        sim_results.append({
            "game_id": game.id,
            "game_date": game_date_str,
            "home_team": home_name,
            "away_team": away_name,
            "home_win_probability": sim.get("home_win_probability"),
            "away_win_probability": sim.get("away_win_probability"),
            "average_home_score": sim.get("average_home_score"),
            "average_away_score": sim.get("average_away_score"),
            "probability_source": sim.get("probability_source", probability_mode),
            "has_profiles": bool(home_profile and away_profile),
        })

    logger.info(
        "batch_sim_complete",
        extra={"game_count": len(sim_results), "sport": sport},
    )

    return {
        "game_count": len(sim_results),
        "results": sim_results,
    }


# ---------------------------------------------------------------------------
# Shared helpers — imported from _training_helpers to keep this file focused
# on Celery task orchestration.
# ---------------------------------------------------------------------------

from app.tasks._training_helpers import (  # noqa: E402
    build_rolling_profile as _build_rolling_profile,
    get_game_score as _get_game_score,
    get_sklearn_model as _get_sklearn_model,
    load_training_data_from_db as _load_training_data_from_db,
)
