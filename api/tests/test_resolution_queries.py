"""Tests for services/resolution_queries.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.resolution_queries import (
    get_resolution_summary_for_game,
    get_resolution_summary_for_run,
)


def _make_record(entity_type, status, **kwargs):
    r = MagicMock()
    r.entity_type = entity_type
    r.resolution_status = status
    r.source_identifier = kwargs.get("source", "TestTeam")
    r.failure_reason = kwargs.get("reason")
    r.candidates = kwargs.get("candidates", [])
    r.resolved_name = kwargs.get("resolved_name", "Resolved")
    r.resolved_id = kwargs.get("resolved_id", 1)
    r.resolution_method = kwargs.get("method", "exact")
    r.occurrence_count = kwargs.get("occurrences", 1)
    return r


class TestGetResolutionSummaryForGame:
    @pytest.mark.asyncio
    async def test_empty_records(self):
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(return_value=mock_result)
        result = await get_resolution_summary_for_game(session, 42)
        assert result.game_id == 42
        assert result.teams_total == 0

    @pytest.mark.asyncio
    async def test_team_success(self):
        session = AsyncMock()
        records = [_make_record("team", "success")]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = records
        session.execute = AsyncMock(return_value=mock_result)
        result = await get_resolution_summary_for_game(session, 42)
        assert result.teams_total == 1
        assert result.teams_resolved == 1

    @pytest.mark.asyncio
    async def test_team_failed(self):
        session = AsyncMock()
        records = [_make_record("team", "failed", reason="not found")]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = records
        session.execute = AsyncMock(return_value=mock_result)
        result = await get_resolution_summary_for_game(session, 42)
        assert result.teams_failed == 1
        assert len(result.unresolved_teams) == 1

    @pytest.mark.asyncio
    async def test_team_ambiguous(self):
        session = AsyncMock()
        records = [_make_record("team", "ambiguous", candidates=["A", "B"])]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = records
        session.execute = AsyncMock(return_value=mock_result)
        result = await get_resolution_summary_for_game(session, 42)
        assert result.teams_ambiguous == 1
        assert len(result.ambiguous_teams) == 1

    @pytest.mark.asyncio
    async def test_player_success(self):
        session = AsyncMock()
        records = [_make_record("player", "success")]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = records
        session.execute = AsyncMock(return_value=mock_result)
        result = await get_resolution_summary_for_game(session, 42)
        assert result.players_total == 1
        assert result.players_resolved == 1

    @pytest.mark.asyncio
    async def test_player_failed(self):
        session = AsyncMock()
        records = [_make_record("player", "failed", reason="unknown")]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = records
        session.execute = AsyncMock(return_value=mock_result)
        result = await get_resolution_summary_for_game(session, 42)
        assert result.players_failed == 1
        assert len(result.unresolved_players) == 1

    @pytest.mark.asyncio
    async def test_mixed_records(self):
        session = AsyncMock()
        records = [
            _make_record("team", "success"),
            _make_record("team", "failed", reason="not found"),
            _make_record("player", "success"),
            _make_record("player", "failed", reason="ambiguous"),
        ]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = records
        session.execute = AsyncMock(return_value=mock_result)
        result = await get_resolution_summary_for_game(session, 42)
        assert result.teams_total == 2
        assert result.players_total == 2


class TestGetResolutionSummaryForRun:
    @pytest.mark.asyncio
    async def test_run_not_found(self):
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)
        result = await get_resolution_summary_for_run(session, 99)
        assert result is None

    @pytest.mark.asyncio
    async def test_run_found_with_records(self):
        session = AsyncMock()
        mock_run = MagicMock()
        mock_run.game_id = 42

        records = [
            _make_record("team", "success"),
            _make_record("team", "failed", reason="no match"),
            _make_record("team", "ambiguous", candidates=["X"]),
            _make_record("player", "success"),
            _make_record("player", "failed"),
        ]

        # First execute: get run
        # Second execute: get records
        call_count = [0]
        def side_effect(stmt):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                result.scalar_one_or_none.return_value = mock_run
            else:
                result.scalars.return_value.all.return_value = records
            return result

        session.execute = AsyncMock(side_effect=side_effect)

        result = await get_resolution_summary_for_run(session, 1)
        assert result is not None
        assert result.game_id == 42
        assert result.pipeline_run_id == 1
        assert result.teams_total == 3
        assert result.teams_resolved == 1
        assert result.teams_failed == 1
        assert result.teams_ambiguous == 1
        assert result.players_total == 2
