"""HTTP contract tests for Scroll Down MLB.

Mounts the router on a fresh FastAPI app and exercises each endpoint via
TestClient. The Phase 5 router takes an `AsyncSession` via `Depends(get_db)`;
contract tests override that dependency with a no-op session and stub the
service functions so router behavior is tested in isolation from the DB.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import get_db
from app.scroll_down_mlb import service as sdm_service
from app.scroll_down_mlb.router import router as scroll_down_mlb_router
from app.scroll_down_mlb.schemas import (
    DeckCardType,
    PlannerReport,
    ScrollDownMlbDeckCard,
    ScrollDownMlbDeckResponse,
    ScrollDownMlbRecentResponse,
)


def _build_client() -> TestClient:
    app = FastAPI()
    app.include_router(scroll_down_mlb_router)
    # Override get_db so the test doesn't try to open a real async engine.
    # Service functions are stubbed below, so the session is never read.
    app.dependency_overrides[get_db] = lambda: AsyncMock()
    return TestClient(app)


def _stub_deck(game_id: str = "190203") -> ScrollDownMlbDeckResponse:
    """Schema-valid stub deck with one play card for shape assertions."""
    return ScrollDownMlbDeckResponse(
        game_id=game_id,
        deck_version="stub-v0",
        generated_at=datetime.now(timezone.utc),
        is_final=False,
        cards=[
            ScrollDownMlbDeckCard(
                id=f"{game_id}-scene",
                type=DeckCardType.scene,
                sort_order=0,
                title="First pitch",
                description="The matchup is set.",
            ),
        ],
        planner_report=PlannerReport(),
        validation_warnings=[],
    )


# ---------------------------------------------------------------------------
# /games/recent
# ---------------------------------------------------------------------------


def test_recent_returns_envelope_with_games_array(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _empty(*_args: Any, **_kwargs: Any):
        return []

    monkeypatch.setattr(sdm_service, "get_recent_games", _empty)
    client = _build_client()
    resp = client.get("/api/v1/scroll-down-mlb/games/recent")
    assert resp.status_code == 200
    body = resp.json()
    parsed = ScrollDownMlbRecentResponse.model_validate(body)
    assert parsed.games == []


# ---------------------------------------------------------------------------
# /games/{gameId}/deck
# ---------------------------------------------------------------------------


def test_deck_returns_schema_valid_response(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _stub(*_args: Any, **_kwargs: Any) -> ScrollDownMlbDeckResponse:
        return _stub_deck()

    monkeypatch.setattr(sdm_service, "get_game_deck", _stub)
    client = _build_client()
    resp = client.get("/api/v1/scroll-down-mlb/games/190203/deck")
    assert resp.status_code == 200
    body = resp.json()
    parsed = ScrollDownMlbDeckResponse.model_validate(body)
    assert parsed.game_id == "190203"
    assert parsed.spoiler_policy.value == "pre_reveal"
    assert isinstance(parsed.cards, list)


def test_deck_returns_404_when_no_deck(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _none(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(sdm_service, "get_game_deck", _none)
    client = _build_client()
    resp = client.get("/api/v1/scroll-down-mlb/games/190203/deck")
    assert resp.status_code == 404


def test_deck_response_uses_camel_case_keys_on_wire(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _stub(*_args: Any, **_kwargs: Any) -> ScrollDownMlbDeckResponse:
        return _stub_deck()

    monkeypatch.setattr(sdm_service, "get_game_deck", _stub)
    client = _build_client()
    body = client.get("/api/v1/scroll-down-mlb/games/190203/deck").json()
    assert "gameId" in body
    assert "deckVersion" in body
    assert "generatedAt" in body
    assert "isFinal" in body
    assert "spoilerPolicy" in body
    assert "game_id" not in body
    assert "deck_version" not in body


# ---------------------------------------------------------------------------
# /games/{gameId}/deck — ETag / If-None-Match short-circuit
# ---------------------------------------------------------------------------


def test_deck_response_sets_etag_header_from_deck_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """200 responses must carry an ETag header derived from deckVersion."""

    async def _stub_deck_fn(*_args: Any, **_kwargs: Any) -> ScrollDownMlbDeckResponse:
        return _stub_deck()

    monkeypatch.setattr(sdm_service, "get_game_deck", _stub_deck_fn)
    client = _build_client()
    resp = client.get("/api/v1/scroll-down-mlb/games/190203/deck")
    assert resp.status_code == 200
    assert resp.headers["etag"] == '"stub-v0"'
    # deckVersion must still be present in the body — clients without ETag
    # support fall back to body-level comparison.
    assert resp.json()["deckVersion"] == "stub-v0"


def test_deck_returns_304_when_if_none_match_matches_current_etag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When client's If-None-Match matches the current etag, return 304
    with no body and without calling the full builder."""

    builder_calls: list[Any] = []

    async def _etag(*_args: Any, **_kwargs: Any) -> str:
        return "live-abcdef0123456789"

    async def _builder(*args: Any, **kwargs: Any) -> ScrollDownMlbDeckResponse:
        builder_calls.append((args, kwargs))
        return _stub_deck()

    monkeypatch.setattr(sdm_service, "compute_deck_etag", _etag)
    monkeypatch.setattr(sdm_service, "get_game_deck", _builder)
    client = _build_client()
    resp = client.get(
        "/api/v1/scroll-down-mlb/games/190203/deck",
        headers={"If-None-Match": '"live-abcdef0123456789"'},
    )
    assert resp.status_code == 304
    assert resp.content == b""
    assert resp.headers["etag"] == '"live-abcdef0123456789"'
    # Critical: the full build pipeline must not have run on the 304 path.
    assert builder_calls == []


