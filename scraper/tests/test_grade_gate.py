"""Unit tests for the grade gate (ISSUE-053).

Coverage:
- Pass path: combined score at or above threshold → publish
- Fail path (first attempt): combined score below threshold → regen
- Fail path (second attempt): combined score below threshold → template_fallback
- Template-fallback flow: None grader result → publish (skip grading)
- Failure reasons include Tier 1 failures
- Low Tier 2 rubric dimensions included in failure reasons
"""

from __future__ import annotations

import pytest

from sports_scraper.pipeline.grade_gate import (
    GATE_THRESHOLD,
    MAX_REGEN_ATTEMPTS,
    GateDecision,
    apply_grade_gate,
)
from sports_scraper.pipeline.grader import GraderResult, TierOneResult, TierTwoResult


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_result(
    combined_score: float,
    tier1_failures: list[str] | None = None,
    tier2_rubric: dict[str, float] | None = None,
) -> GraderResult:
    """Build a minimal GraderResult with the given combined score."""
    t1 = TierOneResult(
        score=combined_score,
        failures=tier1_failures or [],
        checks={},
    )
    t2 = TierTwoResult(
        score=combined_score,
        rubric=tier2_rubric or {},
        cache_hit=False,
    ) if tier2_rubric is not None else None

    return GraderResult(
        flow_id=1,
        sport="NBA",
        tier1=t1,
        tier2=t2,
        combined_score=combined_score,
        escalated=combined_score < GATE_THRESHOLD,
    )


# ── Pass path ─────────────────────────────────────────────────────────────────


class TestGatePassPath:
    def test_score_at_threshold_publishes(self):
        result = _make_result(combined_score=GATE_THRESHOLD)
        decision = apply_grade_gate(result, regen_attempt=0)
        assert decision.action == "publish"
        assert isinstance(decision.failures, list)

    def test_score_above_threshold_publishes(self):
        result = _make_result(combined_score=GATE_THRESHOLD + 20.0)
        decision = apply_grade_gate(result, regen_attempt=0)
        assert decision.action == "publish"

    def test_score_above_threshold_second_attempt_still_publishes(self):
        """Gate still passes on a regen attempt if score is now above threshold."""
        result = _make_result(combined_score=75.0)
        decision = apply_grade_gate(result, regen_attempt=1)
        assert decision.action == "publish"

    def test_combined_score_preserved_in_decision(self):
        result = _make_result(combined_score=80.0)
        decision = apply_grade_gate(result, regen_attempt=0)
        assert decision.combined_score == 80.0


# ── Fail path: first attempt ──────────────────────────────────────────────────


class TestGateFailFirstAttempt:
    def test_score_below_threshold_triggers_regen(self):
        result = _make_result(combined_score=GATE_THRESHOLD - 1.0)
        decision = apply_grade_gate(result, regen_attempt=0)
        assert decision.action == "regen"

    def test_zero_score_triggers_regen(self):
        result = _make_result(combined_score=0.0)
        decision = apply_grade_gate(result, regen_attempt=0)
        assert decision.action == "regen"

    def test_failure_reasons_propagated_from_tier1(self):
        failures = ["block_count=1 outside [3,7]", "score_not_mentioned: expected 10-5"]
        result = _make_result(
            combined_score=30.0,
            tier1_failures=failures,
        )
        decision = apply_grade_gate(result, regen_attempt=0)
        assert decision.action == "regen"
        assert "block_count=1 outside [3,7]" in decision.failures
        assert "score_not_mentioned: expected 10-5" in decision.failures

    def test_failure_reasons_is_structured_list_not_raw_text(self):
        """Each failure reason must be a str entry, not a blob."""
        failures = ["forbidden_phrases=['as an ai']", "generic_phrase_matches=3"]
        result = _make_result(combined_score=40.0, tier1_failures=failures)
        decision = apply_grade_gate(result, regen_attempt=0)
        assert all(isinstance(r, str) for r in decision.failures)


# ── Fail path: second attempt → template_fallback ─────────────────────────────


class TestGateFailSecondAttempt:
    def test_second_fail_triggers_template_fallback(self):
        result = _make_result(combined_score=GATE_THRESHOLD - 1.0)
        decision = apply_grade_gate(result, regen_attempt=MAX_REGEN_ATTEMPTS)
        assert decision.action == "template_fallback"

    def test_high_regen_attempt_also_template_fallback(self):
        result = _make_result(combined_score=10.0)
        decision = apply_grade_gate(result, regen_attempt=5)
        assert decision.action == "template_fallback"

    def test_failure_reasons_included_on_template_fallback(self):
        failures = ["team_names_missing=['Lakers']"]
        result = _make_result(combined_score=20.0, tier1_failures=failures)
        decision = apply_grade_gate(result, regen_attempt=MAX_REGEN_ATTEMPTS)
        assert decision.action == "template_fallback"
        assert "team_names_missing=['Lakers']" in decision.failures


# ── Template-fallback flow (None result) ──────────────────────────────────────


class TestTemplateFallbackFlow:
    def test_none_result_always_publishes(self):
        """grade_flow() returns None for template flows; gate must pass them through."""
        decision = apply_grade_gate(None, regen_attempt=0)
        assert decision.action == "publish"

    def test_none_result_on_second_attempt_still_publishes(self):
        decision = apply_grade_gate(None, regen_attempt=1)
        assert decision.action == "publish"

    def test_none_result_score_is_100(self):
        decision = apply_grade_gate(None, regen_attempt=0)
        assert decision.combined_score == 100.0
        assert decision.failures == []


# ── Tier 2 rubric failures ────────────────────────────────────────────────────


class TestTier2RubricFailures:
    def test_low_rubric_dimension_added_to_failures(self):
        """A Tier 2 rubric score < 12/25 should appear in failure reasons."""
        result = _make_result(
            combined_score=35.0,
            tier2_rubric={
                "factual_accuracy": 5,
                "sport_specific_voice": 20,
                "narrative_coherence": 20,
                "no_generic_filler": 20,
            },
        )
        decision = apply_grade_gate(result, regen_attempt=0)
        assert any("tier2_factual_accuracy_low_score" in f for f in decision.failures)

    def test_passing_rubric_dimensions_not_in_failures(self):
        result = _make_result(
            combined_score=35.0,
            tier2_rubric={
                "factual_accuracy": 22,
                "sport_specific_voice": 22,
                "narrative_coherence": 22,
                "no_generic_filler": 22,
            },
        )
        decision = apply_grade_gate(result, regen_attempt=0)
        # No tier2_*_low_score entries — all dims are high
        assert not any("tier2_" in f for f in decision.failures)


# ── Custom threshold ──────────────────────────────────────────────────────────


class TestCustomThreshold:
    def test_custom_threshold_respected(self):
        result = _make_result(combined_score=70.0)
        decision = apply_grade_gate(result, regen_attempt=0, threshold=75.0)
        assert decision.action == "regen"

    def test_score_just_above_custom_threshold_publishes(self):
        result = _make_result(combined_score=75.0)
        decision = apply_grade_gate(result, regen_attempt=0, threshold=75.0)
        assert decision.action == "publish"
