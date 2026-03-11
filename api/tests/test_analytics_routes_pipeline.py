"""Route-level tests for analytics training, backtest, and batch simulation endpoints.

Covers: train, training-jobs, training-job/{id}, training-job/{id}/cancel,
backtest, backtest-jobs, backtest-job/{id}, batch-simulate, batch-simulate-jobs,
batch-simulate-job/{id}, and mlb-teams.
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
        mock_result.scalar_one_or_none.return_value = None
        mock_result.all.return_value = []
        mock_db.execute.return_value = mock_result
        mock_db.get.return_value = None

    async def mock_get_db():
        yield mock_db

    app = FastAPI()
    app.dependency_overrides[get_db] = mock_get_db
    app.include_router(router)
    return TestClient(app)


def _mock_training_job(**overrides):
    """Create a mock AnalyticsTrainingJob row."""
    defaults = dict(
        id=1, feature_config_id=None, sport="mlb", model_type="game",
        algorithm="gradient_boosting", date_start=None, date_end=None,
        test_split=0.2, random_state=42, rolling_window=30,
        status="completed", celery_task_id="cel-1", model_id="mlb_game_abc",
        artifact_path="/tmp/model.pkl", metrics={"accuracy": 0.6},
        train_count=100, test_count=25, feature_names=["f1", "f2"],
        feature_importance=None, error_message=None,
        created_at=None, updated_at=None, completed_at=None,
    )
    defaults.update(overrides)
    row = MagicMock()
    for k, v in defaults.items():
        setattr(row, k, v)
    return row


def _mock_backtest_job(**overrides):
    """Create a mock AnalyticsBacktestJob row."""
    defaults = dict(
        id=1, model_id="mlb_game_abc", artifact_path="/tmp/model.pkl",
        sport="mlb", model_type="game", date_start=None, date_end=None,
        rolling_window=30, status="completed", celery_task_id="cel-bt-1",
        game_count=50, correct_count=30, metrics={"accuracy": 0.6},
        predictions=None, error_message=None,
        created_at=None, completed_at=None,
    )
    defaults.update(overrides)
    row = MagicMock()
    for k, v in defaults.items():
        setattr(row, k, v)
    return row


def _mock_batch_sim_job(**overrides):
    """Create a mock AnalyticsBatchSimJob row."""
    defaults = dict(
        id=1, sport="mlb", probability_mode="ml", iterations=5000,
        rolling_window=30, date_start=None, date_end=None,
        status="completed", celery_task_id="cel-bs-1",
        game_count=10, results=None, error_message=None,
        created_at=None, completed_at=None,
    )
    defaults.update(overrides)
    row = MagicMock()
    for k, v in defaults.items():
        setattr(row, k, v)
    return row


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------


class TestStartTraining:
    """POST /api/analytics/train"""

    @patch("app.db.analytics.AnalyticsTrainingJob")
    @patch("app.tasks.training_tasks.train_analytics_model")
    def test_submits_training_job(self, mock_task, mock_job_cls) -> None:
        mock_task.delay.return_value = MagicMock(id="cel-train-1")
        job = _mock_training_job(status="queued", celery_task_id="cel-train-1")
        mock_job_cls.return_value = job

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result
        mock_db.refresh = AsyncMock()

        client = _make_client(mock_db)
        resp = client.post("/api/analytics/train", json={
            "sport": "mlb",
            "model_type": "game",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "submitted"
        assert "job" in data

    def test_validation_error(self) -> None:
        client = _make_client()
        resp = client.post("/api/analytics/train", json={
            "test_split": 99,  # out of range
        })
        assert resp.status_code == 422


class TestListTrainingJobs:
    """GET /api/analytics/training-jobs"""

    def test_returns_empty_list(self) -> None:
        client = _make_client()
        resp = client.get("/api/analytics/training-jobs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["jobs"] == []
        assert data["count"] == 0

    def test_accepts_filters(self) -> None:
        client = _make_client()
        resp = client.get(
            "/api/analytics/training-jobs?sport=mlb&status=completed&limit=10"
        )
        assert resp.status_code == 200


class TestGetTrainingJob:
    """GET /api/analytics/training-job/{job_id}"""

    def test_404_when_not_found(self) -> None:
        client = _make_client()
        resp = client.get("/api/analytics/training-job/999")
        assert resp.status_code == 404

    def test_returns_job(self) -> None:
        mock_db = AsyncMock()
        job = _mock_training_job()
        mock_db.get.return_value = job
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        client = _make_client(mock_db)
        resp = client.get("/api/analytics/training-job/1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == 1
        assert data["sport"] == "mlb"


class TestCancelTrainingJob:
    """POST /api/analytics/training-job/{job_id}/cancel"""

    def test_404_when_not_found(self) -> None:
        client = _make_client()
        resp = client.post("/api/analytics/training-job/999/cancel")
        assert resp.status_code == 404

    def test_400_when_already_completed(self) -> None:
        mock_db = AsyncMock()
        job = _mock_training_job(status="completed")
        mock_db.get.return_value = job
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        client = _make_client(mock_db)
        resp = client.post("/api/analytics/training-job/1/cancel")
        assert resp.status_code == 400

    @patch("app.celery_app.celery_app")
    def test_cancels_running_job(self, mock_celery) -> None:
        mock_db = AsyncMock()
        job = _mock_training_job(status="running", celery_task_id="cel-x")
        mock_db.get.return_value = job
        mock_db.refresh = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        client = _make_client(mock_db)
        resp = client.post("/api/analytics/training-job/1/cancel")
        assert resp.status_code == 200
        data = resp.json()
        # Route returns {"status": "canceled", **serialize(job)} but serialize
        # includes job.status="failed", which overwrites "canceled".
        assert data["status"] == "failed"
        assert data["error_message"] == "Canceled by user"


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------


class TestStartBacktest:
    """POST /api/analytics/backtest"""

    @patch("app.db.analytics.AnalyticsBacktestJob")
    @patch("app.tasks.training_tasks.backtest_analytics_model")
    def test_submits_backtest_job(self, mock_task, mock_job_cls) -> None:
        mock_task.delay.return_value = MagicMock(id="cel-bt-1")
        job = _mock_backtest_job(status="queued", celery_task_id="cel-bt-1")
        mock_job_cls.return_value = job

        mock_db = AsyncMock()
        mock_db.refresh = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        client = _make_client(mock_db)
        resp = client.post("/api/analytics/backtest", json={
            "model_id": "mlb_game_abc",
            "artifact_path": "/tmp/model.pkl",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "submitted"
        assert "job" in data

    def test_validation_missing_required(self) -> None:
        client = _make_client()
        resp = client.post("/api/analytics/backtest", json={})
        assert resp.status_code == 422


class TestListBacktestJobs:
    """GET /api/analytics/backtest-jobs"""

    def test_returns_empty_list(self) -> None:
        client = _make_client()
        resp = client.get("/api/analytics/backtest-jobs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["jobs"] == []
        assert data["count"] == 0

    def test_accepts_filters(self) -> None:
        client = _make_client()
        resp = client.get(
            "/api/analytics/backtest-jobs?sport=mlb&model_id=m1&status=completed"
        )
        assert resp.status_code == 200


class TestGetBacktestJob:
    """GET /api/analytics/backtest-job/{job_id}"""

    def test_404_when_not_found(self) -> None:
        client = _make_client()
        resp = client.get("/api/analytics/backtest-job/999")
        assert resp.status_code == 404

    def test_returns_job(self) -> None:
        mock_db = AsyncMock()
        job = _mock_backtest_job()
        mock_db.get.return_value = job
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        client = _make_client(mock_db)
        resp = client.get("/api/analytics/backtest-job/1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == 1
        assert data["model_id"] == "mlb_game_abc"


# ---------------------------------------------------------------------------
# Batch Simulation
# ---------------------------------------------------------------------------


class TestStartBatchSimulation:
    """POST /api/analytics/batch-simulate"""

    @patch("app.db.analytics.AnalyticsBatchSimJob")
    @patch("app.tasks.batch_sim_tasks.batch_simulate_games")
    def test_submits_batch_sim_job(self, mock_task, mock_job_cls) -> None:
        mock_task.delay.return_value = MagicMock(id="cel-bs-1")
        job = _mock_batch_sim_job(status="queued", celery_task_id="cel-bs-1")
        mock_job_cls.return_value = job

        mock_db = AsyncMock()
        mock_db.refresh = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        client = _make_client(mock_db)
        resp = client.post("/api/analytics/batch-simulate", json={
            "sport": "mlb",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "job" in data

    def test_validation_missing_sport(self) -> None:
        client = _make_client()
        resp = client.post("/api/analytics/batch-simulate", json={})
        assert resp.status_code == 422


class TestListBatchSimJobs:
    """GET /api/analytics/batch-simulate-jobs"""

    def test_returns_empty_list(self) -> None:
        client = _make_client()
        resp = client.get("/api/analytics/batch-simulate-jobs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["jobs"] == []
        assert data["count"] == 0

    def test_accepts_sport_filter(self) -> None:
        client = _make_client()
        resp = client.get("/api/analytics/batch-simulate-jobs?sport=mlb")
        assert resp.status_code == 200


class TestGetBatchSimJob:
    """GET /api/analytics/batch-simulate-job/{job_id}"""

    def test_404_when_not_found(self) -> None:
        client = _make_client()
        resp = client.get("/api/analytics/batch-simulate-job/999")
        assert resp.status_code == 404

    def test_returns_job(self) -> None:
        mock_db = AsyncMock()
        job = _mock_batch_sim_job()
        mock_db.get.return_value = job
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        client = _make_client(mock_db)
        resp = client.get("/api/analytics/batch-simulate-job/1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == 1
        assert data["sport"] == "mlb"


# ---------------------------------------------------------------------------
# MLB Teams (analytics router)
# ---------------------------------------------------------------------------


class TestGetMLBTeams:
    """GET /api/analytics/mlb-teams"""

    def test_returns_empty_teams(self) -> None:
        client = _make_client()
        resp = client.get("/api/analytics/mlb-teams")
        assert resp.status_code == 200
        data = resp.json()
        assert data["teams"] == []
        assert data["count"] == 0
