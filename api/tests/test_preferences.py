"""Tests for user preferences endpoints (GET/PUT/PATCH /auth/me/preferences)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import get_db
from app.dependencies.roles import require_user
from app.routers.preferences import router


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TS = datetime(2026, 3, 11, 12, 0, 0, tzinfo=timezone.utc)


def _make_app(mock_db=None, user_id: int = 1):
    """Create a test app with mocked DB and auth."""

    if mock_db is None:
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

    async def mock_get_db():
        yield mock_db

    async def mock_require_user():
        return "user"

    app = FastAPI()
    app.dependency_overrides[get_db] = mock_get_db
    app.dependency_overrides[require_user] = mock_require_user

    @app.middleware("http")
    async def inject_user(request, call_next):
        request.state.user_id = user_id
        return await call_next(request)

    app.include_router(router)
    return TestClient(app), mock_db


def _mock_prefs(
    settings: dict | None = None,
    pinned: list[int] | None = None,
    revealed: list[int] | None = None,
) -> MagicMock:
    """Build a mock that looks like a UserPreferences row."""
    prefs = MagicMock()
    prefs.settings = settings or {}
    prefs.pinned_game_ids = pinned or []
    prefs.revealed_game_ids = revealed or []
    prefs.updated_at = _TS
    return prefs


# ---------------------------------------------------------------------------
# GET /auth/me/preferences
# ---------------------------------------------------------------------------

class TestGetPreferences:

    def test_returns_empty_when_no_row(self) -> None:
        client, _ = _make_app()
        resp = client.get("/auth/me/preferences")
        assert resp.status_code == 200
        data = resp.json()
        assert data["settings"] == {}
        assert data["pinnedGameIds"] == []
        assert data["revealedGameIds"] == []

    def test_returns_saved_preferences(self) -> None:
        prefs = _mock_prefs(
            settings={"theme": "dark", "oddsFormat": "decimal"},
            pinned=[100, 200],
            revealed=[300],
        )
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = prefs
        mock_db.execute.return_value = mock_result

        client, _ = _make_app(mock_db)
        resp = client.get("/auth/me/preferences")
        assert resp.status_code == 200
        data = resp.json()
        assert data["settings"]["theme"] == "dark"
        assert data["pinnedGameIds"] == [100, 200]
        assert data["revealedGameIds"] == [300]


# ---------------------------------------------------------------------------
# PUT /auth/me/preferences
# ---------------------------------------------------------------------------

class TestPutPreferences:

    def test_replaces_existing_preferences(self) -> None:
        existing = _mock_prefs(settings={"theme": "light"}, pinned=[1])
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_db.execute.return_value = mock_result

        client, _ = _make_app(mock_db)
        resp = client.put(
            "/auth/me/preferences",
            json={
                "settings": {"theme": "dark"},
                "pinnedGameIds": [1, 2, 3],
                "revealedGameIds": [10],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        # Verify the mock was mutated
        assert existing.settings == {"theme": "dark"}
        assert existing.pinned_game_ids == [1, 2, 3]
        assert existing.revealed_game_ids == [10]

    def test_rejects_too_many_pinned(self) -> None:
        client, _ = _make_app()
        resp = client.put(
            "/auth/me/preferences",
            json={"pinnedGameIds": list(range(20))},
        )
        assert resp.status_code == 422

    def test_rejects_too_many_revealed(self) -> None:
        client, _ = _make_app()
        resp = client.put(
            "/auth/me/preferences",
            json={"revealedGameIds": list(range(501))},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# PATCH /auth/me/preferences
# ---------------------------------------------------------------------------

class TestPatchPreferences:

    def test_merges_settings(self) -> None:
        existing = _mock_prefs(settings={"theme": "light", "oddsFormat": "american"})

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_db.execute.return_value = mock_result

        client, _ = _make_app(mock_db)
        resp = client.patch(
            "/auth/me/preferences",
            json={"settings": {"theme": "dark"}},
        )
        assert resp.status_code == 200
        assert existing.settings["theme"] == "dark"
        assert existing.settings["oddsFormat"] == "american"

    def test_replaces_pinned_ids(self) -> None:
        existing = _mock_prefs(pinned=[1, 2, 3])

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_db.execute.return_value = mock_result

        client, _ = _make_app(mock_db)
        resp = client.patch(
            "/auth/me/preferences",
            json={"pinnedGameIds": [99]},
        )
        assert resp.status_code == 200
        assert existing.pinned_game_ids == [99]

    def test_ignores_unset_fields(self) -> None:
        existing = _mock_prefs(
            settings={"theme": "dark"},
            pinned=[1],
            revealed=[2],
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_db.execute.return_value = mock_result

        client, _ = _make_app(mock_db)
        resp = client.patch("/auth/me/preferences", json={})
        assert resp.status_code == 200
        assert existing.settings == {"theme": "dark"}
        assert existing.pinned_game_ids == [1]
        assert existing.revealed_game_ids == [2]
