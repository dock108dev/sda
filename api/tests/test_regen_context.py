"""Unit tests for RegenFailureContext and its integration with prompt builders.

Coverage:
- RegenFailureContext.from_failure_reasons correctly partitions tier1/tier2
- render_for_prompt includes every failure dimension — none silently dropped
- build_block_prompt injects the feedback section when regen_context provided
- build_block_prompt omits the section when regen_context is absent
- build_game_flow_pass_prompt injects the feedback section when regen_context provided
- All failure dimensions present in a realistic GraderResult appear in the prompt
"""
from __future__ import annotations

import pytest

from app.services.pipeline.stages.regen_context import RegenFailureContext, _humanize
from app.services.pipeline.stages.render_prompts import (
    build_block_prompt,
    build_game_flow_pass_prompt,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _minimal_block(idx: int = 0) -> dict:
    return {
        "block_index": idx,
        "role": "SETUP",
        "score_before": [0, 0],
        "score_after": [5, 3],
        "key_play_ids": [],
        "period_start": 1,
        "period_end": 1,
    }


def _minimal_game_context() -> dict:
    return {
        "home_team_name": "Lakers",
        "away_team_name": "Celtics",
        "home_team_abbrev": "LAL",
        "away_team_abbrev": "BOS",
        "sport": "NBA",
    }


# ── RegenFailureContext construction ─────────────────────────────────────────


class TestRegenFailureContextConstruction:
    def test_from_failure_reasons_partitions_tier1(self):
        reasons = [
            "block_count=1 outside [3,7]",
            "score_not_mentioned: expected 10-5",
        ]
        ctx = RegenFailureContext.from_failure_reasons(reasons, regen_attempt=1)
        assert len(ctx.tier1_failures) == 2
        assert ctx.tier2_rubric_failures == []

    def test_from_failure_reasons_partitions_tier2(self):
        reasons = [
            "tier2_factual_accuracy_low_score:5/25",
            "tier2_sport_specific_voice_low_score:8/25",
        ]
        ctx = RegenFailureContext.from_failure_reasons(reasons, regen_attempt=1)
        assert ctx.tier1_failures == []
        assert len(ctx.tier2_rubric_failures) == 2

    def test_from_failure_reasons_mixed_partition(self):
        reasons = [
            "forbidden_phrases=['as an ai']",
            "generic_phrase_matches=3",
            "tier2_narrative_coherence_low_score:9/25",
            "tier2_no_generic_filler_low_score:7/25",
        ]
        ctx = RegenFailureContext.from_failure_reasons(reasons, regen_attempt=1)
        assert len(ctx.tier1_failures) == 2
        assert len(ctx.tier2_rubric_failures) == 2

    def test_empty_reasons_yields_no_failures(self):
        ctx = RegenFailureContext.from_failure_reasons([], regen_attempt=1)
        assert not ctx.has_failures()

    def test_regen_attempt_preserved(self):
        ctx = RegenFailureContext.from_failure_reasons(["score_not_mentioned"], regen_attempt=2)
        assert ctx.regen_attempt == 2

    def test_all_reasons_preserved_no_drop(self):
        reasons = [
            "block_count=6 outside [3,7]",
            "team_names_missing=['Celtics']",
            "tier2_factual_accuracy_low_score:4/25",
            "tier2_narrative_coherence_low_score:10/25",
        ]
        ctx = RegenFailureContext.from_failure_reasons(reasons, regen_attempt=1)
        all_kept = ctx.tier1_failures + ctx.tier2_rubric_failures
        assert set(all_kept) == set(reasons)


# ── render_for_prompt ─────────────────────────────────────────────────────────


class TestRenderForPrompt:
    def test_empty_context_returns_empty_string(self):
        ctx = RegenFailureContext()
        assert ctx.render_for_prompt() == ""

    def test_prompt_includes_attempt_number(self):
        ctx = RegenFailureContext.from_failure_reasons(
            ["score_not_mentioned"], regen_attempt=1
        )
        rendered = ctx.render_for_prompt()
        assert "regen attempt 1" in rendered

    def test_prompt_includes_all_tier1_failures(self):
        reasons = [
            "block_count=1 outside [3,7]",
            "forbidden_phrases=['as an ai']",
            "team_names_missing=['Lakers']",
        ]
        ctx = RegenFailureContext.from_failure_reasons(reasons, regen_attempt=1)
        rendered = ctx.render_for_prompt()
        # Each failure must surface as its humanized label (raw key is mapped)
        for r in reasons:
            humanized = _humanize(r)
            assert humanized in rendered, (
                f"Failure '{r}' (humanized: '{humanized}') missing from rendered prompt"
            )

    def test_prompt_includes_all_tier2_failures(self):
        reasons = [
            "tier2_factual_accuracy_low_score:5/25",
            "tier2_sport_specific_voice_low_score:8/25",
            "tier2_narrative_coherence_low_score:9/25",
            "tier2_no_generic_filler_low_score:7/25",
        ]
        ctx = RegenFailureContext.from_failure_reasons(reasons, regen_attempt=1)
        rendered = ctx.render_for_prompt()
        for r in reasons:
            humanized = _humanize(r)
            assert humanized in rendered, (
                f"Tier2 dimension '{r}' (humanized: '{humanized}') missing from rendered prompt"
            )

    def test_prompt_includes_all_mixed_failure_dimensions(self):
        """All failure dimensions from a realistic gate decision must surface."""
        reasons = [
            "block_count=1 outside [3,7]",
            "score_not_mentioned: expected 110-105",
            "tier2_factual_accuracy_low_score:5/25",
            "tier2_no_generic_filler_low_score:7/25",
        ]
        ctx = RegenFailureContext.from_failure_reasons(reasons, regen_attempt=1)
        rendered = ctx.render_for_prompt()
        for r in reasons:
            humanized = _humanize(r)
            assert humanized in rendered, (
                f"Dimension '{r}' (humanized: '{humanized}') missing from rendered prompt"
            )

    def test_prompt_has_actionable_instruction(self):
        ctx = RegenFailureContext.from_failure_reasons(["score_not_mentioned"], regen_attempt=1)
        rendered = ctx.render_for_prompt()
        assert "Do not repeat" in rendered


# ── _humanize ─────────────────────────────────────────────────────────────────


class TestHumanize:
    def test_known_key_returns_label(self):
        result = _humanize("block_count=1 outside [3,7]")
        assert "block count outside required range" in result

    def test_detail_appended_to_label(self):
        result = _humanize("score_not_mentioned: expected 10-5")
        assert "10-5" in result

    def test_tier2_key_returns_label(self):
        result = _humanize("tier2_factual_accuracy_low_score:5/25")
        assert "factual accuracy" in result
        assert "5/25" in result

    def test_unknown_key_returned_as_is(self):
        raw = "some_unknown_failure_dimension"
        assert _humanize(raw) == raw


# ── build_block_prompt integration ───────────────────────────────────────────


class TestBuildBlockPromptRegenInjection:
    def _make_blocks(self) -> list[dict]:
        return [_minimal_block(0), _minimal_block(1)]

    def test_no_regen_context_omits_feedback_section(self):
        prompt = build_block_prompt(
            self._make_blocks(), _minimal_game_context(), [], regen_context=None
        )
        assert "QUALITY FEEDBACK" not in prompt
        assert "regen attempt" not in prompt

    def test_with_regen_context_includes_feedback_header(self):
        ctx = RegenFailureContext.from_failure_reasons(
            ["score_not_mentioned"], regen_attempt=1
        )
        prompt = build_block_prompt(
            self._make_blocks(), _minimal_game_context(), [], regen_context=ctx
        )
        assert "QUALITY FEEDBACK" in prompt

    def test_all_failure_dims_present_in_prompt(self):
        reasons = [
            "block_count=1 outside [3,7]",
            "forbidden_phrases=['as an ai']",
            "tier2_factual_accuracy_low_score:5/25",
            "tier2_narrative_coherence_low_score:9/25",
        ]
        ctx = RegenFailureContext.from_failure_reasons(reasons, regen_attempt=1)
        prompt = build_block_prompt(
            self._make_blocks(), _minimal_game_context(), [], regen_context=ctx
        )
        for r in reasons:
            humanized = _humanize(r)
            assert humanized in prompt, (
                f"Dimension '{r}' (humanized: '{humanized}') missing from block prompt"
            )

    def test_regen_context_does_not_modify_identity_layer(self):
        """Static narrative instructions must be present regardless of regen context."""
        reasons = ["score_not_mentioned"]
        ctx = RegenFailureContext.from_failure_reasons(reasons, regen_attempt=1)
        prompt = build_block_prompt(
            self._make_blocks(), _minimal_game_context(), [], regen_context=ctx
        )
        # Identity layer markers must still be present
        assert "NARRATIVE STRUCTURE" in prompt
        assert "FORBIDDEN WORDS" in prompt
        assert "PLAYER NAMES" in prompt

    def test_empty_regen_context_omits_feedback_section(self):
        ctx = RegenFailureContext(tier1_failures=[], tier2_rubric_failures=[], regen_attempt=1)
        prompt = build_block_prompt(
            self._make_blocks(), _minimal_game_context(), [], regen_context=ctx
        )
        assert "QUALITY FEEDBACK" not in prompt


# ── build_game_flow_pass_prompt integration ───────────────────────────────────


class TestBuildGameFlowPassPromptRegenInjection:
    def _make_blocks_with_narratives(self) -> list[dict]:
        return [
            {**_minimal_block(0), "narrative": "The game opened with both teams trading baskets."},
            {**_minimal_block(1), "narrative": "The Celtics took a slight lead midway."},
        ]

    def test_no_regen_context_omits_feedback_section(self):
        prompt = build_game_flow_pass_prompt(
            self._make_blocks_with_narratives(), _minimal_game_context(), regen_context=None
        )
        assert "QUALITY FEEDBACK" not in prompt

    def test_with_regen_context_includes_feedback_header(self):
        ctx = RegenFailureContext.from_failure_reasons(
            ["tier2_narrative_coherence_low_score:9/25"], regen_attempt=1
        )
        prompt = build_game_flow_pass_prompt(
            self._make_blocks_with_narratives(), _minimal_game_context(), regen_context=ctx
        )
        assert "QUALITY FEEDBACK" in prompt

    def test_all_failure_dims_present_in_flow_pass_prompt(self):
        reasons = [
            "score_not_mentioned: expected 110-105",
            "tier2_sport_specific_voice_low_score:8/25",
        ]
        ctx = RegenFailureContext.from_failure_reasons(reasons, regen_attempt=1)
        prompt = build_game_flow_pass_prompt(
            self._make_blocks_with_narratives(), _minimal_game_context(), regen_context=ctx
        )
        for r in reasons:
            humanized = _humanize(r)
            assert humanized in prompt, (
                f"Dimension '{r}' (humanized: '{humanized}') missing from flow pass prompt"
            )
