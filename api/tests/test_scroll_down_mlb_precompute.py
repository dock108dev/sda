"""Focused tests for the explicit Scroll Down MLB deck precompute flow."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.scroll_down_mlb import persistence
from app.scroll_down_mlb import precompute as deck_precompute
from app.scroll_down_mlb._pipeline import _source_hash
from app.scroll_down_mlb.schemas import (
    DeckGenerationStatus,
    GenerationOutcome,
    GenerationPolicy,
    TeamSummary,
    ValidationSeverity,
    ValidationWarning,
)

_FIXTURES_DIR = (
    Path(__file__).parent / "fixtures" / "scroll_down_mlb" / "games"
)


def _load_fixture_payload(
    fixture_id: str,
    *,
    is_final: bool = True,
) -> dict[str, Any]:
    with (_FIXTURES_DIR / f"{fixture_id}.json").open() as f:
        payload = json.load(f)
    payload["game"]["isFinal"] = is_final
    payload["game"]["isPregame"] = False
    payload["game"]["isLive"] = not is_final
    payload["game"]["status"] = "final" if is_final else "live"
    return payload


def _metadata(
    game_id: int = 190121,
    *,
    is_final: bool = False,
):
    return deck_precompute.GameDeckMetadata(
        game_id=game_id,
        status="final" if is_final else "live",
        is_final=is_final,
        is_pregame=False,
        home_team=TeamSummary(
            id="home",
            abbreviation="HME",
            display_name="Home",
        ),
        away_team=TeamSummary(
            id="away",
            abbreviation="AWY",
            display_name="Away",
        ),
        first_pitch=datetime.now(UTC),
        venue="Test Park",
    )


@pytest.mark.asyncio
async def test_precompute_live_deck_version_stable_when_source_unchanged() -> None:
    """Precomputing the same upstream payload twice produces one version."""
    session = AsyncMock()
    live_payload = _load_fixture_payload("190121", is_final=False)

    with (
        patch.object(
            deck_precompute,
            "load_game_deck_metadata",
            AsyncMock(return_value=_metadata(is_final=False)),
        ),
        patch.object(deck_precompute, "try_advisory_lock", AsyncMock(return_value=True)),
        patch.object(
            deck_precompute,
            "load_game_payload",
            AsyncMock(return_value=live_payload),
        ),
        patch.object(persistence, "fetch_latest_deck_row", AsyncMock(return_value=None)),
        patch.object(persistence, "upsert_deck", AsyncMock()) as upsert,
    ):
        first = await deck_precompute.precompute_game_deck(session, 190121)
        second = await deck_precompute.precompute_game_deck(session, 190121)

    assert first.deck_version == second.deck_version
    assert upsert.await_count == 2


@pytest.mark.asyncio
async def test_precompute_live_deck_version_changes_on_new_play() -> None:
    """Adding a play to the upstream payload must produce a new deckVersion."""
    session = AsyncMock()
    payload_a = _load_fixture_payload("190121", is_final=False)
    payload_b = _load_fixture_payload("190121", is_final=False)
    payload_a["plays"] = payload_a["plays"][:-1]

    with (
        patch.object(
            deck_precompute,
            "load_game_deck_metadata",
            AsyncMock(return_value=_metadata(is_final=False)),
        ),
        patch.object(deck_precompute, "try_advisory_lock", AsyncMock(return_value=True)),
        patch.object(persistence, "fetch_latest_deck_row", AsyncMock(return_value=None)),
        patch.object(persistence, "upsert_deck", AsyncMock()),
    ):
        with patch.object(
            deck_precompute,
            "load_game_payload",
            AsyncMock(return_value=payload_a),
        ):
            first = await deck_precompute.precompute_game_deck(session, 190121)
        with patch.object(
            deck_precompute,
            "load_game_payload",
            AsyncMock(return_value=payload_b),
        ):
            second = await deck_precompute.precompute_game_deck(session, 190121)

    assert first.deck_version != second.deck_version


@pytest.mark.asyncio
async def test_precompute_skips_when_lock_is_held() -> None:
    session = AsyncMock()
    with (
        patch.object(
            deck_precompute,
            "load_game_deck_metadata",
            AsyncMock(return_value=_metadata(is_final=False)),
        ),
        patch.object(deck_precompute, "try_advisory_lock", AsyncMock(return_value=False)),
        patch.object(deck_precompute, "load_game_payload", AsyncMock()) as loader,
    ):
        result = await deck_precompute.precompute_game_deck(session, 190121)

    assert result.status == "locked"
    loader.assert_not_awaited()


@pytest.mark.asyncio
async def test_precompute_skips_unchanged_source_without_force() -> None:
    session = AsyncMock()
    payload = _load_fixture_payload("190121", is_final=False)
    latest = MagicMock()
    latest.source_hash = _source_hash(payload)
    latest.deck_version = "live-existing"

    with (
        patch.object(
            deck_precompute,
            "load_game_deck_metadata",
            AsyncMock(return_value=_metadata(is_final=False)),
        ),
        patch.object(deck_precompute, "try_advisory_lock", AsyncMock(return_value=True)),
        patch.object(
            deck_precompute,
            "load_game_payload",
            AsyncMock(return_value=payload),
        ),
        patch.object(persistence, "fetch_latest_deck_row", AsyncMock(return_value=latest)),
        patch.object(deck_precompute, "build_deck_from_upstream") as builder,
        patch.object(persistence, "upsert_deck", AsyncMock()) as upsert,
    ):
        result = await deck_precompute.precompute_game_deck(session, 190121)

    assert result.status == "unchanged"
    assert result.deck_version == "live-existing"
    builder.assert_not_called()
    upsert.assert_not_awaited()


@pytest.mark.asyncio
async def test_precompute_persists_pending_fallback_without_play_by_play() -> None:
    session = AsyncMock()
    payload = _load_fixture_payload("190121", is_final=False)
    payload["plays"] = []
    upsert = AsyncMock()

    with (
        patch.object(
            deck_precompute,
            "load_game_deck_metadata",
            AsyncMock(return_value=_metadata(is_final=False)),
        ),
        patch.object(deck_precompute, "try_advisory_lock", AsyncMock(return_value=True)),
        patch.object(
            deck_precompute,
            "load_game_payload",
            AsyncMock(return_value=payload),
        ),
        patch.object(persistence, "fetch_latest_deck_row", AsyncMock(return_value=None)),
        patch.object(persistence, "upsert_deck", upsert),
    ):
        result = await deck_precompute.precompute_game_deck(session, 190121)

    assert result.status == DeckGenerationStatus.pending.value
    persisted = upsert.await_args.kwargs["deck"]
    assert persisted.generation_status is DeckGenerationStatus.pending
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_precompute_persists_degraded_fallback_on_generation_failure() -> None:
    session = AsyncMock()
    payload = _load_fixture_payload("190121", is_final=False)
    upsert = AsyncMock()

    with (
        patch.object(
            deck_precompute,
            "load_game_deck_metadata",
            AsyncMock(return_value=_metadata(is_final=False)),
        ),
        patch.object(deck_precompute, "try_advisory_lock", AsyncMock(return_value=True)),
        patch.object(
            deck_precompute,
            "load_game_payload",
            AsyncMock(return_value=payload),
        ),
        patch.object(persistence, "fetch_latest_deck_row", AsyncMock(return_value=None)),
        patch.object(
            deck_precompute,
            "build_deck_from_upstream",
            side_effect=TimeoutError,
        ),
        patch.object(persistence, "upsert_deck", upsert),
    ):
        result = await deck_precompute.precompute_game_deck(session, 190121)

    assert result.status == DeckGenerationStatus.degraded.value
    persisted = upsert.await_args.kwargs["deck"]
    assert persisted.generation_status is DeckGenerationStatus.degraded
    assert persisted.cards[0].description == "The catch-up deck is using a safe fallback."
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_precompute_persists_blocked_fallback_for_official_validation_error() -> None:
    session = AsyncMock()
    payload = _load_fixture_payload("190121", is_final=True)
    validation_error = ValidationWarning(
        code="unsafe_text",
        severity=ValidationSeverity.error,
        message="unsafe",
    )
    blocked = GenerationOutcome(
        policy=GenerationPolicy.official,
        deck=None,
        errors=[validation_error],
        blocked=True,
    )
    upsert = AsyncMock()

    with (
        patch.object(
            deck_precompute,
            "load_game_deck_metadata",
            AsyncMock(return_value=_metadata(is_final=True)),
        ),
        patch.object(deck_precompute, "try_advisory_lock", AsyncMock(return_value=True)),
        patch.object(
            deck_precompute,
            "load_game_payload",
            AsyncMock(return_value=payload),
        ),
        patch.object(persistence, "fetch_latest_deck_row", AsyncMock(return_value=None)),
        patch.object(deck_precompute, "build_deck_from_upstream", return_value=blocked),
        patch.object(persistence, "upsert_deck", upsert),
    ):
        result = await deck_precompute.precompute_game_deck(session, 190121)

    assert result.status == DeckGenerationStatus.blocked.value
    persisted = upsert.await_args.kwargs["deck"]
    assert persisted.generation_status is DeckGenerationStatus.blocked
    assert upsert.await_args.kwargs["errors"] == [validation_error]
    assert "unsafe" not in persisted.cards[0].description
    session.commit.assert_awaited()
