"""Tests for SUBDOMAIN_ROUTING feature flag — CORS configuration and origin matching.

Covers:
  - cors_origin_regex is None when SUBDOMAIN_ROUTING=false (default)
  - cors_origin_regex allows *.BASE_DOMAIN when SUBDOMAIN_ROUTING=true
  - regex correctly accepts subdomain origins and rejects unrelated domains
  - parametrized: both routing strategies exercise the same clubs endpoint handler
    (slug extraction is identical regardless of how it reaches the API)
"""

from __future__ import annotations

import re
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import get_db
from app.db.club import Club
from app.db.golf_pools import GolfPool
from app.routers.clubs import router


# ---------------------------------------------------------------------------
# Settings / CORS origin regex
# ---------------------------------------------------------------------------


def _make_settings(subdomain_routing: bool, base_domain: str = "app.example.com"):
    from app.config import Settings

    return Settings(
        SUBDOMAIN_ROUTING=subdomain_routing,
        BASE_DOMAIN=base_domain,
        DATABASE_URL="postgresql+asyncpg://test:test@localhost/testdb",
    )


def test_cors_origin_regex_is_none_when_disabled():
    s = _make_settings(subdomain_routing=False)
    assert s.cors_origin_regex is None


def test_cors_origin_regex_set_when_enabled():
    s = _make_settings(subdomain_routing=True, base_domain="app.example.com")
    assert s.cors_origin_regex is not None


@pytest.mark.parametrize(
    "origin,expected",
    [
        ("https://the-pines-gc.app.example.com", True),
        ("https://riverside-cc.app.example.com", True),
        ("http://the-pines-gc.app.example.com", True),
        ("https://app.example.com", False),       # base domain itself, no subdomain
        ("https://evil.notapp.example.com", False),
        ("https://other.com", False),
    ],
)
def test_cors_origin_regex_matches(origin: str, expected: bool):
    s = _make_settings(subdomain_routing=True, base_domain="app.example.com")
    pattern = re.compile(s.cors_origin_regex)
    assert bool(pattern.fullmatch(origin)) is expected


# ---------------------------------------------------------------------------
# Clubs endpoint — both routing strategies produce identical handler output
# ---------------------------------------------------------------------------


def _make_result(scalars: list[Any] | None = None, scalar: Any = None) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = scalar
    if scalars is not None:
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = scalars
        r.scalars.return_value = scalars_mock
    return r


class _QueueDB:
    def __init__(self, *results: Any) -> None:
        self._queue: list[Any] = list(results)

    async def execute(self, _stmt: Any) -> Any:
        return self._queue.pop(0)

    async def close(self) -> None:
        pass


def _make_club(slug: str = "the-pines-gc") -> Club:
    c = Club(club_id="uuid-test", slug=slug, name="The Pines GC", plan_id="price_pro", status="active")
    c.id = 1
    c.branding_json = None
    return c


def _make_pool() -> GolfPool:
    p = GolfPool(
        code="masters-2026",
        name="Masters 2026",
        club_code="the-pines-gc",
        club_id=1,
        tournament_id=5,
        status="open",
        allow_self_service_entry=True,
    )
    p.id = 10
    p.entry_deadline = None
    p.created_at = None
    return p


def _app(db_override: Any) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db_override
    return app


@pytest.mark.parametrize(
    "strategy,request_path,slug_header",
    [
        # Path-based: slug comes from URL path param
        ("path", "/api/v1/clubs/the-pines-gc", None),
        # Subdomain: middleware would set X-Club-Slug; API endpoint ignores the header
        # and still resolves via path param — both strategies hit the same handler.
        ("subdomain", "/api/v1/clubs/the-pines-gc", "the-pines-gc"),
    ],
)
def test_both_routing_strategies_resolve_same_handler(
    strategy: str,
    request_path: str,
    slug_header: str | None,
) -> None:
    """Both path-based and subdomain routing reach the same clubs handler."""
    club = _make_club()
    pool = _make_pool()
    db = _QueueDB(
        _make_result(scalar=club),
        _make_result(scalars=[pool]),
    )
    client = TestClient(_app(db))

    headers = {"x-club-slug": slug_header} if slug_header else {}
    resp = client.get(request_path, headers=headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["slug"] == "the-pines-gc"
    assert body["name"] == "The Pines GC"
    assert len(body["active_pools"]) == 1
