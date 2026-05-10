"""Phase 5 integration tests — service flow against mocked DB sessions.

These tests prove the real-data path behaves correctly without requiring
a live Postgres. They cover the five branches the service has to handle:

  1. Game not found → None
  2. Game pregame   → None
  3. Game live      → fresh build, no persistence
  4. Game final     + no persisted deck → build + freeze
  5. Game final     + persisted deck    → serve persisted, no rebuild

Plus the recap-fallback shape for `get_game_reveal`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.scroll_down_mlb import persistence, service
from app.scroll_down_mlb._pipeline import _source_hash
from app.scroll_down_mlb.schemas import (
    PlannerReport,
    ScrollDownMlbDeckResponse,
)

_FIXTURES_DIR = (
    Path(__file__).parent / "fixtures" / "scroll_down_mlb" / "games"
)


def _load_fixture_payload(
    fixture_id: str,
    *,
    is_final: bool = True,
) -> dict[str, Any]:
    """Load a captured fixture and adapt it into the upstream payload shape
    that `data_source.load_game_payload` would have produced.

    The captured fixtures already use the same shape (it's the format the
    Phase 3 builder consumes), so we can hand them directly to
    `build_deck_from_upstream` for the persistence-flow tests.

    Force-overrides the lifecycle flags so the test caller controls
    final/live/pregame regardless of what the snapshot fixture stored.
    """
    with (_FIXTURES_DIR / f"{fixture_id}.json").open() as f:
        payload = json.load(f)
    payload["game"]["isFinal"] = is_final
    payload["game"]["isPregame"] = False
    payload["game"]["isLive"] = not is_final
    payload["game"]["status"] = "final" if is_final else "live"
    return payload


# ---------------------------------------------------------------------------
# get_game_deck — five branches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_game_deck_returns_none_when_game_missing() -> None:
    session = AsyncMock()
    with patch.object(service, "load_game_payload", AsyncMock(return_value=None)):
        result = await service.get_game_deck(session, "190203")
    assert result is None


@pytest.mark.asyncio
async def test_get_game_deck_returns_none_for_invalid_id() -> None:
    session = AsyncMock()
    result = await service.get_game_deck(session, "not-a-number")
    assert result is None


@pytest.mark.asyncio
async def test_get_game_deck_returns_none_for_pregame() -> None:
    session = AsyncMock()
    pregame = {
        "game": {
            "id": 190203,
            "isPregame": True,
            "isFinal": False,
            "isLive": False,
            "status": "scheduled",
        },
        "plays": [],
        "mlbPitchers": [],
    }
    with patch.object(service, "load_game_payload", AsyncMock(return_value=pregame)):
        result = await service.get_game_deck(session, "190203")
    assert result is None


@pytest.mark.asyncio
async def test_get_game_deck_serves_persisted_official_when_present() -> None:
    """A final game with a persisted official deck must be served as-is —
    the builder must not run a second time, and the wire shape comes
    straight from the stored payload."""
    session = AsyncMock()
    final_payload = _load_fixture_payload("190121")

    persisted = ScrollDownMlbDeckResponse(
        game_id="190121",
        deck_version="frozen-v1",
        generated_at=datetime.now(UTC),
        is_final=True,
        cards=[],
        planner_report=PlannerReport(),
        validation_warnings=[],
    )

    with (
        patch.object(service, "load_game_payload", AsyncMock(return_value=final_payload)),
        patch.object(persistence, "fetch_official_deck", AsyncMock(return_value=persisted)),
        patch.object(persistence, "upsert_deck", AsyncMock()) as upsert,
    ):
        result = await service.get_game_deck(session, "190121")

    assert result is not None
    assert result.deck_version == "frozen-v1"
    upsert.assert_not_awaited()  # No regeneration on a hit.


@pytest.mark.asyncio
async def test_get_game_deck_builds_and_freezes_final_without_persisted() -> None:
    """A final game with no persisted deck must build, validate, and call
    `upsert_deck`. Subsequent fetches would then hit the persisted path."""
    session = AsyncMock()
    final_payload = _load_fixture_payload("190121")

    upsert = AsyncMock()
    with (
        patch.object(service, "load_game_payload", AsyncMock(return_value=final_payload)),
        patch.object(persistence, "fetch_official_deck", AsyncMock(return_value=None)),
        patch.object(persistence, "upsert_deck", upsert),
    ):
        result = await service.get_game_deck(session, "190121")

    assert result is not None
    assert result.is_final
    assert result.deck_version.startswith("official-")
    upsert.assert_awaited_once()
    # Must commit so the freeze is durable on the same request.
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_get_game_deck_live_builds_without_persisting() -> None:
    """Live games must NOT freeze a deck. Each poll runs the builder,
    deckVersion shifts when source data shifts."""
    session = AsyncMock()
    live_payload = _load_fixture_payload("190121", is_final=False)

    upsert = AsyncMock()
    with (
        patch.object(service, "load_game_payload", AsyncMock(return_value=live_payload)),
        patch.object(persistence, "fetch_official_deck", AsyncMock(return_value=None)),
        patch.object(persistence, "upsert_deck", upsert),
    ):
        result = await service.get_game_deck(session, "190121")

    assert result is not None
    assert not result.is_final
    assert result.deck_version.startswith("live-")
    upsert.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_game_deck_live_deck_version_stable_when_source_unchanged() -> None:
    """Polling the same upstream payload twice must produce the same
    `deckVersion`. This is the load-bearing invariant for the
    'New moments available' banner."""
    session = AsyncMock()
    live_payload = _load_fixture_payload("190121")
    live_payload["game"]["isFinal"] = False
    live_payload["game"]["isLive"] = True
    live_payload["game"]["status"] = "live"

    with (
        patch.object(service, "load_game_payload", AsyncMock(return_value=live_payload)),
        patch.object(persistence, "fetch_official_deck", AsyncMock(return_value=None)),
        patch.object(persistence, "upsert_deck", AsyncMock()),
    ):
        first = await service.get_game_deck(session, "190121")
        second = await service.get_game_deck(session, "190121")

    assert first is not None and second is not None
    assert first.deck_version == second.deck_version


@pytest.mark.asyncio
async def test_get_game_deck_live_deck_version_changes_on_new_play() -> None:
    """Adding a play to the upstream payload must produce a new
    `deckVersion` so the frontend banner triggers."""
    session = AsyncMock()
    payload_a = _load_fixture_payload("190121", is_final=False)
    payload_b = _load_fixture_payload("190121", is_final=False)
    # Truncate one play in payload A so payload B has one extra.
    payload_a["plays"] = payload_a["plays"][:-1]

    with (
        patch.object(persistence, "fetch_official_deck", AsyncMock(return_value=None)),
        patch.object(persistence, "upsert_deck", AsyncMock()),
    ):
        with patch.object(service, "load_game_payload", AsyncMock(return_value=payload_a)):
            first = await service.get_game_deck(session, "190121")
        with patch.object(service, "load_game_payload", AsyncMock(return_value=payload_b)):
            second = await service.get_game_deck(session, "190121")

    assert first is not None and second is not None
    assert first.deck_version != second.deck_version


# ---------------------------------------------------------------------------
# get_recent_games — date window bounds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_recent_games_excludes_future_scheduled_games() -> None:
    """The /recent feed is a catch-up product — future-scheduled games
    must not appear. Regression test: an earlier version had only a
    lower bound (`game_date >= now - 48h`) and leaked games scheduled
    days in the future into the home grid.
    """
    captured: list[Any] = []

    async def capture_execute(stmt):
        captured.append(stmt)
        result = AsyncMock()
        result.all = MagicMock(return_value=[])
        return result

    session = AsyncMock()
    session.execute = capture_execute

    fixed_now = datetime(2026, 5, 10, 15, 0, tzinfo=UTC)
    await service.get_recent_games(session, now=fixed_now)

    assert len(captured) == 1
    sql = str(captured[0].compile(compile_kwargs={"literal_binds": True}))
    # Both the lower bound (cutoff = now - 48h) and the upper bound
    # (end_cap = now) must appear as literal datetimes in the compiled
    # SQL. The exact comparison op is rendered by SQLAlchemy/the
    # dialect, so we assert by the literal values rather than the op.
    assert "2026-05-10 15:00:00" in sql, (
        "Upper bound `game_date <= now` is missing — future games will "
        "leak into /recent"
    )
    assert "2026-05-08 15:00:00" in sql, (
        "Lower bound `game_date >= now - 48h` is missing"
    )


# ---------------------------------------------------------------------------
# get_game_reveal — fallback recap text
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_game_reveal_returns_none_for_invalid_id() -> None:
    session = AsyncMock()
    result = await service.get_game_reveal(session, "not-a-number")
    assert result is None


# ---------------------------------------------------------------------------
# Source hash invariants
# ---------------------------------------------------------------------------


def test_source_hash_stable_for_identical_payloads() -> None:
    payload = _load_fixture_payload("190121")
    h1 = _source_hash(payload)
    h2 = _source_hash(payload)
    assert h1 == h2


def test_source_hash_changes_when_play_count_changes() -> None:
    payload_a = _load_fixture_payload("190121")
    payload_b = _load_fixture_payload("190121")
    payload_b["plays"] = payload_b["plays"][:-1]
    assert _source_hash(payload_a) != _source_hash(payload_b)


def test_source_hash_changes_when_status_transitions_to_final() -> None:
    payload_a = _load_fixture_payload("190121")
    payload_a["game"]["status"] = "live"
    payload_b = _load_fixture_payload("190121")
    payload_b["game"]["status"] = "final"
    assert _source_hash(payload_a) != _source_hash(payload_b)
