"""Tests for the consolidated summary prompt builder (v3-summary)."""

from __future__ import annotations

import json

import pytest


def _key_plays():
    return [
        {
            "play_index": 1,
            "quarter": 1,
            "game_clock": "10:00",
            "description": "Opening jumper",
            "home_score": 2,
            "away_score": 0,
        },
        {
            "play_index": 12,
            "quarter": 4,
            "game_clock": "0:30",
            "description": "Go-ahead three",
            "home_score": 110,
            "away_score": 109,
        },
    ]


class TestBuildSummaryPrompt:
    def test_includes_required_facts(self):
        from app.services.pipeline.stages.summary_prompt import build_summary_prompt

        prompt = build_summary_prompt(
            league_code="NBA",
            home_team="Los Angeles Lakers",
            away_team="Denver Nuggets",
            home_abbrev="LAL",
            away_abbrev="DEN",
            home_final=110,
            away_final=109,
            archetype="late_separation",
            key_plays=_key_plays(),
        )
        assert "Lakers" in prompt
        assert "Nuggets" in prompt
        assert "110" in prompt
        assert "109" in prompt
        assert "late_separation" in prompt
        # The play descriptions are rendered, not the raw play ids only.
        assert "Opening jumper" in prompt
        assert "Go-ahead three" in prompt

    def test_period_noun_varies_by_league(self):
        from app.services.pipeline.stages.summary_prompt import build_summary_prompt

        nba_prompt = build_summary_prompt(
            league_code="NBA",
            home_team="A",
            away_team="B",
            home_abbrev="A",
            away_abbrev="B",
            home_final=100,
            away_final=99,
            archetype=None,
            key_plays=_key_plays(),
        )
        mlb_prompt = build_summary_prompt(
            league_code="MLB",
            home_team="A",
            away_team="B",
            home_abbrev="A",
            away_abbrev="B",
            home_final=5,
            away_final=4,
            archetype=None,
            key_plays=[
                {
                    "play_index": 1,
                    "quarter": 1,
                    "description": "Solo HR",
                    "home_score": 1,
                    "away_score": 0,
                }
            ],
        )
        assert "quarter" in nba_prompt
        assert "inning" in mlb_prompt

    def test_unknown_archetype_falls_through(self):
        from app.services.pipeline.stages.summary_prompt import build_summary_prompt

        prompt = build_summary_prompt(
            league_code="NBA",
            home_team="A",
            away_team="B",
            home_abbrev="A",
            away_abbrev="B",
            home_final=100,
            away_final=99,
            archetype="unknown_label",
            key_plays=_key_plays(),
        )
        assert "No specific archetype hint" in prompt


class TestParseSummaryResponse:
    def test_valid_response(self):
        from app.services.pipeline.stages.summary_prompt import parse_summary_response

        body = {
            "summary": ["First paragraph.", "Second paragraph.", "Third paragraph."],
            "referenced_play_ids": [1, 12],
        }
        parsed = parse_summary_response(json.dumps(body))
        assert parsed["summary"] == body["summary"]
        assert parsed["referenced_play_ids"] == [1, 12]

    def test_too_few_paragraphs_rejected(self):
        from app.services.pipeline.stages.summary_prompt import parse_summary_response

        body = {"summary": ["only one"], "referenced_play_ids": []}
        with pytest.raises(ValueError, match="3-5 paragraphs"):
            parse_summary_response(json.dumps(body))

    def test_too_many_paragraphs_rejected(self):
        from app.services.pipeline.stages.summary_prompt import parse_summary_response

        body = {
            "summary": ["a", "b", "c", "d", "e", "f"],
            "referenced_play_ids": [],
        }
        with pytest.raises(ValueError, match="3-5 paragraphs"):
            parse_summary_response(json.dumps(body))

    def test_non_string_paragraphs_rejected(self):
        from app.services.pipeline.stages.summary_prompt import parse_summary_response

        body = {"summary": ["a", 2, "c"], "referenced_play_ids": []}
        with pytest.raises(ValueError, match="non-empty strings"):
            parse_summary_response(json.dumps(body))

    def test_referenced_ids_default_empty(self):
        from app.services.pipeline.stages.summary_prompt import parse_summary_response

        body = {"summary": ["a", "b", "c"]}
        parsed = parse_summary_response(json.dumps(body))
        assert parsed["referenced_play_ids"] == []

    def test_invalid_referenced_ids_silently_dropped(self):
        from app.services.pipeline.stages.summary_prompt import parse_summary_response

        body = {
            "summary": ["a", "b", "c"],
            "referenced_play_ids": [1, "garbage", 3, None],
        }
        parsed = parse_summary_response(json.dumps(body))
        assert parsed["referenced_play_ids"] == [1, 3]
