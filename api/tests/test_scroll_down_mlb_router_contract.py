"""HTTP contract tests for Scroll Down MLB.

Mounts the router on a fresh FastAPI app and exercises each endpoint via
TestClient. The Phase 5 router takes an `AsyncSession` via `Depends(get_db)`;
contract tests override that dependency with a no-op session and stub the
service functions so router behavior is tested in isolation from the DB.
"""

from __future__ import annotations

import datetime
import sys
from datetime import UTC
from datetime import datetime as dt
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.scroll_down_mlb.router  # noqa: F401  — ensure submodule is loaded
from app.db import get_db
from app.scroll_down_mlb import service as sdm_service
from app.scroll_down_mlb.arcade_pack_service import (
    DailyPressurePack,
    NoPressurePackAvailable,
    PressureMoment,
)
from app.scroll_down_mlb.router import router as scroll_down_mlb_router
from app.scroll_down_mlb.schemas import (
    DeckCardType,
    PlannerReport,
    ScrollDownMlbDeckCard,
    ScrollDownMlbDeckResponse,
    ScrollDownMlbRecentResponse,
)

# The package's ``__init__`` rebinds ``app.scroll_down_mlb.router`` to the
# APIRouter object, shadowing the submodule. Reach for the module via
# ``sys.modules`` so monkeypatching ``today_et`` and ``build_daily_pressure_pack``
# in tests actually targets the names the router calls at runtime.
router_module = sys.modules["app.scroll_down_mlb.router"]


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
        generated_at=dt.now(UTC),
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


# ---------------------------------------------------------------------------
# /pressure/today + /pressure/daily/{date}
# ---------------------------------------------------------------------------


def _make_pack(pack_date: datetime.date, *, count: int = 2) -> DailyPressurePack:
    """Helper: build a small DailyPressurePack stub for route shape tests."""
    moments = tuple(
        PressureMoment(
            game_id=100 + i,
            play_index=10 + i,
            rank=i + 1,
            difficulty=80 - 5 * i,
            tier="high",
            card_payload={"id": f"card-{i}", "type": "play"},
        )
        for i in range(count)
    )
    return DailyPressurePack(pack_date=pack_date, moments=moments)


def test_pressure_today_uses_yesterday_in_eastern_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`/today` must request yesterday's MLB calendar date — ET, not UTC.

    Pin both ``today_et`` (used by the router) so the test is deterministic
    regardless of when it runs.
    """
    fixed_today = datetime.date(2026, 5, 14)
    expected_yesterday = datetime.date(2026, 5, 13)

    seen_dates: list[datetime.date] = []

    async def _builder(target_date: datetime.date, *_a: Any, **_kw: Any) -> DailyPressurePack:
        seen_dates.append(target_date)
        return _make_pack(target_date)

    monkeypatch.setattr(router_module, "today_et", lambda: fixed_today)
    monkeypatch.setattr(router_module, "build_daily_pressure_pack", _builder)

    client = _build_client()
    resp = client.get("/api/v1/scroll-down-mlb/pressure/today")

    assert resp.status_code == 200
    assert seen_dates == [expected_yesterday]
    body = resp.json()
    assert body["date"] == "2026-05-13"
    assert isinstance(body["moments"], list)
    assert body["moments"][0]["gameId"] == "100"
    assert body["moments"][0]["rank"] == 1


def test_pressure_today_returns_structured_404_when_no_pack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 404 body must be flat ``{detail, date}`` so the client can
    read the date without traversing a nested FastAPI error envelope."""
    fixed_today = datetime.date(2026, 5, 14)

    async def _raise(target_date: datetime.date, *_a: Any, **_kw: Any) -> DailyPressurePack:
        raise NoPressurePackAvailable(target_date)

    monkeypatch.setattr(router_module, "today_et", lambda: fixed_today)
    monkeypatch.setattr(router_module, "build_daily_pressure_pack", _raise)

    client = _build_client()
    resp = client.get("/api/v1/scroll-down-mlb/pressure/today")

    assert resp.status_code == 404
    body = resp.json()
    assert body == {
        "detail": "No pressure pack available for 2026-05-13",
        "date": "2026-05-13",
    }


