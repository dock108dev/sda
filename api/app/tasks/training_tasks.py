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

from app.celery_app import celery_app

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
    from sqlalchemy import select

    from app.db import get_async_session
    from app.db.analytics import AnalyticsFeatureConfig, AnalyticsTrainingJob

    async with get_async_session() as db:
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
        async with get_async_session() as db:
            job = await db.get(AnalyticsTrainingJob, job_id)
            if job:
                job.status = "failed"
                job.error_message = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
                job.completed_at = datetime.now(timezone.utc)
                await db.commit()
        return {"error": str(exc), "job_id": job_id}

    # Write results back
    async with get_async_session() as db:
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

    # Load training data from DB
    records = await _load_training_data_from_db(
        sport=sport,
        model_type=model_type,
        date_start=date_start,
        date_end=date_end,
        rolling_window=rolling_window,
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
    from app.db import get_async_session
    from app.db.analytics import AnalyticsBacktestJob

    async with get_async_session() as db:
        job = await db.get(AnalyticsBacktestJob, job_id)
        if job is None:
            return {"error": "job_not_found", "job_id": job_id}

        job.status = "running"
        if celery_task_id:
            job.celery_task_id = celery_task_id
        await db.commit()

    try:
        result = await _execute_backtest(
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
        async with get_async_session() as db:
            job = await db.get(AnalyticsBacktestJob, job_id)
            if job:
                job.status = "failed"
                job.error_message = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
                job.completed_at = datetime.now(timezone.utc)
                await db.commit()
        return {"error": str(exc), "job_id": job_id}

    async with get_async_session() as db:
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
    records = await _load_training_data_from_db(
        sport=sport,
        model_type=model_type,
        date_start=date_start,
        date_end=date_end,
        rolling_window=rolling_window,
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
    from app.db import get_async_session
    from app.db.analytics import AnalyticsBatchSimJob

    async with get_async_session() as db:
        job = await db.get(AnalyticsBatchSimJob, job_id)
        if job is None:
            return {"error": "job_not_found", "job_id": job_id}

        job.status = "running"
        if celery_task_id:
            job.celery_task_id = celery_task_id
        await db.commit()

    try:
        result = await _execute_batch_sim(
            sport=job.sport,
            probability_mode=job.probability_mode,
            iterations=job.iterations,
            rolling_window=getattr(job, "rolling_window", 30),
            date_start=job.date_start,
            date_end=job.date_end,
        )
    except Exception as exc:
        logger.exception("batch_sim_failed", extra={"job_id": job_id})
        async with get_async_session() as db:
            job = await db.get(AnalyticsBatchSimJob, job_id)
            if job:
                job.status = "failed"
                job.error_message = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
                job.completed_at = datetime.now(timezone.utc)
                await db.commit()
        return {"error": str(exc), "job_id": job_id}

    async with get_async_session() as db:
        job = await db.get(AnalyticsBatchSimJob, job_id)
        if job:
            if "error" in result:
                job.status = "failed"
                job.error_message = result.get("error", "unknown")
            else:
                job.status = "completed"
                job.game_count = result.get("game_count")
                job.results = result.get("results")
            job.completed_at = datetime.now(timezone.utc)
            await db.commit()

    return result


async def _execute_batch_sim(
    *,
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
    from app.db import get_async_session
    from app.db.mlb_advanced import MLBGameAdvancedStats
    from app.db.sports import SportsGame, SportsTeam

    if sport.lower() != "mlb":
        return {"error": "only_mlb_supported"}

    async with get_async_session() as db:
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


async def _load_training_data_from_db(
    *,
    sport: str,
    model_type: str,
    date_start: str | None,
    date_end: str | None,
    rolling_window: int = 30,
) -> list[dict]:
    """Load historical training data from the database.

    For MLB game models: queries MLBGameAdvancedStats + SportsGame
    to build rolling team profiles (aggregated from prior N games)
    with win/loss labels.
    """
    if sport.lower() != "mlb":
        return []

    if model_type == "game":
        return await _load_mlb_game_training_data(
            date_start, date_end, rolling_window=rolling_window
        )

    # PA model and others: placeholder for future implementation
    return []


async def _load_mlb_game_training_data(
    date_start: str | None,
    date_end: str | None,
    *,
    rolling_window: int = 30,
) -> list[dict]:
    """Load MLB game training data using rolling team profiles.

    For each game, builds home/away profiles by aggregating each team's
    prior N games of advanced stats. This prevents data leakage — a team's
    features for game X only use data from games before X.

    Games where a team has fewer than 5 prior games are skipped to
    ensure profiles are meaningful.
    """
    from collections import defaultdict

    from sqlalchemy import select

    from app.db import get_async_session
    from app.db.mlb_advanced import MLBGameAdvancedStats
    from app.db.sports import SportsGame

    min_games = 5  # Minimum prior games required for a valid profile

    async with get_async_session() as db:
        # 1. Load training games (the games we want to predict)
        train_stmt = (
            select(SportsGame)
            .where(SportsGame.status == "final")
            .order_by(SportsGame.game_date.asc())
        )
        if date_start:
            train_stmt = train_stmt.where(SportsGame.game_date >= date_start)
        if date_end:
            train_stmt = train_stmt.where(SportsGame.game_date <= date_end)

        result = await db.execute(train_stmt)
        training_games = result.scalars().all()

        if not training_games:
            return []

        # 2. Load ALL advanced stats (including lookback period before date_start)
        #    so we can build rolling profiles for early games in the training set.
        all_stats_stmt = (
            select(MLBGameAdvancedStats)
            .join(SportsGame, SportsGame.id == MLBGameAdvancedStats.game_id)
            .where(SportsGame.status == "final")
            .order_by(SportsGame.game_date.asc())
        )
        # Only apply end date filter — we need all history before date_start
        if date_end:
            all_stats_stmt = all_stats_stmt.where(SportsGame.game_date <= date_end)

        stats_result = await db.execute(all_stats_stmt)
        all_stats = stats_result.scalars().all()

        # 3. Index stats by game_id for quick lookup
        stats_by_game: dict[int, list] = defaultdict(list)
        for s in all_stats:
            stats_by_game[s.game_id].append(s)

        # 4. Build per-team chronological history: team_id -> [(game_date, stats_row)]
        #    We need game dates to enforce the "prior games only" constraint.
        game_dates: dict[int, str] = {}
        for g in training_games:
            game_dates[g.id] = str(g.game_date)

        # Load game dates for ALL games that have stats (including lookback)
        all_game_ids = list(stats_by_game.keys())
        if all_game_ids:
            dates_stmt = select(SportsGame.id, SportsGame.game_date).where(
                SportsGame.id.in_(all_game_ids)
            )
            dates_result = await db.execute(dates_stmt)
            for gid, gdate in dates_result:
                game_dates[gid] = str(gdate)

        # Build team histories sorted by date
        team_history: dict[int, list[tuple[str, object]]] = defaultdict(list)
        for game_id, stats_list in stats_by_game.items():
            gdate = game_dates.get(game_id, "")
            for s in stats_list:
                team_history[s.team_id].append((gdate, s))

        # Sort each team's history by date
        for tid in team_history:
            team_history[tid].sort(key=lambda x: x[0])

        # 5. For each training game, build rolling profiles from prior games
        training_game_ids = {g.id for g in training_games}
        records = []
        skipped_insufficient = 0

        for game in training_games:
            game_stats = stats_by_game.get(game.id, [])
            if len(game_stats) != 2:
                continue

            home_stats = None
            away_stats = None
            for s in game_stats:
                if s.is_home:
                    home_stats = s
                else:
                    away_stats = s

            if not home_stats or not away_stats:
                continue

            home_score = _get_game_score(game, is_home=True)
            away_score = _get_game_score(game, is_home=False)
            if home_score is None or away_score is None:
                continue

            game_date_str = str(game.game_date)

            # Build rolling profile for home team
            home_profile = _build_rolling_profile(
                team_history[home_stats.team_id],
                before_date=game_date_str,
                window=rolling_window,
            )
            # Build rolling profile for away team
            away_profile = _build_rolling_profile(
                team_history[away_stats.team_id],
                before_date=game_date_str,
                window=rolling_window,
            )

            # Skip if either team lacks sufficient history
            if home_profile is None or away_profile is None:
                skipped_insufficient += 1
                continue

            records.append({
                "home_profile": {"metrics": home_profile},
                "away_profile": {"metrics": away_profile},
                "home_win": 1 if home_score > away_score else 0,
                "home_score": home_score,
                "away_score": away_score,
            })

        logger.info(
            "mlb_training_data_loaded",
            extra={
                "records": len(records),
                "games_queried": len(training_games),
                "skipped_insufficient_history": skipped_insufficient,
                "rolling_window": rolling_window,
            },
        )
        return records


def _build_rolling_profile(
    team_games: list[tuple[str, object]],
    *,
    before_date: str,
    window: int,
    min_games: int = 5,
) -> dict | None:
    """Aggregate a team's prior games into a rolling profile.

    Args:
        team_games: Chronologically sorted list of (date_str, MLBGameAdvancedStats).
        before_date: Only include games strictly before this date.
        window: Maximum number of prior games to include.
        min_games: Minimum prior games required; returns None if insufficient.

    Returns:
        Aggregated metrics dict, or None if insufficient history.
    """
    # Collect prior games (strictly before the target date)
    prior = [stats for date_str, stats in team_games if date_str < before_date]

    if len(prior) < min_games:
        return None

    # Take the most recent N games
    recent = prior[-window:]

    # Convert each game's stats to metrics, then average
    all_metrics: list[dict] = [_stats_to_metrics(s) for s in recent]

    # Average each metric key across the window
    aggregated: dict[str, float] = {}
    for key in all_metrics[0]:
        values = [m[key] for m in all_metrics if key in m]
        if values:
            aggregated[key] = round(sum(values) / len(values), 4)

    return aggregated


def _stats_to_metrics(stats) -> dict:
    """Convert MLBGameAdvancedStats row to metrics dict for feature builder."""
    return {
        "contact_rate": _safe_rate(stats.z_contact_pct, stats.o_contact_pct),
        "power_index": _power_index(stats.avg_exit_velo, stats.barrel_pct),
        "barrel_rate": stats.barrel_pct or 0.0,
        "hard_hit_rate": stats.hard_hit_pct or 0.0,
        "swing_rate": _safe_rate(stats.z_swing_pct, stats.o_swing_pct),
        "whiff_rate": _whiff_rate(stats),
        "avg_exit_velocity": stats.avg_exit_velo or 88.0,
        "expected_slug": _expected_slug(stats),
    }


def _safe_rate(zone_pct: float | None, outside_pct: float | None) -> float:
    """Combine zone and outside rates into an overall rate."""
    z = zone_pct or 0.0
    o = outside_pct or 0.0
    return round((z + o) / 2, 4) if (z or o) else 0.0


def _power_index(avg_ev: float | None, barrel_pct: float | None) -> float:
    """Composite power metric from exit velocity and barrel rate."""
    ev = avg_ev or 88.0
    bp = barrel_pct or 0.07
    return round((ev / 88.0) * (1 + bp * 5), 4)


def _whiff_rate(stats) -> float:
    """Calculate whiff rate from available swing/contact data."""
    total_swings = (stats.zone_swings or 0) + (stats.outside_swings or 0)
    total_contact = (stats.zone_contact or 0) + (stats.outside_contact or 0)
    if total_swings == 0:
        return 0.23  # league average
    return round(1.0 - (total_contact / total_swings), 4)


def _expected_slug(stats) -> float:
    """Estimate expected slugging from quality of contact metrics."""
    ev = stats.avg_exit_velo or 88.0
    hh = stats.hard_hit_pct or 0.35
    bp = stats.barrel_pct or 0.07
    return round(0.3 + (ev - 80) * 0.01 + hh * 0.5 + bp * 2.0, 4)


def _get_game_score(game, *, is_home: bool) -> int | None:
    """Extract score from a SportsGame for home or away team."""
    # SportsGame stores boxscores as relationships; try common patterns
    if hasattr(game, "home_score") and hasattr(game, "away_score"):
        return game.home_score if is_home else game.away_score

    # Try raw_data JSONB if available
    raw = getattr(game, "raw_data", None) or {}
    if is_home:
        return raw.get("home_score") or raw.get("homeScore")
    return raw.get("away_score") or raw.get("awayScore")


def _get_sklearn_model(algorithm: str, model_type: str, random_state: int):
    """Create sklearn model instance based on algorithm choice."""
    if algorithm == "random_forest":
        from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
        if model_type in ("plate_appearance", "game"):
            return RandomForestClassifier(
                n_estimators=200, max_depth=6, random_state=random_state
            )
        return RandomForestRegressor(
            n_estimators=200, max_depth=6, random_state=random_state
        )

    if algorithm == "xgboost":
        try:
            from xgboost import XGBClassifier, XGBRegressor
            if model_type in ("plate_appearance", "game"):
                return XGBClassifier(
                    n_estimators=200, max_depth=5, random_state=random_state,
                    use_label_encoder=False, eval_metric="logloss",
                )
            return XGBRegressor(
                n_estimators=200, max_depth=5, random_state=random_state,
            )
        except ImportError:
            pass  # Fall through to gradient_boosting

    # Default: gradient_boosting
    from sklearn.ensemble import GradientBoostingClassifier, GradientBoostingRegressor
    if model_type in ("plate_appearance", "game"):
        return GradientBoostingClassifier(
            n_estimators=100, max_depth=5, random_state=random_state,
        )
    return GradientBoostingRegressor(
        n_estimators=100, max_depth=4, random_state=random_state,
    )
