"""Prediction outcome, calibration, and degradation alert endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.analytics import AnalyticsPredictionOutcome

router = APIRouter()


@router.post("/record-outcomes")
async def post_record_outcomes(
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Trigger auto-recording of outcomes for finalized games.

    Dispatches the Celery task that scans pending predictions and
    matches them against completed SportsGame records.
    """
    from app.tasks.training_tasks import record_completed_outcomes

    task = record_completed_outcomes.delay()
    return {"status": "dispatched", "task_id": task.id}


@router.get("/prediction-outcomes")
async def list_prediction_outcomes(
    sport: str | None = Query(None, description="Filter by sport"),
    status: str | None = Query(None, description="Filter: 'pending' or 'resolved'"),
    limit: int = Query(100, ge=1, le=500, description="Max results"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List prediction outcome records."""
    stmt = (
        select(AnalyticsPredictionOutcome)
        .order_by(AnalyticsPredictionOutcome.id.desc())
        .limit(limit)
    )
    if sport:
        stmt = stmt.where(AnalyticsPredictionOutcome.sport == sport)
    if status == "pending":
        stmt = stmt.where(AnalyticsPredictionOutcome.outcome_recorded_at.is_(None))
    elif status == "resolved":
        stmt = stmt.where(AnalyticsPredictionOutcome.outcome_recorded_at.isnot(None))

    result = await db.execute(stmt)
    outcomes = list(result.scalars().all())
    return {
        "outcomes": [_serialize_prediction_outcome(o) for o in outcomes],
        "count": len(outcomes),
    }


@router.get("/calibration-report")
async def get_calibration_report(
    sport: str | None = Query(None, description="Filter by sport"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Aggregate calibration metrics from resolved prediction outcomes."""
    stmt = select(AnalyticsPredictionOutcome).where(
        AnalyticsPredictionOutcome.outcome_recorded_at.isnot(None)
    )
    if sport:
        stmt = stmt.where(AnalyticsPredictionOutcome.sport == sport)

    result = await db.execute(stmt)
    outcomes = list(result.scalars().all())

    if not outcomes:
        return {
            "total_predictions": 0,
            "resolved": 0,
            "accuracy": 0.0,
            "brier_score": 0.0,
            "avg_home_score_error": 0.0,
            "avg_away_score_error": 0.0,
            "home_bias": 0.0,
        }

    n = len(outcomes)
    correct = sum(1 for o in outcomes if o.correct_winner)
    avg_brier = sum(o.brier_score for o in outcomes if o.brier_score is not None) / n

    home_errors = [
        abs((o.predicted_home_score or 0) - (o.actual_home_score or 0))
        for o in outcomes if o.actual_home_score is not None
    ]
    away_errors = [
        abs((o.predicted_away_score or 0) - (o.actual_away_score or 0))
        for o in outcomes if o.actual_away_score is not None
    ]
    home_wp_diffs = [
        o.predicted_home_wp - (1.0 if o.home_win_actual else 0.0)
        for o in outcomes
    ]

    return {
        "total_predictions": n,
        "resolved": n,
        "accuracy": round(correct / n, 4) if n else 0.0,
        "brier_score": round(avg_brier, 4),
        "avg_home_score_error": round(sum(home_errors) / len(home_errors), 2) if home_errors else 0.0,
        "avg_away_score_error": round(sum(away_errors) / len(away_errors), 2) if away_errors else 0.0,
        "home_bias": round(sum(home_wp_diffs) / n, 4) if n else 0.0,
    }


def _serialize_prediction_outcome(o: Any) -> dict[str, Any]:
    return {
        "id": o.id,
        "game_id": o.game_id,
        "sport": o.sport,
        "batch_sim_job_id": o.batch_sim_job_id,
        "home_team": o.home_team,
        "away_team": o.away_team,
        "predicted_home_wp": o.predicted_home_wp,
        "predicted_away_wp": o.predicted_away_wp,
        "predicted_home_score": o.predicted_home_score,
        "predicted_away_score": o.predicted_away_score,
        "probability_mode": o.probability_mode,
        "game_date": o.game_date,
        "actual_home_score": o.actual_home_score,
        "actual_away_score": o.actual_away_score,
        "home_win_actual": o.home_win_actual,
        "correct_winner": o.correct_winner,
        "brier_score": o.brier_score,
        "outcome_recorded_at": o.outcome_recorded_at.isoformat() if o.outcome_recorded_at else None,
        "created_at": o.created_at.isoformat() if o.created_at else None,
    }


# ---------------------------------------------------------------------------
# Degradation Alerts
# ---------------------------------------------------------------------------


@router.post("/degradation-check")
async def post_degradation_check(
    sport: str = Query("mlb", description="Sport to check"),
) -> dict[str, Any]:
    """Trigger a degradation check for the given sport."""
    from app.tasks.training_tasks import check_model_degradation

    task = check_model_degradation.delay(sport=sport)
    return {"status": "dispatched", "task_id": task.id}


@router.get("/degradation-alerts")
async def list_degradation_alerts(
    sport: str | None = Query(None, description="Filter by sport"),
    acknowledged: bool | None = Query(None, description="Filter by acknowledged status"),
    limit: int = Query(20, ge=1, le=100, description="Max results"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List degradation alerts, newest first."""
    from app.db.analytics import AnalyticsDegradationAlert

    stmt = (
        select(AnalyticsDegradationAlert)
        .order_by(AnalyticsDegradationAlert.id.desc())
        .limit(limit)
    )
    if sport:
        stmt = stmt.where(AnalyticsDegradationAlert.sport == sport)
    if acknowledged is True:
        stmt = stmt.where(AnalyticsDegradationAlert.acknowledged.is_(True))
    elif acknowledged is False:
        stmt = stmt.where(AnalyticsDegradationAlert.acknowledged.is_(False))

    result = await db.execute(stmt)
    alerts = list(result.scalars().all())
    return {
        "alerts": [_serialize_degradation_alert(a) for a in alerts],
        "count": len(alerts),
    }


@router.post("/degradation-alerts/{alert_id}/acknowledge")
async def acknowledge_degradation_alert(
    alert_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Acknowledge a degradation alert."""
    from app.db.analytics import AnalyticsDegradationAlert

    alert = await db.get(AnalyticsDegradationAlert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.acknowledged = True
    await db.commit()
    return _serialize_degradation_alert(alert)


def _serialize_degradation_alert(a: Any) -> dict[str, Any]:
    return {
        "id": a.id,
        "sport": a.sport,
        "alert_type": a.alert_type,
        "baseline_brier": a.baseline_brier,
        "recent_brier": a.recent_brier,
        "baseline_accuracy": a.baseline_accuracy,
        "recent_accuracy": a.recent_accuracy,
        "baseline_count": a.baseline_count,
        "recent_count": a.recent_count,
        "delta_brier": a.delta_brier,
        "delta_accuracy": a.delta_accuracy,
        "severity": a.severity,
        "message": a.message,
        "acknowledged": a.acknowledged,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }
