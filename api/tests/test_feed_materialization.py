from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.flow import SportsGameCardFeedArtifact
from app.feed import materialization
from app.feed.materialization import (
    CARD_FEED_GENERATOR_LABEL,
    CardFeedMaterializationResult,
    CardFeedRefreshSummary,
    artifact_to_response,
)
from app.feed.schemas import CARD_FEED_CONTRACT_VERSION
from app.feed.service import get_game_card_feed
from app.routers.sports.card_feeds import refresh_recent_card_feeds


def _artifact(*, source_hash: str = "abc123") -> SportsGameCardFeedArtifact:
    return SportsGameCardFeedArtifact(
        game_id=42,
        contract_version=CARD_FEED_CONTRACT_VERSION,
        feed_key=materialization.CARD_FEED_ARTIFACT_KEY,
        generation_status="ready",
        source_hash=source_hash,
        card_count=1,
        last_play_index=7,
        game_json={"gameId": 42, "sport": "baseball", "league": "MLB"},
        sections_json=[],
        team_stats_json=[],
        player_stats_json=[],
        cards_json=[],
        validation_issues_json=[],
        generated_at=datetime(2026, 6, 1, tzinfo=UTC),
        generator_label=CARD_FEED_GENERATOR_LABEL,
    )


def _materialization_result(game_id: int) -> CardFeedMaterializationResult:
    return CardFeedMaterializationResult(
        game_id=game_id,
        contract_version=CARD_FEED_CONTRACT_VERSION,
        feed_key=materialization.CARD_FEED_ARTIFACT_KEY,
        status="ready",
        card_count=1,
        generated=True,
        source_hash=f"hash-{game_id}",
    )


def test_artifact_to_response_hydrates_current_contract() -> None:
    artifact = _artifact()

    response = artifact_to_response(artifact)

    assert response.contract_version == 2
    assert response.game.game_id == 42
    assert response.generation.status == "ready"
    assert response.generation.card_count == 1


@pytest.mark.asyncio
async def test_artifact_stale_check_uses_lightweight_source_metadata() -> None:
    artifact = _artifact()
    session = AsyncMock()
    result = MagicMock()
    result.one_or_none.return_value = (
        artifact.generated_at - timedelta(minutes=1),
        artifact.generated_at - timedelta(minutes=1),
        artifact.card_count,
        artifact.last_play_index,
    )
    session.execute.return_value = result

    is_stale = await materialization._artifact_is_stale_async(session, artifact)

    assert is_stale is False


@pytest.mark.asyncio
async def test_artifact_stale_check_detects_new_pbp() -> None:
    artifact = _artifact()
    session = AsyncMock()
    result = MagicMock()
    result.one_or_none.return_value = (
        artifact.generated_at + timedelta(minutes=1),
        artifact.generated_at,
        artifact.card_count,
        artifact.last_play_index,
    )
    session.execute.return_value = result

    is_stale = await materialization._artifact_is_stale_async(session, artifact)

    assert is_stale is True


@pytest.mark.asyncio
async def test_public_card_feed_reads_materialized_artifact_without_generating(
    monkeypatch,
) -> None:
    load_game = AsyncMock(return_value=SimpleNamespace(id=42))
    monkeypatch.setattr(materialization, "_load_game_async", load_game)
    monkeypatch.setattr(materialization, "_source_hash", lambda game: "current")
    monkeypatch.setattr(
        materialization,
        "_load_artifact_async",
        AsyncMock(return_value=_artifact(source_hash="current")),
    )
    monkeypatch.setattr(
        materialization,
        "_artifact_is_stale_async",
        AsyncMock(return_value=False),
    )
    regenerate = AsyncMock()
    monkeypatch.setattr(materialization, "_materialize_loaded_game_async", regenerate)

    response = await get_game_card_feed(
        AsyncMock(),
        42,
    )

    assert response.generation.card_count == 1
    assert response.generation.is_stale is False
    load_game.assert_awaited_once()
    regenerate.assert_not_called()


@pytest.mark.asyncio
async def test_public_card_feed_regenerates_stale_artifact(
    monkeypatch,
) -> None:
    load_game = AsyncMock(return_value=SimpleNamespace(id=42))
    monkeypatch.setattr(materialization, "_load_game_async", load_game)
    monkeypatch.setattr(materialization, "_source_hash", lambda game: "new")
    monkeypatch.setattr(
        materialization,
        "_load_artifact_async",
        AsyncMock(return_value=_artifact(source_hash="old")),
    )
    monkeypatch.setattr(
        materialization,
        "_artifact_is_stale_async",
        AsyncMock(return_value=True),
    )
    regenerate = AsyncMock(return_value=_artifact(source_hash="new"))
    monkeypatch.setattr(materialization, "_materialize_loaded_game_async", regenerate)

    response = await get_game_card_feed(
        AsyncMock(),
        42,
    )

    assert response.generation.card_count == 1
    load_game.assert_awaited_once()
    regenerate.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_or_materialize_returns_current_artifact_without_regenerating(
    monkeypatch,
) -> None:
    artifact = _artifact(source_hash="current")
    monkeypatch.setattr(
        materialization,
        "_load_game_async",
        AsyncMock(return_value=SimpleNamespace(id=42)),
    )
    monkeypatch.setattr(materialization, "_source_hash", lambda game: "current")
    monkeypatch.setattr(
        materialization,
        "_load_artifact_async",
        AsyncMock(return_value=artifact),
    )
    regenerate = AsyncMock()
    monkeypatch.setattr(materialization, "_materialize_loaded_game_async", regenerate)

    response = await materialization.get_or_materialize_card_feed(
        AsyncMock(),
        42,
    )

    assert response.generation.card_count == 1
    regenerate.assert_not_called()


@pytest.mark.asyncio
async def test_get_or_materialize_regenerates_stale_artifact(monkeypatch) -> None:
    game = SimpleNamespace(id=42)
    monkeypatch.setattr(materialization, "_load_game_async", AsyncMock(return_value=game))
    monkeypatch.setattr(materialization, "_source_hash", lambda loaded_game: "new")
    monkeypatch.setattr(
        materialization,
        "_load_artifact_async",
        AsyncMock(return_value=_artifact(source_hash="old")),
    )
    regenerate = AsyncMock(return_value=_artifact(source_hash="new"))
    monkeypatch.setattr(materialization, "_materialize_loaded_game_async", regenerate)

    response = await materialization.get_or_materialize_card_feed(
        AsyncMock(),
        42,
    )

    assert response.generation.card_count == 1
    regenerate.assert_awaited_once()


@pytest.mark.asyncio
async def test_admin_refresh_route_uses_deploy_window_aliases(monkeypatch) -> None:
    called: dict[str, object] = {}

    async def _refresh(session, **kwargs):
        called["session"] = session
        called.update(kwargs)
        return CardFeedRefreshSummary(
            scanned_games=4,
            eligible_games=4,
            generated=3,
            skipped_current=1,
            failed=0,
            errors=(),
        )

    monkeypatch.setattr(materialization, "refresh_card_feeds_for_window", _refresh)
    session = AsyncMock()

    response = await refresh_recent_card_feeds(
        lookback_hours=72,
        lookahead_hours=72,
        force=True,
        session=session,
    )

    assert response.scanned_games == 4
    assert response.generated == 3
    assert called == {
        "session": session,
        "lookback_hours": 72,
        "lookahead_hours": 72,
        "force": True,
    }


@pytest.mark.asyncio
async def test_async_refresh_rolls_back_failed_game_and_continues(monkeypatch) -> None:
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [101, 102]
    session.execute.return_value = result
    attempted: list[int] = []

    async def _materialize(session_arg, game_id: int, *, force: bool = False):
        assert session_arg is session
        assert force is True
        attempted.append(game_id)
        if game_id == 101:
            raise RuntimeError("missing feed_key")
        return _materialization_result(game_id)

    monkeypatch.setattr(materialization, "materialize_card_feed", _materialize)

    summary = await materialization.refresh_card_feeds_for_window(
        session,
        force=True,
        now=datetime(2026, 6, 3, tzinfo=UTC),
    )

    assert attempted == [101, 102]
    assert summary.generated == 1
    assert summary.failed == 1
    assert summary.errors == ("101: RuntimeError: missing feed_key",)
    session.rollback.assert_awaited_once()


def test_sync_refresh_rolls_back_failed_game_and_continues(monkeypatch) -> None:
    class _Query:
        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def all(self):
            return [(201,), (202,)]

    class _Session:
        def __init__(self) -> None:
            self.rollback_count = 0

        def query(self, *args, **kwargs):
            return _Query()

        def rollback(self) -> None:
            self.rollback_count += 1

    session = _Session()
    attempted: list[int] = []

    def _materialize(session_arg, game_id: int, *, force: bool = False):
        assert session_arg is session
        assert force is True
        attempted.append(game_id)
        if game_id == 201:
            raise RuntimeError("missing feed_key")
        return _materialization_result(game_id)

    monkeypatch.setattr(materialization, "materialize_card_feed_sync", _materialize)

    summary = materialization.materialize_recent_card_feeds_sync(
        session,
        force=True,
        now=datetime(2026, 6, 3, tzinfo=UTC),
    )

    assert attempted == [201, 202]
    assert summary.generated == 1
    assert summary.failed == 1
    assert summary.errors == ("201: RuntimeError: missing feed_key",)
    assert session.rollback_count == 1
