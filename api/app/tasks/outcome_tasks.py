"""Celery tasks for outcome recording and model degradation detection.

Records actual game outcomes against stored predictions, and detects
model accuracy degradation by comparing recent vs baseline Brier scores.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from app.celery_app import celery_app
from app.tasks._task_infra import _complete_job_run, _start_job_run, _task_db

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Auto-record outcomes
# ---------------------------------------------------------------------------

# Thresholds for degradation alerts
_BRIER_WARNING_THRESHOLD = 0.03  # Brier increase of 0.03 triggers warning
_BRIER_CRITICAL_THRESHOLD = 0.06  # Brier increase of 0.06 triggers critical
_MIN_WINDOW_SIZE = 10  # Minimum predictions needed per window


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
        run_id = await _start_job_run(sf, "analytics_record_outcomes")

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
                pred.outcome_recorded_at = datetime.now(UTC)
                recorded += 1

            await db.commit()

        await _complete_job_run(
            sf, run_id, "success",
            summary_data={"recorded": recorded, "skipped": skipped},
        )

    logger.info(
        "record_completed_outcomes_done",
        extra={"recorded": recorded, "skipped": skipped},
    )
    return {"recorded": recorded, "skipped": skipped, "pending": len(pending)}


# ---------------------------------------------------------------------------
# Model degradation detection
# ---------------------------------------------------------------------------


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
        run_id = await _start_job_run(
            sf, "analytics_degradation_check",
            summary_data={"sport": sport},
        )

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
                await _complete_job_run(
                    sf, run_id, "success",
                    summary_data={"sport": sport, "status": "insufficient_data", "total": len(outcomes)},
                )
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

        await _complete_job_run(
            sf, run_id, "success",
            summary_data={
                "sport": sport,
                "status": "alert_created" if alert_created else "healthy",
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
