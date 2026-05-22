"""Verify the catch-up games endpoint does not expose legacy cache headers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import get_db
from app.middleware.head_method import HeadAsGetMiddleware
from app.routers.sports import router as sports_router


def _stub_db_for_empty_result() -> AsyncMock:
    """Return a mock session for the empty catch-up list path."""
    db = AsyncMock()

    def make_result(**kwargs):
        result = MagicMock()
        for k, v in kwargs.items():
            setattr(result, k, v)
        # Common access shapes used by the handler:
        result.unique = MagicMock(return_value=result)
        result.all = MagicMock(return_value=kwargs.get("rows", []))
        result.scalars = MagicMock(return_value=result)
        result.scalar_one = MagicMock(return_value=kwargs.get("scalar", 0))
        return result

    # Sequence of execute() calls in the handler (in order):
    #   1) page query (unique().all() → list of (game, ...)) — 0 rows
    #   2) count query (scalar_one() → total)
    db.execute = AsyncMock(
        side_effect=[
            make_result(rows=[]),
            make_result(scalar=0),
        ]
    )
    return db


def _make_client(*, with_head_middleware: bool = True) -> TestClient:
    db = _stub_db_for_empty_result()

    async def mock_get_db():
        yield db

    app = FastAPI()
    app.dependency_overrides[get_db] = mock_get_db
    app.include_router(sports_router)
    if with_head_middleware:
        app.add_middleware(HeadAsGetMiddleware)
    return TestClient(app)


class TestGamesEndpointCacheHeaders:
    """Catch-up games intentionally avoid legacy cache diagnostic headers."""

    def test_get_response_omits_legacy_cache_headers(self) -> None:
        client = _make_client()
        resp = client.get("/api/admin/sports/games?limit=1")
        assert resp.status_code == 200, resp.text
        assert resp.headers.get("cache-control") is None
        assert resp.headers.get("x-cache") is None

    def test_authorization_header_does_not_reenable_legacy_bypass_header(self) -> None:
        client = _make_client()
        resp = client.get(
            "/api/admin/sports/games?limit=1",
            headers={"Authorization": "Bearer not-validated-here"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.headers.get("cache-control") is None
        assert resp.headers.get("x-cache") is None

    def test_head_returns_405_without_middleware(self) -> None:
        """Baseline: stock FastAPI rejects HEAD on a GET-only route.
        This documents why we need ``HeadAsGetMiddleware`` at all."""
        client = _make_client(with_head_middleware=False)
        resp = client.head("/api/admin/sports/games?limit=1")
        assert resp.status_code == 405
        assert resp.headers.get("cache-control") is None
        assert resp.headers.get("x-cache") is None

    def test_head_with_middleware_returns_200_without_legacy_cache_headers(self) -> None:
        """With ``HeadAsGetMiddleware``, a HEAD probe (e.g. ``curl -I``)
        runs through the GET handler. Body is empty per HTTP/1.1 HEAD semantics."""
        client = _make_client(with_head_middleware=True)
        resp = client.head("/api/admin/sports/games?limit=1")
        assert resp.status_code == 200
        assert resp.headers.get("cache-control") is None
        assert resp.headers.get("x-cache") is None
        # Body must be empty for HEAD.
        assert resp.content == b""
