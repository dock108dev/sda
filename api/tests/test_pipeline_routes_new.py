"""Tests for new analytics pipeline endpoints: experiments, replay, data-coverage."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.analytics.api.analytics_routes import router
from app.db import get_db


def _make_client(mock_db=None):
    if mock_db is None:
        mock_db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        result_mock.scalar_one_or_none.return_value = None
        result_mock.scalar.return_value = 0
        result_mock.all.return_value = []
        mock_db.execute.return_value = result_mock
        mock_db.get.return_value = None

    async def mock_get_db():
        yield mock_db

    app = FastAPI()
    app.dependency_overrides[get_db] = mock_get_db
    app.include_router(router)
    return TestClient(app), mock_db


def _mock_suite(**overrides):
    defaults = dict(
        id=1, name="Test Suite", description="desc", sport="mlb",
        model_type="plate_appearance", parameter_grid={"algorithms": ["gradient_boosting"]},
        tags=None, status="completed", celery_task_id="cel-1",
        total_variants=2, completed_variants=2, failed_variants=0,
        leaderboard=[], promoted_model_id=None, promoted_at=None,
        error_message=None,
        created_at=datetime(2026, 3, 1, tzinfo=UTC),
        completed_at=datetime(2026, 3, 1, tzinfo=UTC),
    )
    defaults.update(overrides)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def _mock_variant(**overrides):
    defaults = dict(
        id=1, suite_id=1, variant_index=0, algorithm="gradient_boosting",
        rolling_window=30, feature_config_id=None,
        training_date_start=None, training_date_end=None,
        test_split=0.2, extra_params=None,
        training_job_id=10, replay_job_id=None, model_id="model_abc",
        status="completed", training_metrics={"accuracy": 0.65},
        replay_metrics=None, rank=1, error_message=None,
        created_at=datetime(2026, 3, 1, tzinfo=UTC),
        completed_at=datetime(2026, 3, 1, tzinfo=UTC),
    )
    defaults.update(overrides)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def _mock_replay_job(**overrides):
    defaults = dict(
        id=1, sport="mlb", model_id="model_abc", model_type="plate_appearance",
        date_start="2025-07-01", date_end="2025-10-01",
        game_count_requested=50, rolling_window=30,
        probability_mode="ml", iterations=5000, suite_id=None,
        status="completed", celery_task_id="cel-rp-1",
        game_count=50, results=[], metrics={"winner_accuracy": 0.58},
        error_message=None,
        created_at=datetime(2026, 3, 1, tzinfo=UTC),
        completed_at=datetime(2026, 3, 1, tzinfo=UTC),
    )
    defaults.update(overrides)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


# ---------------------------------------------------------------------------
# Experiment Suite endpoints
# ---------------------------------------------------------------------------


class TestCreateExperimentSuite:
    @patch("app.tasks.experiment_tasks.run_experiment_suite")
    def test_creates_suite(self, mock_task):
        mock_task.delay.return_value = MagicMock(id="cel-suite-1")
        client, mock_db = _make_client()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock(side_effect=lambda obj: setattr(obj, "id", 1))

        resp = client.post("/api/analytics/experiments", json={
            "name": "Test Sweep",
            "sport": "mlb",
            "model_type": "plate_appearance",
            "parameter_grid": {"algorithms": ["gradient_boosting", "random_forest"]},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "submitted"
        assert "suite" in data

    @patch("app.tasks.experiment_tasks.run_experiment_suite")
    def test_handles_dispatch_failure(self, mock_task):
        mock_task.delay.side_effect = Exception("Celery down")
        client, mock_db = _make_client()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock(side_effect=lambda obj: setattr(obj, "id", 1))

        resp = client.post("/api/analytics/experiments", json={
            "name": "Fail Suite",
            "sport": "mlb",
            "model_type": "plate_appearance",
            "parameter_grid": {},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "submitted"


class TestListExperimentSuites:
    def test_lists_empty(self):
        client, _ = _make_client()
        resp = client.get("/api/analytics/experiments")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_lists_with_results(self):
        mock_db = AsyncMock()
        suite = _mock_suite()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [suite]
        result_mock.scalar.return_value = 0
        mock_db.execute.return_value = result_mock
        mock_db.get.return_value = None

        client, _ = _make_client(mock_db)
        resp = client.get("/api/analytics/experiments")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["suites"][0]["name"] == "Test Suite"

    def test_filters_by_sport(self):
        client, _ = _make_client()
        resp = client.get("/api/analytics/experiments?sport=mlb")
        assert resp.status_code == 200

    def test_filters_by_status(self):
        client, _ = _make_client()
        resp = client.get("/api/analytics/experiments?status=completed")
        assert resp.status_code == 200


class TestGetExperimentSuite:
    def test_returns_404_for_missing(self):
        client, _ = _make_client()
        resp = client.get("/api/analytics/experiments/999")
        assert resp.status_code == 404

    def test_returns_suite_with_variants(self):
        mock_db = AsyncMock()
        suite = _mock_suite()
        variant = _mock_variant()

        call_count = 0

        async def mock_get(cls, id_):
            return suite

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            result.scalars.return_value.all.return_value = [variant]
            result.scalar.return_value = 0
            return result

        mock_db.get = mock_get
        mock_db.execute = mock_execute

        client, _ = _make_client(mock_db)
        resp = client.get("/api/analytics/experiments/1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Test Suite"
        assert len(data["variants"]) == 1
        assert data["variants"][0]["algorithm"] == "gradient_boosting"


class TestPromoteExperimentVariant:
    def test_returns_404_missing_suite(self):
        client, _ = _make_client()
        resp = client.post("/api/analytics/experiments/999/promote/1")
        assert resp.status_code == 404

    def test_returns_404_missing_variant(self):
        mock_db = AsyncMock()
        suite = _mock_suite()

        async def mock_get(cls, id_):
            if id_ == 1:
                return suite
            return None

        mock_db.get = mock_get
        client, _ = _make_client(mock_db)
        resp = client.post("/api/analytics/experiments/1/promote/999")
        assert resp.status_code == 404

    def test_returns_400_no_model(self):
        mock_db = AsyncMock()
        suite = _mock_suite()
        variant = _mock_variant(model_id=None)

        async def mock_get(cls, id_):
            if id_ == 1:
                return suite
            if id_ == 2:
                return variant
            return None

        mock_db.get = mock_get
        client, _ = _make_client(mock_db)
        resp = client.post("/api/analytics/experiments/1/promote/2")
        assert resp.status_code == 400

    @patch("app.analytics.models.core.model_registry.ModelRegistry")
    def test_promotes_successfully(self, mock_registry_cls):
        mock_registry = MagicMock()
        mock_registry_cls.return_value = mock_registry

        mock_db = AsyncMock()
        suite = _mock_suite()
        variant = _mock_variant(id=2, suite_id=1, model_id="model_xyz")

        async def mock_get(cls, id_):
            if id_ == 1:
                return suite
            if id_ == 2:
                return variant
            return None

        mock_db.get = mock_get
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        client, _ = _make_client(mock_db)
        resp = client.post("/api/analytics/experiments/1/promote/2")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "promoted"
        assert data["model_id"] == "model_xyz"
        mock_registry.activate_model.assert_called_once()


# ---------------------------------------------------------------------------
# Replay endpoints
# ---------------------------------------------------------------------------


class TestStartReplay:
    @patch("app.tasks.replay_tasks.replay_historical_games")
    def test_creates_replay_job(self, mock_task):
        mock_task.delay.return_value = MagicMock(id="cel-rp-1")
        client, mock_db = _make_client()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock(side_effect=lambda obj: setattr(obj, "id", 1))

        resp = client.post("/api/analytics/replay", json={
            "model_id": "model_abc",
            "date_start": "2025-07-01",
            "date_end": "2025-10-01",
            "game_count": 50,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "submitted"
        assert "job" in data

    @patch("app.tasks.replay_tasks.replay_historical_games")
    def test_handles_dispatch_failure(self, mock_task):
        mock_task.delay.side_effect = Exception("Celery down")
        client, mock_db = _make_client()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock(side_effect=lambda obj: setattr(obj, "id", 1))

        resp = client.post("/api/analytics/replay", json={
            "model_id": "model_abc",
        })
        assert resp.status_code == 200


class TestListReplayJobs:
    def test_lists_empty(self):
        client, _ = _make_client()
        resp = client.get("/api/analytics/replay-jobs")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_lists_with_results(self):
        mock_db = AsyncMock()
        job = _mock_replay_job()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [job]
        result_mock.scalar.return_value = 0
        mock_db.execute.return_value = result_mock
        mock_db.get.return_value = None

        client, _ = _make_client(mock_db)
        resp = client.get("/api/analytics/replay-jobs")
        assert resp.status_code == 200
        assert resp.json()["count"] == 1

    def test_filters_by_sport(self):
        client, _ = _make_client()
        resp = client.get("/api/analytics/replay-jobs?sport=mlb")
        assert resp.status_code == 200

    def test_filters_by_suite_id(self):
        client, _ = _make_client()
        resp = client.get("/api/analytics/replay-jobs?suite_id=1")
        assert resp.status_code == 200


class TestGetReplayJob:
    def test_returns_404_for_missing(self):
        client, _ = _make_client()
        resp = client.get("/api/analytics/replay-job/999")
        assert resp.status_code == 404

    def test_returns_job(self):
        mock_db = AsyncMock()
        job = _mock_replay_job()
        mock_db.get = AsyncMock(return_value=job)
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        result_mock.scalar.return_value = 0
        mock_db.execute.return_value = result_mock

        client, _ = _make_client(mock_db)
        resp = client.get("/api/analytics/replay-job/1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["model_id"] == "model_abc"
        assert data["status"] == "completed"


# ---------------------------------------------------------------------------
# Data coverage endpoint
# ---------------------------------------------------------------------------


class TestMLBDataCoverage:
    def test_returns_coverage_all_zero(self):
        mock_db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar.return_value = 0
        mock_db.execute.return_value = result_mock
        mock_db.get.return_value = None

        client, _ = _make_client(mock_db)
        resp = client.get("/api/analytics/mlb-data-coverage")
        assert resp.status_code == 200
        data = resp.json()
        assert data["advanced_data_coverage"]["pa"] == "missing"
        assert data["advanced_data_coverage"]["pitch"] == "missing"
        assert data["advanced_data_coverage"]["fielding"] == "missing"
        assert data["counts"]["player_advanced_stats"] == 0

    def test_returns_partial_coverage(self):
        mock_db = AsyncMock()
        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            # Return different counts for each query
            counts = [50, 50, 50, 10]  # pa, pitcher, team_stats, fielding
            result.scalar.return_value = counts[call_count - 1] if call_count <= 4 else 0
            result.scalars.return_value.all.return_value = []
            return result

        mock_db.execute = mock_execute
        mock_db.get.return_value = None

        client, _ = _make_client(mock_db)
        resp = client.get("/api/analytics/mlb-data-coverage")
        assert resp.status_code == 200
        data = resp.json()
        assert data["advanced_data_coverage"]["pa"] == "partial"
        assert data["advanced_data_coverage"]["pitch"] == "ready"  # 50+50=100
        assert data["advanced_data_coverage"]["fielding"] == "partial"

    def test_returns_ready_coverage(self):
        mock_db = AsyncMock()
        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            counts = [200, 150, 150, 50]
            result.scalar.return_value = counts[call_count - 1] if call_count <= 4 else 0
            result.scalars.return_value.all.return_value = []
            return result

        mock_db.execute = mock_execute
        mock_db.get.return_value = None

        client, _ = _make_client(mock_db)
        resp = client.get("/api/analytics/mlb-data-coverage")
        assert resp.status_code == 200
        data = resp.json()
        assert data["advanced_data_coverage"]["pa"] == "ready"
        assert data["advanced_data_coverage"]["pitch"] == "ready"
        assert data["advanced_data_coverage"]["fielding"] == "ready"