def test_pressure_daily_serves_explicit_date_pack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed_today = datetime.date(2026, 5, 14)
    target = datetime.date(2026, 5, 10)

    captured: list[datetime.date] = []

    async def _builder(target_date: datetime.date, *_a: Any, **_kw: Any) -> DailyPressurePack:
        captured.append(target_date)
        return _make_pack(target_date, count=1)

    monkeypatch.setattr(router_module, "today_et", lambda: fixed_today)
    monkeypatch.setattr(router_module, "build_daily_pressure_pack", _builder)

    client = _build_client()
    resp = client.get("/api/v1/scroll-down-mlb/pressure/daily/2026-05-10")

    assert resp.status_code == 200
    assert captured == [target]
    body = resp.json()
    assert body["date"] == "2026-05-10"
    assert len(body["moments"]) == 1


def test_pressure_daily_rejects_malformed_date_with_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`2026-5-1` is not strict ISO 8601 and must 422 with a clear message."""
    monkeypatch.setattr(router_module, "today_et", lambda: datetime.date(2026, 5, 14))

    client = _build_client()
    # The 10-char path constraint catches `2026-5-1` (which is 8 chars)
    # before the regex even runs — FastAPI returns 422 from path validation.
    # We assert the API contract: malformed dates do not 200/500/404, they 422.
    resp = client.get("/api/v1/scroll-down-mlb/pressure/daily/2026-5-1")
    assert resp.status_code == 422


def test_pressure_daily_rejects_non_iso_format_with_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Other 10-char strings that aren't `\\d{4}-\\d{2}-\\d{2}` must 422
    via the in-handler regex gate (not 200, not 500)."""
    monkeypatch.setattr(router_module, "today_et", lambda: datetime.date(2026, 5, 14))

    client = _build_client()
    resp = client.get("/api/v1/scroll-down-mlb/pressure/daily/2026.05.10")
    assert resp.status_code == 422
    body = resp.json()
    assert "Invalid date format" in body["detail"]


def test_pressure_daily_rejects_future_date_with_400(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed_today = datetime.date(2026, 5, 14)
    monkeypatch.setattr(router_module, "today_et", lambda: fixed_today)
    # The builder should NOT be called for a future date.
    builder_calls: list[Any] = []

    async def _builder(*args: Any, **kwargs: Any) -> DailyPressurePack:
        builder_calls.append((args, kwargs))
        return _make_pack(datetime.date(2026, 5, 14))

    monkeypatch.setattr(router_module, "build_daily_pressure_pack", _builder)

    client = _build_client()
    # Yesterday (in ET) is 2026-05-13; anything later must 400.
    resp = client.get("/api/v1/scroll-down-mlb/pressure/daily/2026-05-14")
    assert resp.status_code == 400
    assert "No games have been played yet for 2026-05-14" in resp.json()["detail"]
    assert builder_calls == []


def test_pressure_daily_returns_structured_404_for_empty_pack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed_today = datetime.date(2026, 5, 14)
    monkeypatch.setattr(router_module, "today_et", lambda: fixed_today)

    async def _raise(target_date: datetime.date, *_a: Any, **_kw: Any) -> DailyPressurePack:
        raise NoPressurePackAvailable(target_date)

    monkeypatch.setattr(router_module, "build_daily_pressure_pack", _raise)

    client = _build_client()
    resp = client.get("/api/v1/scroll-down-mlb/pressure/daily/2026-05-10")
    assert resp.status_code == 404
    body = resp.json()
    assert body == {
        "detail": "No pressure pack available for 2026-05-10",
        "date": "2026-05-10",
    }


def test_pressure_response_uses_camel_case_keys_on_wire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wire shape must use camelCase (`gameId`, `playIndex`, `cardPayload`)."""
    fixed_today = datetime.date(2026, 5, 14)

    async def _builder(target_date: datetime.date, *_a: Any, **_kw: Any) -> DailyPressurePack:
        return _make_pack(target_date, count=1)

    monkeypatch.setattr(router_module, "today_et", lambda: fixed_today)
    monkeypatch.setattr(router_module, "build_daily_pressure_pack", _builder)

    client = _build_client()
    body = client.get("/api/v1/scroll-down-mlb/pressure/today").json()
    assert "date" in body
    assert "moments" in body
    moment = body["moments"][0]
    assert "gameId" in moment
    assert "playIndex" in moment
    assert "cardPayload" in moment
    # Snake-case wire keys would be a regression.
    assert "game_id" not in moment
    assert "play_index" not in moment
    assert "card_payload" not in moment
