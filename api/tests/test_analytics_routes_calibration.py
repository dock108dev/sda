"""Route-level tests for analytics calibration endpoints.

Covers: record-outcomes, prediction-outcomes, calibration-report,
degradation-check, degradation-alerts, acknowledge degradation alert.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.analytics.api.analytics_routes import router
from app.db import get_db


def _make_client(mock_db=None):
    """Create a TestClient with mocked DB dependency."""
    if mock_db is None:
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_result.all.return_value = []
        mock_db.execute.return_value = mock_result
        mock_db.get.return_value = None

    async def mock_get_db():
        yield mock_db

    app = FastAPI()
    app.dependency_overrides[get_db] = mock_get_db
    app.include_router(router)
    return TestClient(app)


class TestRecordOutcomes:
    """POST /api/analytics/record-outcomes"""

    @patch("app.tasks.outcome_tasks.record_completed_outcomes")
    def test_dispatches_celery_task(self, mock_task) -> None:
        mock_task.delay.return_value = MagicMock(id="task-123")
        client = _make_client()
        resp = client.post("/api/analytics/record-outcomes")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "dispatched"
        assert data["task_id"] == "task-123"
        mock_task.delay.assert_called_once()


class TestPredictionOutcomes:
    """GET /api/analytics/prediction-outcomes"""

    def test_returns_empty_list(self) -> None:
        client = _make_client()
        resp = client.get("/api/analytics/prediction-outcomes")
        assert resp.status_code == 200
        data = resp.json()
        assert data["outcomes"] == []
        assert data["count"] == 0

    def test_accepts_filters(self) -> None:
        client = _make_client()
        resp = client.get(
            "/api/analytics/prediction-outcomes?sport=mlb&status=pending&limit=10"
        )
        assert resp.status_code == 200

    def test_with_results(self) -> None:
        mock_db = AsyncMock()
        mock_outcome = MagicMock()
        mock_outcome.id = 1
        mock_outcome.game_id = 100
        mock_outcome.sport = "mlb"
        mock_outcome.batch_sim_job_id = None
        mock_outcome.home_team = "NYY"
        mock_outcome.away_team = "BOS"
        mock_outcome.predicted_home_wp = 0.6
        mock_outcome.predicted_away_wp = 0.4
        mock_outcome.predicted_home_score = 5.0
        mock_outcome.predicted_away_score = 3.0
        mock_outcome.probability_mode = "ml"
        mock_outcome.game_date = "2026-03-01"
        mock_outcome.actual_home_score = None
        mock_outcome.actual_away_score = None
        mock_outcome.home_win_actual = None
        mock_outcome.correct_winner = None
        mock_outcome.brier_score = None
        mock_outcome.outcome_recorded_at = None
        mock_outcome.created_at = None
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_outcome]
        mock_db.execute.return_value = mock_result

        client = _make_client(mock_db)
        resp = client.get("/api/analytics/prediction-outcomes")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["outcomes"][0]["home_team"] == "NYY"


class TestCalibrationReport:
    """GET /api/analytics/calibration-report"""

    def test_empty_returns_zeros(self) -> None:
        client = _make_client()
        resp = client.get("/api/analytics/calibration-report")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_predictions"] == 0
        assert data["accuracy"] == 0.0
        assert data["brier_score"] == 0.0

    def test_accepts_sport_filter(self) -> None:
        client = _make_client()
        resp = client.get("/api/analytics/calibration-report?sport=mlb")
        assert resp.status_code == 200


class TestDegradationCheck:
    """POST /api/analytics/degradation-check"""

    @patch("app.tasks.outcome_tasks.check_model_degradation")
    def test_dispatches_celery_task(self, mock_task) -> None:
        mock_task.delay.return_value = MagicMock(id="deg-task-1")
        client = _make_client()
        resp = client.post("/api/analytics/degradation-check?sport=mlb")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "dispatched"
        assert data["task_id"] == "deg-task-1"

    @patch("app.tasks.outcome_tasks.check_model_degradation")
    def test_default_sport_mlb(self, mock_task) -> None:
        mock_task.delay.return_value = MagicMock(id="t1")
        client = _make_client()
        resp = client.post("/api/analytics/degradation-check")
        assert resp.status_code == 200
        mock_task.delay.assert_called_once_with(sport="mlb")


class TestDegradationAlerts:
    """GET /api/analytics/degradation-alerts"""

    def test_returns_empty_list(self) -> None:
        client = _make_client()
        resp = client.get("/api/analytics/degradation-alerts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["alerts"] == []
        assert data["count"] == 0

    def test_accepts_filters(self) -> None:
        client = _make_client()
        resp = client.get(
            "/api/analytics/degradation-alerts?sport=mlb&acknowledged=false&limit=5"
        )
        assert resp.status_code == 200


class TestAcknowledgeDegradationAlert:
    """POST /api/analytics/degradation-alerts/{alert_id}/acknowledge"""

    def test_404_when_not_found(self) -> None:
        client = _make_client()
        resp = client.post("/api/analytics/degradation-alerts/999/acknowledge")
        assert resp.status_code == 404

    def test_acknowledges_alert(self) -> None:
        mock_db = AsyncMock()
        mock_alert = MagicMock()
        mock_alert.id = 1
        mock_alert.sport = "mlb"
        mock_alert.alert_type = "accuracy_drop"
        mock_alert.baseline_brier = 0.2
        mock_alert.recent_brier = 0.3
        mock_alert.baseline_accuracy = 0.6
        mock_alert.recent_accuracy = 0.45
        mock_alert.baseline_count = 50
        mock_alert.recent_count = 20
        mock_alert.delta_brier = 0.1
        mock_alert.delta_accuracy = -0.15
        mock_alert.severity = "warning"
        mock_alert.message = "Accuracy dropped"
        mock_alert.acknowledged = False
        mock_alert.created_at = None
        mock_db.get.return_value = mock_alert
        # Also need execute for empty list queries
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        client = _make_client(mock_db)
        resp = client.post("/api/analytics/degradation-alerts/1/acknowledge")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == 1
        assert mock_alert.acknowledged is True
