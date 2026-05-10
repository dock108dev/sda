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
