"""Route-level tests for analytics feature config endpoints.

Covers: feature-configs, feature-config CRUD, clone, available-features.
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
        mock_result.scalar.return_value = 0
        mock_db.execute.return_value = mock_result
        mock_db.get.return_value = None

    async def mock_get_db():
        yield mock_db

    app = FastAPI()
    app.dependency_overrides[get_db] = mock_get_db
    app.include_router(router)
    return TestClient(app)


def _mock_feature_config(
    id=1,
    name="test-loadout",
    sport="mlb",
    model_type="game",
    features=None,
    is_default=False,
):
    """Create a mock AnalyticsFeatureConfig row."""
    row = MagicMock()
    row.id = id
    row.name = name
    row.sport = sport
    row.model_type = model_type
    row.features = features or [
        {"name": "contact_rate", "enabled": True, "weight": 1.0},
        {"name": "power_index", "enabled": False, "weight": 0.5},
    ]
    row.is_default = is_default
    row.created_at = None
    row.updated_at = None
    return row


class TestListFeatureConfigs:
    """GET /api/analytics/feature-configs"""

    def test_returns_empty(self) -> None:
        client = _make_client()
        resp = client.get("/api/analytics/feature-configs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["loadouts"] == []
        assert data["count"] == 0

    def test_accepts_filters(self) -> None:
        client = _make_client()
        resp = client.get(
            "/api/analytics/feature-configs?sport=mlb&model_type=game"
        )
        assert resp.status_code == 200

    def test_with_results(self) -> None:
        mock_db = AsyncMock()
        row = _mock_feature_config()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [row]
        mock_db.execute.return_value = mock_result

        client = _make_client(mock_db)
        resp = client.get("/api/analytics/feature-configs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["loadouts"][0]["name"] == "test-loadout"
        assert data["loadouts"][0]["enabled_count"] == 1  # only contact_rate enabled
        assert data["loadouts"][0]["total_count"] == 2


class TestGetFeatureConfig:
    """GET /api/analytics/feature-config/{config_id}"""

    def test_404_when_not_found(self) -> None:
        client = _make_client()
        resp = client.get("/api/analytics/feature-config/999")
        assert resp.status_code == 404

    def test_returns_config(self) -> None:
        mock_db = AsyncMock()
        row = _mock_feature_config()
        mock_db.get.return_value = row
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        client = _make_client(mock_db)
        resp = client.get("/api/analytics/feature-config/1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == 1
        assert data["name"] == "test-loadout"
        assert data["sport"] == "mlb"


class TestCreateFeatureConfig:
    """POST /api/analytics/feature-config"""

    @patch("app.analytics.api._feature_routes.AnalyticsFeatureConfig")
    def test_creates_config(self, mock_model_cls) -> None:
        created_row = _mock_feature_config(id=5, name="new-loadout")
        mock_model_cls.return_value = created_row

        mock_db = AsyncMock()
        async def mock_refresh(obj):
            pass  # created_row already has all attrs
        mock_db.refresh = mock_refresh
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        client = _make_client(mock_db)
        resp = client.post("/api/analytics/feature-config", json={
            "name": "new-loadout",
            "sport": "mlb",
            "model_type": "game",
            "features": [{"name": "contact_rate", "enabled": True, "weight": 1.0}],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "created"
        assert data["name"] == "new-loadout"

    def test_validation_error_missing_name(self) -> None:
        client = _make_client()
        resp = client.post("/api/analytics/feature-config", json={
            "sport": "mlb",
            "model_type": "game",
            "features": [],
        })
        assert resp.status_code == 422


class TestUpdateFeatureConfig:
    """PUT /api/analytics/feature-config/{config_id}"""

    def test_404_when_not_found(self) -> None:
        client = _make_client()
        resp = client.put("/api/analytics/feature-config/999", json={"name": "x"})
        assert resp.status_code == 404

    def test_updates_config(self) -> None:
        mock_db = AsyncMock()
        row = _mock_feature_config()
        mock_db.get.return_value = row

        async def mock_refresh(obj):
            pass  # row already has updated attrs

        mock_db.refresh = mock_refresh
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        client = _make_client(mock_db)
        resp = client.put("/api/analytics/feature-config/1", json={
            "name": "renamed",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "updated"


class TestDeleteFeatureConfig:
    """DELETE /api/analytics/feature-config/{config_id}"""

    def test_404_when_not_found(self) -> None:
        client = _make_client()
        resp = client.delete("/api/analytics/feature-config/999")
        assert resp.status_code == 404

    def test_deletes_config(self) -> None:
        mock_db = AsyncMock()
        row = _mock_feature_config(id=7, name="to-delete")
        mock_db.get.return_value = row
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        client = _make_client(mock_db)
        resp = client.delete("/api/analytics/feature-config/7")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "deleted"
        assert data["id"] == 7
        assert data["name"] == "to-delete"


class TestCloneFeatureConfig:
    """POST /api/analytics/feature-config/{config_id}/clone"""

    def test_404_when_not_found(self) -> None:
        client = _make_client()
        resp = client.post("/api/analytics/feature-config/999/clone")
        assert resp.status_code == 404

    @patch("app.analytics.api._feature_routes.AnalyticsFeatureConfig")
    def test_clones_config(self, mock_model_cls) -> None:
        mock_db = AsyncMock()
        source_row = _mock_feature_config(id=1, name="original")
        clone_row = _mock_feature_config(id=10, name="original (copy)")
        mock_db.get.return_value = source_row
        mock_model_cls.return_value = clone_row

        async def mock_refresh(obj):
            pass
        mock_db.refresh = mock_refresh
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        client = _make_client(mock_db)
        resp = client.post("/api/analytics/feature-config/1/clone")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "cloned"

    @patch("app.analytics.api._feature_routes.AnalyticsFeatureConfig")
    def test_clone_with_custom_name(self, mock_model_cls) -> None:
        mock_db = AsyncMock()
        source_row = _mock_feature_config(id=1, name="original")
        clone_row = _mock_feature_config(id=11, name="my-clone")
        mock_db.get.return_value = source_row
        mock_model_cls.return_value = clone_row

        async def mock_refresh(obj):
            pass
        mock_db.refresh = mock_refresh
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        client = _make_client(mock_db)
        resp = client.post(
            "/api/analytics/feature-config/1/clone?name=my-clone"
        )
        assert resp.status_code == 200


class TestAvailableFeatures:
    """GET /api/analytics/available-features"""

    def test_returns_mlb_features(self) -> None:
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 42
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        client = _make_client(mock_db)
        resp = client.get("/api/analytics/available-features?sport=mlb")
        assert resp.status_code == 200
        data = resp.json()
        assert data["sport"] == "mlb"
        assert data["total_games_with_data"] == 42
        assert len(data["plate_appearance_features"]) > 0
        assert len(data["game_features"]) > 0
        assert len(data["all_features"]) == (
            len(data["plate_appearance_features"]) + len(data["game_features"])
        )

    def test_unsupported_sport(self) -> None:
        client = _make_client()
        resp = client.get("/api/analytics/available-features?sport=nfl")
        assert resp.status_code == 200
        data = resp.json()
        assert data["features"] == []
