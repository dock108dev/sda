"""Tests for ANALYZE_DRAMA stage (deterministic drama-weighting variant)."""

from __future__ import annotations

import pytest

from app.services.pipeline.models import StageInput
from app.services.pipeline.stages.analyze_drama import (
    DEFAULT_QUARTER_WEIGHTS,
    _extract_quarter_summary,
    compute_drama_weights,
    execute_analyze_drama,
)


class TestExtractQuarterSummary:
    """Tests for _extract_quarter_summary function."""

    def test_four_quarter_game_with_lead_changes(self) -> None:
        moments = [
            {"period": 1, "score_before": [0, 0], "score_after": [10, 8]},
            {"period": 1, "score_before": [10, 8], "score_after": [15, 20]},
            {"period": 2, "score_before": [15, 20], "score_after": [25, 28]},
            {"period": 2, "score_before": [25, 28], "score_after": [35, 30]},
            {"period": 3, "score_before": [35, 30], "score_after": [50, 45]},
            {"period": 4, "score_before": [50, 45], "score_after": [60, 55]},
        ]

        summary = _extract_quarter_summary(moments)

        assert {"Q1", "Q2", "Q3", "Q4"} <= set(summary.keys())
        assert summary["Q1"]["moment_count"] == 2
        assert summary["Q1"]["lead_changes"] == 1

    def test_overtime_game_creates_ot_keys(self) -> None:
        moments = [
            {"period": 1, "score_before": [0, 0], "score_after": [25, 25]},
            {"period": 5, "score_before": [100, 100], "score_after": [105, 102]},
            {"period": 6, "score_before": [105, 102], "score_after": [110, 110]},
        ]
        summary = _extract_quarter_summary(moments)
        assert "OT1" in summary
        assert "OT2" in summary

    def test_empty_moments_returns_empty(self) -> None:
        assert _extract_quarter_summary([]) == {}

    def test_point_swing_calculated(self) -> None:
        moments = [
            {"period": 1, "score_before": [0, 0], "score_after": [20, 10]},
            {"period": 1, "score_before": [20, 10], "score_after": [25, 30]},
        ]
        summary = _extract_quarter_summary(moments)
        # Start margin 0, end margin -5, swing = 5
        assert summary["Q1"]["point_swing"] == 5

    def test_peak_margin_tracked_within_quarter(self) -> None:
        moments = [
            {"period": 1, "score_before": [0, 0], "score_after": [22, 0]},
            {"period": 1, "score_before": [22, 0], "score_after": [25, 18]},
        ]
        summary = _extract_quarter_summary(moments)
        assert summary["Q1"]["peak_margin"] == 22
        assert summary["Q1"]["peak_leader"] == 1


