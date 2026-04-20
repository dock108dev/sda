"""Unit tests for pipeline OTel metrics (ISSUE-030).

Patches app.services.pipeline.metrics._instruments so opentelemetry-sdk
does not need to be installed in the test environment.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def _reset_module():
    """Clear cached instrument state so each test starts fresh."""
    import app.services.pipeline.metrics as m

    m._initialized = False
    m._stage_duration = None
    m._regen_count = None
    m._fallback_count = None
    m._published_count = None
    m._score_mismatch_count = None
    return m


def _make_mock_instruments():
    """Return (hist, regen_counter, fallback_counter, published_counter, score_mismatch_counter) mocks."""
    return MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock()


class TestRecordStageDuration:
    def test_records_with_correct_attributes(self):
        m = _reset_module()
        hist, regen, fallback, published, score_mismatch = _make_mock_instruments()
        with patch.object(m, "_instruments", return_value=(hist, regen, fallback, published, score_mismatch)):
            m.record_stage_duration("NORMALIZE_PBP", "NBA", 1234.5)
        hist.record.assert_called_once_with(
            1234.5, attributes={"stage": "NORMALIZE_PBP", "sport": "NBA"}
        )

    def test_different_stages_use_stage_attribute(self):
        m = _reset_module()
        hist, regen, fallback, published, score_mismatch = _make_mock_instruments()
        with patch.object(m, "_instruments", return_value=(hist, regen, fallback, published, score_mismatch)):
            m.record_stage_duration("ANALYZE_DRAMA", "NFL", 999.0)
        hist.record.assert_called_once_with(
            999.0, attributes={"stage": "ANALYZE_DRAMA", "sport": "NFL"}
        )


class TestIncrementRegen:
    def test_coverage_fail_reason(self):
        m = _reset_module()
        hist, regen, fallback, published, score_mismatch = _make_mock_instruments()
        with patch.object(m, "_instruments", return_value=(hist, regen, fallback, published, score_mismatch)):
            m.increment_regen("NBA", "coverage_fail")
        regen.add.assert_called_once_with(
            1, attributes={"sport": "NBA", "reason": "coverage_fail"}
        )

    def test_quality_fail_reason(self):
        m = _reset_module()
        hist, regen, fallback, published, score_mismatch = _make_mock_instruments()
        with patch.object(m, "_instruments", return_value=(hist, regen, fallback, published, score_mismatch)):
            m.increment_regen("NFL", "quality_fail")
        regen.add.assert_called_once_with(
            1, attributes={"sport": "NFL", "reason": "quality_fail"}
        )


class TestIncrementFallback:
    def test_increments_with_sport_and_reason(self):
        m = _reset_module()
        hist, regen, fallback, published, score_mismatch = _make_mock_instruments()
        with patch.object(m, "_instruments", return_value=(hist, regen, fallback, published, score_mismatch)):
            m.increment_fallback("NHL", "coverage_fail")
        fallback.add.assert_called_once_with(1, attributes={"sport": "NHL", "reason": "coverage_fail"})

    def test_default_reason_is_max_regen_exceeded(self):
        m = _reset_module()
        hist, regen, fallback, published, score_mismatch = _make_mock_instruments()
        with patch.object(m, "_instruments", return_value=(hist, regen, fallback, published, score_mismatch)):
            m.increment_fallback("NHL")
        fallback.add.assert_called_once_with(1, attributes={"sport": "NHL", "reason": "max_regen_exceeded"})


class TestIncrementPublished:
    def test_increments_with_sport(self):
        m = _reset_module()
        hist, regen, fallback, published, score_mismatch = _make_mock_instruments()
        with patch.object(m, "_instruments", return_value=(hist, regen, fallback, published, score_mismatch)):
            m.increment_published("MLB")
        published.add.assert_called_once_with(1, attributes={"sport": "MLB"})


class TestIncrementScoreMismatch:
    def test_increments_with_sport(self):
        m = _reset_module()
        hist, regen, fallback, published, score_mismatch = _make_mock_instruments()
        with patch.object(m, "_instruments", return_value=(hist, regen, fallback, published, score_mismatch)):
            m.increment_score_mismatch("NBA")
        score_mismatch.add.assert_called_once_with(1, attributes={"sport": "NBA"})


class TestNoopWhenOtelMissing:
    """When opentelemetry is not installed, _instruments must return _NOOP objects."""

    def test_noop_on_import_error(self):
        import builtins

        import app.services.pipeline.metrics as m

        m._initialized = False
        m._stage_duration = None

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "opentelemetry":
                raise ImportError("no opentelemetry")
            return real_import(name, *args, **kwargs)

        import builtins

        with patch.object(builtins, "__import__", side_effect=mock_import):
            hist, regen, fallback, published, score_mismatch = m._instruments()

        # Should not raise; all should be _NOOP
        hist.record(100.0, attributes={})
        regen.add(1, attributes={})
        fallback.add(1, attributes={})
        published.add(1, attributes={})
        score_mismatch.add(1, attributes={})


class TestValidateBlocksEmitsMetrics:
    """Integration-style check: validate_blocks.execute calls increment_regen/fallback."""

    def _blocks_failing_coverage(self):
        """Minimal structurally-valid blocks whose narratives don't mention the score."""
        from app.services.pipeline.stages.block_types import SemanticRole

        narrative = " ".join(["word"] * 40)
        return [
            {
                "block_index": 0,
                "role": SemanticRole.SETUP.value,
                "narrative": narrative,
                "score_before": [0, 0],
                "score_after": [10, 5],
                "moment_indices": [0],
                "play_ids": [1],
                "key_play_ids": [1],
                "mini_box": {
                    "cumulative": {"home": {"pts": 10}, "away": {"pts": 5}},
                    "delta": {"pts": 10},
                },
            },
            {
                "block_index": 1,
                "role": SemanticRole.RESOLUTION.value,
                "narrative": narrative,
                "score_before": [10, 5],
                "score_after": [20, 10],
                "moment_indices": [1],
                "play_ids": [2],
                "key_play_ids": [2],
                "mini_box": {
                    "cumulative": {"home": {"pts": 20}, "away": {"pts": 10}},
                    "delta": {"pts": 10},
                },
            },
        ]

    def _run(self, blocks, regen_attempt):
        import asyncio
        from unittest.mock import AsyncMock

        from app.services.pipeline.models import StageInput
        from app.services.pipeline.stages.validate_blocks import execute_validate_blocks

        session = AsyncMock()
        session.execute.return_value.scalars.return_value.all.return_value = []

        stage_input = StageInput(
            game_id=1,
            run_id=1,
            previous_output={
                "blocks_rendered": True,
                "blocks": blocks,
                "total_moments": len(blocks),
                "moments": [{"idx": i} for i in range(len(blocks))],
            },
            game_context={
                "sport": "NBA",
                "home_team": "Lakers",
                "away_team": "Celtics",
                "regen_attempt": regen_attempt,
            },
        )

        async def _inner():
            with patch(
                "app.services.pipeline.stages.validate_blocks.load_and_attach_embedded_tweets",
                new=AsyncMock(return_value=(blocks, None)),
            ):
                return await execute_validate_blocks(session, stage_input)

        return asyncio.run(_inner())

    def test_regenerate_increments_regen_counter(self):
        import app.services.pipeline.metrics as m

        _reset_module()
        hist, regen, fallback, published, score_mismatch = _make_mock_instruments()
        blocks = self._blocks_failing_coverage()

        with patch.object(m, "_instruments", return_value=(hist, regen, fallback, published, score_mismatch)):
            result = self._run(blocks, regen_attempt=0)

        # Narratives have no score mention — coverage fails → REGENERATE
        assert result.data["decision"] == "REGENERATE"
        regen.add.assert_called_once_with(
            1, attributes={"sport": "NBA", "reason": "coverage_fail"}
        )
        fallback.add.assert_not_called()

    def test_fallback_increments_fallback_counter(self):
        import app.services.pipeline.metrics as m

        _reset_module()
        hist, regen, fallback, published, score_mismatch = _make_mock_instruments()
        blocks = self._blocks_failing_coverage()

        with patch.object(m, "_instruments", return_value=(hist, regen, fallback, published, score_mismatch)):
            result = self._run(blocks, regen_attempt=2)  # >= MAX_REGEN_ATTEMPTS=2

        # FALLBACK replaces LLM blocks with template blocks → final decision is PUBLISH
        assert result.data["fallback_used"] is True
        assert result.data["decision"] == "PUBLISH"
        fallback.add.assert_called_once_with(1, attributes={"sport": "NBA", "reason": "coverage_fail"})
        regen.add.assert_not_called()

    def test_no_metric_on_publish(self):
        from app.services.pipeline.stages.block_types import SemanticRole

        import app.services.pipeline.metrics as m

        _reset_module()
        hist, regen, fallback, published, score_mismatch = _make_mock_instruments()

        # Need 3+ blocks (MIN_BLOCKS=3) with narratives that mention score/winner
        winning_narrative = "The Lakers dominated and won 30-10 over the Celtics tonight."
        blocks = [
            {
                "block_index": 0,
                "role": SemanticRole.SETUP.value,
                "narrative": winning_narrative,
                "score_before": [0, 0],
                "score_after": [10, 5],
                "moment_indices": [0],
                "play_ids": [1],
                "key_play_ids": [1],
                "mini_box": {
                    "cumulative": {"home": {"pts": 10}, "away": {"pts": 5}},
                    "delta": {"pts": 10},
                },
            },
            {
                "block_index": 1,
                "role": "DECISION_POINT",
                "narrative": winning_narrative,
                "score_before": [10, 5],
                "score_after": [20, 8],
                "moment_indices": [1],
                "play_ids": [2],
                "key_play_ids": [2],
                "mini_box": {
                    "cumulative": {"home": {"pts": 20}, "away": {"pts": 8}},
                    "delta": {"pts": 10},
                },
            },
            {
                "block_index": 2,
                "role": SemanticRole.RESOLUTION.value,
                "narrative": winning_narrative,
                "score_before": [20, 8],
                "score_after": [30, 10],
                "moment_indices": [2],
                "play_ids": [3],
                "key_play_ids": [3],
                "mini_box": {
                    "cumulative": {"home": {"pts": 30}, "away": {"pts": 10}},
                    "delta": {"pts": 10},
                },
            },
        ]

        with patch.object(m, "_instruments", return_value=(hist, regen, fallback, published, score_mismatch)):
            result = self._run(blocks, regen_attempt=0)

        assert result.data["decision"] == "PUBLISH"
        regen.add.assert_not_called()
        fallback.add.assert_not_called()