def test_deck_returns_200_when_if_none_match_differs_from_current_etag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale If-None-Match must fall through to the full deck build."""

    builder_calls: list[Any] = []

    async def _etag(*_args: Any, **_kwargs: Any) -> str:
        return "live-newversion0001"

    async def _builder(*args: Any, **kwargs: Any) -> ScrollDownMlbDeckResponse:
        builder_calls.append((args, kwargs))
        return _stub_deck()

    monkeypatch.setattr(sdm_service, "compute_deck_etag", _etag)
    monkeypatch.setattr(sdm_service, "get_game_deck", _builder)
    client = _build_client()
    resp = client.get(
        "/api/v1/scroll-down-mlb/games/190203/deck",
        headers={"If-None-Match": '"live-oldversion0000"'},
    )
    assert resp.status_code == 200
    assert len(builder_calls) == 1
    body = resp.json()
    assert body["deckVersion"] == "stub-v0"


def test_deck_omits_etag_check_when_no_header_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without an If-None-Match header, the cheap etag computation is
    skipped — a polite client should still always get a 200 with body."""

    etag_calls: list[Any] = []
    builder_calls: list[Any] = []

    async def _etag(*args: Any, **_kwargs: Any) -> str:
        etag_calls.append(args)
        return "live-shouldnotmatter"

    async def _builder(*args: Any, **kwargs: Any) -> ScrollDownMlbDeckResponse:
        builder_calls.append((args, kwargs))
        return _stub_deck()

    monkeypatch.setattr(sdm_service, "compute_deck_etag", _etag)
    monkeypatch.setattr(sdm_service, "get_game_deck", _builder)
    client = _build_client()
    resp = client.get("/api/v1/scroll-down-mlb/games/190203/deck")
    assert resp.status_code == 200
    assert len(builder_calls) == 1
    # No header → no etag pre-check.
    assert etag_calls == []


def test_deck_falls_through_when_current_etag_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the lightweight etag computation returns None (no deck
    available), don't 304 — let the builder produce the canonical 404."""

    async def _etag(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def _builder(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(sdm_service, "compute_deck_etag", _etag)
    monkeypatch.setattr(sdm_service, "get_game_deck", _builder)
    client = _build_client()
    resp = client.get(
        "/api/v1/scroll-down-mlb/games/190203/deck",
        headers={"If-None-Match": '"anything"'},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# /games/{gameId}/reveal
# ---------------------------------------------------------------------------


def test_reveal_returns_409_when_not_available(monkeypatch: pytest.MonkeyPatch) -> None:
    """Service returns None for a non-final game; router translates to 409."""

    async def _none(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(sdm_service, "get_game_reveal", _none)
    client = _build_client()
    resp = client.get("/api/v1/scroll-down-mlb/games/190203/reveal")
    assert resp.status_code == 409
    body = resp.json()
    assert "detail" in body
