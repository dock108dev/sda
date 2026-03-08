"""Celery tasks for analytics model training.

Dispatched from the workbench UI when a user kicks off model training.
Runs the TrainingPipeline asynchronously and updates the
AnalyticsTrainingJob row with results.
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
