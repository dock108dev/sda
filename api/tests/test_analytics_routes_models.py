"""Route-level tests for analytics model registry, inference, and ensemble endpoints.

Covers: model-predict (GET/POST), models, models/details, models/compare,
models/activate, models/active, model-metrics, ensemble-config (GET/POST),
ensemble-configs.
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


# ---------------------------------------------------------------------------
# Model Inference
# ---------------------------------------------------------------------------


class TestPostModelPredict:
    """POST /api/analytics/model-predict"""

    @patch("app.analytics.api._model_routes._inference_engine")
    def test_returns_probabilities(self, mock_engine) -> None:
        mock_engine.predict_proba.return_value = {
            "strikeout": 0.22, "out": 0.46, "walk": 0.08,
        }
        client = _make_client()
        resp = client.post("/api/analytics/model-predict", json={
            "sport": "mlb",
            "model_type": "plate_appearance",
            "profiles": {},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["sport"] == "mlb"
        assert data["model_type"] == "plate_appearance"
        assert "probabilities" in data

    def test_validation_missing_sport(self) -> None:
        client = _make_client()
        resp = client.post("/api/analytics/model-predict", json={
            "model_type": "game",
        })
        assert resp.status_code == 422


class TestGetModelPredict:
    """GET /api/analytics/model-predict"""

    @patch("app.analytics.api._model_routes._inference_engine")
    def test_default_params(self, mock_engine) -> None:
        mock_engine.predict_proba.return_value = {"strikeout": 0.22}
        client = _make_client()
        resp = client.get("/api/analytics/model-predict")
        assert resp.status_code == 200
        data = resp.json()
        assert data["sport"] == "mlb"
        assert data["model_type"] == "plate_appearance"
        assert "probabilities" in data

    @patch("app.analytics.api._model_routes._inference_engine")
    def test_custom_params(self, mock_engine) -> None:
        mock_engine.predict_proba.return_value = {}
        client = _make_client()
        resp = client.get(
            "/api/analytics/model-predict?sport=mlb&model_type=game"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["model_type"] == "game"


# ---------------------------------------------------------------------------
# Model Registry
# ---------------------------------------------------------------------------


class TestGetModels:
    """GET /api/analytics/models"""

    @patch("app.analytics.api._model_routes._model_registry")
    def test_returns_empty_list(self, mock_registry) -> None:
        mock_registry.list_models.return_value = []
        client = _make_client()
        resp = client.get("/api/analytics/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["models"] == []
        assert data["count"] == 0

    @patch("app.analytics.api._model_routes._model_registry")
    def test_accepts_filters(self, mock_registry) -> None:
        mock_registry.list_models.return_value = []
        client = _make_client()
        resp = client.get(
            "/api/analytics/models?sport=mlb&model_type=game&sort_by=accuracy&active_only=true"
        )
        assert resp.status_code == 200

    @patch("app.analytics.api._model_routes._model_registry")
    def test_returns_models_from_training_jobs(self, mock_registry) -> None:
        """When training jobs exist, returns model list with artifact status."""
        from datetime import UTC, datetime

        mock_registry.list_models.return_value = [
            {"model_id": "model_a", "active": True},
        ]

        mock_db = AsyncMock()
        job = MagicMock()
        job.model_id = "model_a"
        job.artifact_path = "/tmp/nonexistent.pkl"
        job.id = 10
        job.created_at = datetime(2026, 3, 1, tzinfo=UTC)
        job.metrics = {"accuracy": 0.65}
        job.sport = "mlb"
        job.model_type = "game"
        job.feature_config_id = None
        job.algorithm = "gradient_boosting"
        job.train_count = 1000
        job.test_count = 200
        job.feature_importance = None

        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [job]
        result_mock.scalar_one_or_none.return_value = None
        result_mock.all.return_value = []
        mock_db.execute.return_value = result_mock
        mock_db.get.return_value = None

        client = _make_client(mock_db)
        resp = client.get("/api/analytics/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["models"][0]["model_id"] == "model_a"
        assert data["models"][0]["active"] is True
        assert data["models"][0]["artifact_status"] == "missing"

    @patch("app.analytics.api._model_routes._model_registry")
    def test_active_only_filters(self, mock_registry) -> None:
        """active_only=true skips inactive models."""
        from datetime import UTC, datetime

        mock_registry.list_models.return_value = []  # no active models

        mock_db = AsyncMock()
        job = MagicMock()
        job.model_id = "model_inactive"
        job.artifact_path = None
        job.id = 5
        job.created_at = datetime(2026, 3, 1, tzinfo=UTC)
        job.metrics = {}
        job.sport = "mlb"
        job.model_type = "game"
        job.feature_config_id = None
        job.algorithm = "random_forest"
        job.train_count = 500
        job.test_count = 100
        job.feature_importance = None

        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [job]
        result_mock.scalar_one_or_none.return_value = None
        result_mock.all.return_value = []
        mock_db.execute.return_value = result_mock
        mock_db.get.return_value = None

        client = _make_client(mock_db)
        resp = client.get("/api/analytics/models?active_only=true")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0

    @patch("app.analytics.api._model_routes._model_registry")
    def test_sort_by_version(self, mock_registry) -> None:
        """sort_by=version sorts models."""
        from datetime import UTC, datetime

        mock_registry.list_models.return_value = []

        mock_db = AsyncMock()
        jobs = []
        for i, mid in enumerate(["model_a", "model_b"]):
            job = MagicMock()
            job.model_id = mid
            job.artifact_path = None
            job.id = i + 1
            job.created_at = datetime(2026, 3, 1, tzinfo=UTC)
            job.metrics = {}
            job.sport = "mlb"
            job.model_type = "game"
            job.feature_config_id = None
            job.algorithm = "gradient_boosting"
            job.train_count = 100
            job.test_count = 20
            job.feature_importance = None
            jobs.append(job)

        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = jobs
        result_mock.scalar_one_or_none.return_value = None
        result_mock.all.return_value = []
        mock_db.execute.return_value = result_mock
        mock_db.get.return_value = None

        client = _make_client(mock_db)
        resp = client.get("/api/analytics/models?sort_by=version")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2


class TestGetModelDetails:
    """GET /api/analytics/models/details"""

    @patch("app.analytics.api._model_routes._model_service")
    def test_not_found(self, mock_service) -> None:
        mock_service.get_model_details.return_value = None
        client = _make_client()
        resp = client.get("/api/analytics/models/details?model_id=nonexistent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "not_found"

    def test_missing_model_id_param(self) -> None:
        client = _make_client()
        resp = client.get("/api/analytics/models/details")
        assert resp.status_code == 422

    @patch("app.analytics.api._model_routes._model_registry")
    def test_returns_details_from_db(self, mock_registry) -> None:
        """Returns model details from training job DB record."""
        from datetime import UTC, datetime

        mock_registry.list_models.return_value = [
            {"model_id": "model_xyz", "active": True},
        ]

        mock_db = AsyncMock()
        job = MagicMock()
        job.model_id = "model_xyz"
        job.artifact_path = "/tmp/model.pkl"
        job.id = 7
        job.created_at = datetime(2026, 3, 1, tzinfo=UTC)
        job.metrics = {"accuracy": 0.70}
        job.sport = "mlb"
        job.model_type = "plate_appearance"
        job.algorithm = "gradient_boosting"
        job.train_count = 2000
        job.test_count = 400
        job.feature_names = ["f1", "f2"]
        job.feature_importance = None
        job.date_start = "2025-07-01"
        job.date_end = "2025-10-01"
        job.rolling_window = 30

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = job
        result_mock.scalars.return_value.all.return_value = []
        result_mock.all.return_value = []
        mock_db.execute.return_value = result_mock
        mock_db.get.return_value = None

        client = _make_client(mock_db)
        resp = client.get("/api/analytics/models/details?model_id=model_xyz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["model_id"] == "model_xyz"
        assert data["active"] is True
        assert data["algorithm"] == "gradient_boosting"


class TestGetModelCompare:
    """GET /api/analytics/models/compare"""

    @patch("app.analytics.api._model_routes._model_service")
    def test_returns_comparison(self, mock_service) -> None:
        mock_service.compare_models.return_value = {"models": [], "count": 0}
        client = _make_client()
        resp = client.get(
            "/api/analytics/models/compare?sport=mlb&model_type=game&model_ids=m1,m2"
        )
        assert resp.status_code == 200

    def test_missing_required_params(self) -> None:
        client = _make_client()
        resp = client.get("/api/analytics/models/compare")
        assert resp.status_code == 422


class TestPostActivateModel:
    """POST /api/analytics/models/activate"""

    @patch("app.analytics.api._model_routes._inference_engine")
    @patch("app.analytics.api._model_routes._model_registry")
    def test_model_not_found(self, mock_registry, mock_engine) -> None:
        mock_registry._get_bucket.return_value = None
        client = _make_client()
        resp = client.post("/api/analytics/models/activate", json={
            "sport": "mlb",
            "model_type": "game",
            "model_id": "nonexistent",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"

    @patch("app.analytics.api._model_routes._inference_engine")
    @patch("app.analytics.api._model_routes._model_registry")
    def test_activates_existing_model(self, mock_registry, mock_engine) -> None:
        mock_registry._get_bucket.return_value = {
            "models": [{"model_id": "mlb_game_abc"}]
        }
        mock_registry.activate_model.return_value = {
            "status": "success", "model_id": "mlb_game_abc",
        }
        client = _make_client()
        resp = client.post("/api/analytics/models/activate", json={
            "sport": "mlb",
            "model_type": "game",
            "model_id": "mlb_game_abc",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        mock_engine._cache.clear.assert_called_once()


class TestGetActiveModel:
    """GET /api/analytics/models/active"""

    @patch("app.analytics.api._model_routes._model_registry")
    def test_no_active_model(self, mock_registry) -> None:
        mock_registry.get_active_model.return_value = None
        client = _make_client()
        resp = client.get(
            "/api/analytics/models/active?sport=mlb&model_type=game"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["active_model"] is None
        assert data["sport"] == "mlb"

    @patch("app.analytics.api._model_routes._model_registry")
    def test_has_active_model(self, mock_registry) -> None:
        mock_registry.get_active_model.return_value = {
            "model_id": "mlb_game_abc",
            "version": 3,
            "metrics": {"accuracy": 0.65},
        }
        client = _make_client()
        resp = client.get(
            "/api/analytics/models/active?sport=mlb&model_type=game"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["active_model"] == "mlb_game_abc"
        assert data["metrics"]["accuracy"] == 0.65

    def test_missing_required_params(self) -> None:
        client = _make_client()
        resp = client.get("/api/analytics/models/active")
        assert resp.status_code == 422


class TestGetModelMetrics:
    """GET /api/analytics/model-metrics"""

    @patch("app.analytics.api._model_routes._model_registry")
    def test_returns_empty(self, mock_registry) -> None:
        mock_registry.list_models.return_value = []
        client = _make_client()
        resp = client.get("/api/analytics/model-metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["models"] == []
        assert data["count"] == 0

    @patch("app.analytics.api._model_routes._model_registry")
    def test_filter_by_model_id(self, mock_registry) -> None:
        mock_registry.list_models.return_value = [
            {"model_id": "m1", "sport": "mlb", "model_type": "game",
             "version": 1, "active": True, "metrics": {}},
        ]
        client = _make_client()
        resp = client.get("/api/analytics/model-metrics?model_id=m1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1


# ---------------------------------------------------------------------------
# Ensemble Configuration
# ---------------------------------------------------------------------------


class TestGetEnsembleConfig:
    """GET /api/analytics/ensemble-config"""

    def test_returns_config(self) -> None:
        client = _make_client()
        resp = client.get(
            "/api/analytics/ensemble-config?sport=mlb&model_type=plate_appearance"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "sport" in data
        assert "providers" in data

    def test_missing_required_params(self) -> None:
        client = _make_client()
        resp = client.get("/api/analytics/ensemble-config")
        assert resp.status_code == 422


class TestListEnsembleConfigs:
    """GET /api/analytics/ensemble-configs"""

    def test_returns_list(self) -> None:
        client = _make_client()
        resp = client.get("/api/analytics/ensemble-configs")
        assert resp.status_code == 200
        data = resp.json()
        assert "configs" in data
        assert "count" in data


class TestPostEnsembleConfig:
    """POST /api/analytics/ensemble-config"""

    def test_updates_config(self) -> None:
        client = _make_client()
        resp = client.post("/api/analytics/ensemble-config", json={
            "sport": "mlb",
            "model_type": "game",
            "providers": [
                {"name": "rule_based", "weight": 0.4},
                {"name": "ml", "weight": 0.6},
            ],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "updated"
        assert data["sport"] == "mlb"

    def test_validation_missing_providers(self) -> None:
        client = _make_client()
        resp = client.post("/api/analytics/ensemble-config", json={
            "sport": "mlb",
            "model_type": "game",
        })
        assert resp.status_code == 422

    def test_validation_empty_providers(self) -> None:
        client = _make_client()
        resp = client.post("/api/analytics/ensemble-config", json={
            "sport": "mlb",
            "model_type": "game",
            "providers": [],
        })
        assert resp.status_code == 422

    def test_validation_negative_weight(self) -> None:
        client = _make_client()
        resp = client.post("/api/analytics/ensemble-config", json={
            "sport": "mlb",
            "model_type": "game",
            "providers": [
                {"name": "rule_based", "weight": -0.5},
                {"name": "ml", "weight": 0.6},
            ],
        })
        assert resp.status_code == 422

    def test_validation_all_zero_weights(self) -> None:
        client = _make_client()
        resp = client.post("/api/analytics/ensemble-config", json={
            "sport": "mlb",
            "model_type": "game",
            "providers": [
                {"name": "rule_based", "weight": 0},
                {"name": "ml", "weight": 0},
            ],
        })
        assert resp.status_code == 422

    def test_validation_missing_name_key(self) -> None:
        client = _make_client()
        resp = client.post("/api/analytics/ensemble-config", json={
            "sport": "mlb",
            "model_type": "game",
            "providers": [{"weight": 0.5}],
        })
        assert resp.status_code == 422

    def test_non_normalized_weights_accepted(self) -> None:
        """Weights that don't sum to 1.0 are accepted (engine normalizes)."""
        client = _make_client()
        resp = client.post("/api/analytics/ensemble-config", json={
            "sport": "mlb",
            "model_type": "game",
            "providers": [
                {"name": "rule_based", "weight": 0.3},
                {"name": "ml", "weight": 0.3},
            ],
        })
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Model Deletion
# ---------------------------------------------------------------------------


class TestDeleteModel:
    """DELETE /api/analytics/models"""

    def test_not_found(self) -> None:
        client = _make_client()
        resp = client.request(
            "DELETE", "/api/analytics/models",
            json={"model_id": "nonexistent"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "not_found"

    @patch("app.analytics.api._model_routes._inference_engine")
    @patch("app.analytics.api._model_routes._model_registry")
    def test_deletes_model(self, mock_registry, mock_engine) -> None:
        mock_db = AsyncMock()

        job = MagicMock()
        job.sport = "mlb"
        job.model_type = "game"
        job.artifact_path = None

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = job
        result_mock.scalars.return_value.all.return_value = []
        result_mock.all.return_value = []
        mock_db.execute.return_value = result_mock
        mock_db.get.return_value = None
        mock_db.delete = AsyncMock()
        mock_db.commit = AsyncMock()

        client = _make_client(mock_db)
        resp = client.request(
            "DELETE", "/api/analytics/models",
            json={"model_id": "model_to_delete"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "deleted"
        assert data["artifact_deleted"] is False
        mock_registry.remove_model.assert_called_once()
        mock_engine._cache.clear.assert_called_once()
