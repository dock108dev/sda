"""Tests for the GENERATE_SUMMARY stage (v3-summary pipeline)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest


def _events():
    return [
        {"play_index": 1, "quarter": 1, "home_score": 2, "away_score": 0, "play_type": "score", "description": "Opener"},
        {"play_index": 2, "quarter": 1, "home_score": 2, "away_score": 3, "play_type": "score", "description": "Three"},
        {"play_index": 3, "quarter": 2, "home_score": 50, "away_score": 48, "play_type": "score", "description": "Mid-game"},
        {"play_index": 4, "quarter": 4, "home_score": 110, "away_score": 109, "play_type": "score", "description": "Game winner"},
    ]


class TestExecuteGenerateSummary:
    @pytest.mark.asyncio
    async def test_missing_pbp_events_raises(self):
        from app.services.pipeline.models import StageInput
        from app.services.pipeline.stages.generate_summary import (
            execute_generate_summary,
        )

        stage_input = StageInput(
            game_id=1,
            run_id=1,
            previous_output={"archetype": "blowout"},
            game_context={"sport": "NBA"},
        )
        with pytest.raises(ValueError, match="requires pbp_events"):
            await execute_generate_summary(stage_input)

    @pytest.mark.asyncio
    async def test_happy_path_with_mocked_openai(self, monkeypatch):
        from app.services.pipeline.models import StageInput
        from app.services.pipeline.stages import generate_summary

        # Stub OpenAI client returning a valid 3-paragraph JSON response.
        def fake_client():
            client = MagicMock()
            client.model = "gpt-4o-mini"
            response_body = {
                "summary": [
                    "Para one.",
                    "Para two with a turning point.",
                    "Final: Home 110, Away 109.",
                ],
                "referenced_play_ids": [4],
            }
            client.generate.return_value = json.dumps(response_body)
            return client

        monkeypatch.setattr(generate_summary, "get_openai_client", fake_client)

        stage_input = StageInput(
            game_id=42,
            run_id=7,
            previous_output={
                "archetype": "late_separation",
                "pbp_events": _events(),
            },
            game_context={
                "sport": "NBA",
                "home_team_name": "Home",
                "away_team_name": "Away",
                "home_team_abbrev": "HOM",
                "away_team_abbrev": "AWY",
            },
        )
        result = await generate_summary.execute_generate_summary(stage_input)

        data = result.data
        assert data["summary_generated"] is True
        assert len(data["summary"]) == 3
        assert data["referenced_play_ids"] == [4]
        assert data["openai_calls"] == 1
        assert data["home_final"] == 110
        assert data["away_final"] == 109
        # archetype passed through for FINALIZE_SUMMARY
        assert data["archetype"] == "late_separation"

    @pytest.mark.asyncio
    async def test_referenced_ids_constrained_to_offered_plays(self, monkeypatch):
        from app.services.pipeline.models import StageInput
        from app.services.pipeline.stages import generate_summary

        def fake_client():
            client = MagicMock()
            client.model = "gpt-4o-mini"
            # Model "hallucinates" id 999 plus a real id; only the real one survives.
            client.generate.return_value = json.dumps(
                {
                    "summary": ["a", "b", "c"],
                    "referenced_play_ids": [4, 999],
                }
            )
            return client

        monkeypatch.setattr(generate_summary, "get_openai_client", fake_client)

        stage_input = StageInput(
            game_id=1,
            run_id=1,
            previous_output={
                "archetype": "blowout",
                "pbp_events": _events(),
            },
            game_context={
                "sport": "NBA",
                "home_team_name": "Home",
                "away_team_name": "Away",
                "home_team_abbrev": "HOM",
                "away_team_abbrev": "AWY",
            },
        )
        result = await generate_summary.execute_generate_summary(stage_input)
        assert 999 not in result.data["referenced_play_ids"]
        assert 4 in result.data["referenced_play_ids"]

    @pytest.mark.asyncio
    async def test_missing_openai_client_raises(self, monkeypatch):
        from app.services.pipeline.models import StageInput
        from app.services.pipeline.stages import generate_summary

        monkeypatch.setattr(generate_summary, "get_openai_client", lambda: None)
        stage_input = StageInput(
            game_id=1,
            run_id=1,
            previous_output={"archetype": "blowout", "pbp_events": _events()},
            game_context={"sport": "NBA"},
        )
        with pytest.raises(RuntimeError, match="OpenAI client unavailable"):
            await generate_summary.execute_generate_summary(stage_input)
