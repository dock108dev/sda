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
    m._published_count = None
    m._score_mismatch_count = None
    return m


def _make_mock_instruments():
    """Return (hist, published_counter, score_mismatch_counter) mocks."""
    return MagicMock(), MagicMock(), MagicMock()


class TestRecordStageDuration:
    def test_records_with_correct_attributes(self):
        m = _reset_module()
        hist, published, score_mismatch = _make_mock_instruments()
        with patch.object(m, "_instruments", return_value=(hist, published, score_mismatch)):
            m.record_stage_duration("NORMALIZE_PBP", "NBA", 1234.5)
        hist.record.assert_called_once_with(
            1234.5, attributes={"stage": "NORMALIZE_PBP", "sport": "NBA"}
        )

    def test_different_stages_use_stage_attribute(self):
        m = _reset_module()
        hist, published, score_mismatch = _make_mock_instruments()
        with patch.object(m, "_instruments", return_value=(hist, published, score_mismatch)):
            m.record_stage_duration("GENERATE_SUMMARY", "NFL", 999.0)
        hist.record.assert_called_once_with(
            999.0, attributes={"stage": "GENERATE_SUMMARY", "sport": "NFL"}
        )


class TestIncrementPublished:
    def test_increments_with_sport(self):
        m = _reset_module()
        hist, published, score_mismatch = _make_mock_instruments()
        with patch.object(m, "_instruments", return_value=(hist, published, score_mismatch)):
            m.increment_published("MLB")
        published.add.assert_called_once_with(1, attributes={"sport": "MLB"})


class TestIncrementScoreMismatch:
    def test_increments_with_sport(self):
        m = _reset_module()
        hist, published, score_mismatch = _make_mock_instruments()
        with patch.object(m, "_instruments", return_value=(hist, published, score_mismatch)):
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

        with patch.object(builtins, "__import__", side_effect=mock_import):
            hist, published, score_mismatch = m._instruments()

        # Should not raise; all should be _NOOP
        hist.record(100.0, attributes={})
        published.add(1, attributes={})
        score_mismatch.add(1, attributes={})