class TestComputeDramaWeights:
    """Tests for compute_drama_weights pure function."""

    def _summary(self, quarters: list[str], lead_changes: int = 0, swing: int = 0) -> dict:
        return {
            q: {
                "moment_count": 5,
                "lead_changes": lead_changes,
                "point_swing": swing,
                "peak_margin": 0,
                "peak_leader": 0,
                "score_start": [0, 0],
                "score_end": [0, 0],
            }
            for q in quarters
        }

    def test_empty_summary_returns_default(self) -> None:
        assert compute_drama_weights("comeback", {}, "NBA") == DEFAULT_QUARTER_WEIGHTS

    def test_wire_to_wire_amplifies_opening(self) -> None:
        summary = self._summary(["Q1", "Q2", "Q3", "Q4"])
        weights = compute_drama_weights("wire_to_wire", summary, "NBA")
        assert weights["Q1"] > weights["Q2"]
        assert weights["Q1"] > weights["Q4"]
        # Late + middle suppressed for wire-to-wire
        assert weights["Q4"] < 1.0

    def test_comeback_amplifies_turning_period(self) -> None:
        summary = self._summary(["Q1", "Q2", "Q3", "Q4"])
        # Q3 has the largest swing — should be the peak
        summary["Q3"]["point_swing"] = 18
        summary["Q3"]["lead_changes"] = 2
        weights = compute_drama_weights("comeback", summary, "NBA")
        assert weights["Q3"] == max(weights.values())
        assert weights["Q3"] >= 2.0
        # Q1 suppressed when it isn't the turning period
        assert weights["Q1"] < 1.0

    def test_back_and_forth_even_weights(self) -> None:
        summary = self._summary(["Q1", "Q2", "Q3", "Q4"])
        weights = compute_drama_weights("back_and_forth", summary, "NBA")
        assert len(set(weights.values())) == 1

    def test_blowout_compresses_late(self) -> None:
        summary = self._summary(["Q1", "Q2", "Q3", "Q4"])
        weights = compute_drama_weights("blowout", summary, "NBA")
        # Q2 is the decisive period, Q3+Q4 compressed
        assert weights["Q2"] >= weights["Q1"]
        assert weights["Q3"] < weights["Q2"]
        assert weights["Q4"] < weights["Q2"]

    def test_early_avalanche_blowout_uses_blowout_shape(self) -> None:
        summary = self._summary(["Q1", "Q2", "Q3", "Q4"])
        baseline = compute_drama_weights("blowout", summary, "MLB")
        avalanche = compute_drama_weights("early_avalanche_blowout", summary, "MLB")
        assert avalanche == baseline

    def test_low_event_even_weights(self) -> None:
        summary = self._summary(["Q1", "Q2", "Q3"])
        weights = compute_drama_weights("low_event", summary, "NHL")
        assert all(w == 1.0 for w in weights.values())

    def test_fake_close_amplifies_final(self) -> None:
        summary = self._summary(["Q1", "Q2", "Q3", "Q4"])
        weights = compute_drama_weights("fake_close", summary, "NBA")
        assert weights["Q4"] > weights["Q1"]
        assert weights["Q4"] >= 1.5

    def test_late_separation_amplifies_final(self) -> None:
        summary = self._summary(["Q1", "Q2", "Q3", "Q4"])
        weights = compute_drama_weights("late_separation", summary, "NBA")
        assert weights["Q4"] > weights["Q1"]

    def test_unknown_archetype_uses_default_late_bump(self) -> None:
        summary = self._summary(["Q1", "Q2", "Q3", "Q4"])
        weights = compute_drama_weights(None, summary, "NBA")
        assert weights["Q4"] > weights["Q1"]

    def test_weights_clamped_to_valid_range(self) -> None:
        summary = self._summary(["Q1", "Q2", "Q3", "Q4"])
        for archetype in [
            "comeback",
            "wire_to_wire",
            "blowout",
            "fake_close",
            "late_separation",
            "back_and_forth",
            "low_event",
            None,
        ]:
            weights = compute_drama_weights(archetype, summary, "NBA")
            for w in weights.values():
                assert 0.5 <= w <= 2.5

    def test_pure_function_deterministic(self) -> None:
        summary = self._summary(["Q1", "Q2", "Q3", "Q4"], lead_changes=2, swing=15)
        first = compute_drama_weights("comeback", summary, "NBA")
        second = compute_drama_weights("comeback", summary, "NBA")
        assert first == second


