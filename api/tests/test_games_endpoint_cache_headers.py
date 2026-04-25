"""Verify that ``GET /api/admin/sports/games`` actually emits the cache
diagnostic headers (``Cache-Control`` and ``X-Cache``) on the wire.

Reproduces the downstream report: "Not seeing Cache-Control / X-Cache
headers on /api/admin/sports/games". If this test passes, the headers
are leaving our handler, and any missing-headers symptom is downstream
of the API container (Caddy, Cloudflare, the client's request shape).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import get_db
from app.middleware.head_method import HeadAsGetMiddleware
from app.routers.sports import router as sports_router


def _stub_db_for_empty_result() -> AsyncMock:
    """Return a mock session that satisfies every execute() the handler does
    (page query + counts query + flow lookup) without hitting a real DB."""
    db = AsyncMock()

    def make_result(**kwargs):
        result = MagicMock()
        for k, v in kwargs.items():
            setattr(result, k, v)
        # Common access shapes used by the handler:
        result.unique = MagicMock(return_value=result)
        result.all = MagicMock(return_value=kwargs.get("rows", []))
        result.scalars = MagicMock(return_value=result)
        # `counts_row = (await session.execute(counts_stmt)).one()`
        if "counts_row" in kwargs:
            result.one = MagicMock(return_value=kwargs["counts_row"])
        return result

    counts_row = MagicMock()
    counts_row.total = 0
    counts_row.with_boxscore = 0
    counts_row.with_player_stats = 0
    counts_row.with_odds = 0
    counts_row.with_social = 0
    counts_row.with_pbp = 0
    counts_row.with_flow = 0
    counts_row.with_advanced_stats = 0

    # Sequence of execute() calls in the handler (in order):
    #   1) page query (unique().all() → list of (game, ...)) — 0 rows
    #   2) counts_stmt (.one() → counts_row)
    #   3) flow_check_stmt (only if game_ids non-empty — skipped here)
    db.execute = AsyncMock(
        side_effect=[
            make_result(rows=[]),
            make_result(counts_row=counts_row),
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
    """Anonymous GET /api/admin/sports/games should emit Cache-Control and
    X-Cache headers regardless of whether the cache is hit."""

    def test_miss_response_includes_cache_control_and_x_cache(self) -> None:
        client = _make_client()
        resp = client.get("/api/admin/sports/games?limit=1")
        assert resp.status_code == 200, resp.text
        assert resp.headers.get("cache-control") == "public, max-age=15"
        # MISS or DISABLED depending on Redis circuit state in the test env.
        assert resp.headers.get("x-cache") in {"MISS", "DISABLED"}

    def test_authorization_header_emits_bypass(self) -> None:
        client = _make_client()
        resp = client.get(
            "/api/admin/sports/games?limit=1",
            headers={"Authorization": "Bearer not-validated-here"},
        )
        # The response_cache short-circuits when Authorization is present.
        # Cache-Control is still emitted; X-Cache should be BYPASS.
        assert resp.status_code == 200, resp.text
        assert resp.headers.get("cache-control") == "public, max-age=15"
        assert resp.headers.get("x-cache") == "BYPASS"

    def test_head_returns_405_without_middleware(self) -> None:
        """Baseline: stock FastAPI rejects HEAD on a GET-only route.
        This documents why we need ``HeadAsGetMiddleware`` at all."""
        client = _make_client(with_head_middleware=False)
        resp = client.head("/api/admin/sports/games?limit=1")
        assert resp.status_code == 405
        assert resp.headers.get("cache-control") is None
        assert resp.headers.get("x-cache") is None

    def test_head_with_middleware_returns_200_with_cache_headers(self) -> None:
        """With ``HeadAsGetMiddleware``, a HEAD probe (e.g. ``curl -I``)
        runs through the GET handler and sees the same cache headers.
        Body is empty per HTTP/1.1 HEAD semantics."""
        client = _make_client(with_head_middleware=True)
        resp = client.head("/api/admin/sports/games?limit=1")
        assert resp.status_code == 200
        assert resp.headers.get("cache-control") == "public, max-age=15"
        assert resp.headers.get("x-cache") in {"MISS", "DISABLED"}
        # Body must be empty for HEAD.
        assert resp.content == b""