class TestExecuteAnalyzeDrama:
    """Tests for execute_analyze_drama async function."""

    @pytest.mark.asyncio
    async def test_missing_previous_output_raises(self) -> None:
        stage_input = StageInput(
            game_id=1,
            run_id=1,
            previous_output=None,
            game_context={"home_team": "Lakers", "away_team": "Celtics"},
        )
        with pytest.raises(ValueError, match="requires CLASSIFY_GAME_SHAPE output"):
            await execute_analyze_drama(stage_input)

    @pytest.mark.asyncio
    async def test_validation_failed_raises(self) -> None:
        stage_input = StageInput(
            game_id=1,
            run_id=1,
            previous_output={"validated": False, "moments": [], "archetype": "blowout"},
            game_context={"home_team": "Lakers", "away_team": "Celtics"},
        )
        with pytest.raises(ValueError, match="requires validated moments"):
            await execute_analyze_drama(stage_input)

    @pytest.mark.asyncio
    async def test_empty_moments_returns_defaults(self) -> None:
        stage_input = StageInput(
            game_id=1,
            run_id=1,
            previous_output={
                "validated": True,
                "moments": [],
                "pbp_events": [],
                "errors": [],
                "archetype": "wire_to_wire",
            },
            game_context={"home_team": "Lakers", "away_team": "Celtics"},
        )
        result = await execute_analyze_drama(stage_input)
        assert result.data["drama_analyzed"] is False
        assert result.data["quarter_weights"] == DEFAULT_QUARTER_WEIGHTS

    @pytest.mark.asyncio
    async def test_archetype_drives_weights(self) -> None:
        moments = [
            {"period": 1, "score_before": [0, 0], "score_after": [10, 8]},
            {"period": 2, "score_before": [10, 8], "score_after": [25, 22]},
            {"period": 3, "score_before": [25, 22], "score_after": [50, 32]},
            {"period": 4, "score_before": [50, 32], "score_after": [80, 50]},
        ]
        stage_input = StageInput(
            game_id=1,
            run_id=1,
            previous_output={
                "validated": True,
                "moments": moments,
                "pbp_events": [],
                "errors": [],
                "archetype": "blowout",
            },
            game_context={"sport": "NBA"},
        )
        result = await execute_analyze_drama(stage_input)
        weights = result.data["quarter_weights"]
        # Blowout shape compresses Q3/Q4 below the decisive Q2
        assert weights["Q2"] >= weights["Q1"]
        assert weights["Q3"] < weights["Q2"]

    @pytest.mark.asyncio
    async def test_no_llm_dependency(self) -> None:
        """Stage executes deterministically without any OpenAI client."""
        moments = [
            {"period": 1, "score_before": [0, 0], "score_after": [10, 8]},
            {"period": 4, "score_before": [90, 85], "score_after": [100, 95]},
        ]
        stage_input = StageInput(
            game_id=1,
            run_id=1,
            previous_output={
                "validated": True,
                "moments": moments,
                "pbp_events": [],
                "errors": [],
                "archetype": "wire_to_wire",
            },
            game_context={"sport": "NBA"},
        )
        # No OpenAI patching — the call must succeed without one.
        result = await execute_analyze_drama(stage_input)
        assert result.data["drama_analyzed"] is True
        assert "headline" not in result.data
        assert "story_type" not in result.data

    @pytest.mark.asyncio
    async def test_passthrough_data_preserved(self) -> None:
        moments = [{"period": 1, "score_before": [0, 0], "score_after": [10, 8]}]
        pbp_events = [{"play_index": 1, "description": "Test play"}]
        errors = ["Some error from previous stage"]

        stage_input = StageInput(
            game_id=1,
            run_id=1,
            previous_output={
                "validated": True,
                "moments": moments,
                "pbp_events": pbp_events,
                "errors": errors,
                "archetype": "back_and_forth",
            },
            game_context={"sport": "NBA"},
        )
        result = await execute_analyze_drama(stage_input)
        assert result.data["moments"] == moments
        assert result.data["pbp_events"] == pbp_events
        assert result.data["errors"] == errors
        assert result.data["validated"] is True
        assert result.data["archetype"] == "back_and_forth"

    @pytest.mark.asyncio
    async def test_peak_quarter_matches_max_weight(self) -> None:
        moments = [
            {"period": 1, "score_before": [0, 0], "score_after": [10, 8]},
            {"period": 2, "score_before": [10, 8], "score_after": [25, 22]},
            {"period": 3, "score_before": [25, 22], "score_after": [50, 45]},
            {"period": 4, "score_before": [50, 45], "score_after": [70, 65]},
        ]
        stage_input = StageInput(
            game_id=1,
            run_id=1,
            previous_output={
                "validated": True,
                "moments": moments,
                "pbp_events": [],
                "errors": [],
                "archetype": "fake_close",
            },
            game_context={"sport": "NBA"},
        )
        result = await execute_analyze_drama(stage_input)
        weights = result.data["quarter_weights"]
        peak_q = result.data["peak_quarter"]
        assert weights[peak_q] == max(weights.values())
