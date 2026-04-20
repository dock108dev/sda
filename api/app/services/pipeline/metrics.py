"""OTel metrics instruments for the narrative pipeline.

Instruments are lazily initialized from the global MeterProvider on first use.
When opentelemetry-sdk is not installed or no endpoint is configured, all
functions are no-ops — callers never need to guard against import errors.
"""
from __future__ import annotations

import logging

_logger = logging.getLogger(__name__)

_initialized = False
_stage_duration = None
_regen_count = None
_fallback_count = None
_published_count = None
_score_mismatch_count = None

_quality_initialized = False
_quality_score_hist = None


class _Noop:
    """Minimal no-op stand-in for OTel Histogram / Counter."""

    def record(self, *args, **kwargs) -> None:  # noqa: ANN002
        pass

    def add(self, *args, **kwargs) -> None:  # noqa: ANN002
        pass


_NOOP = _Noop()


def _instruments():
    global _initialized, _stage_duration, _regen_count, _fallback_count, _published_count, _score_mismatch_count
    if _initialized:
        return _stage_duration, _regen_count, _fallback_count, _published_count, _score_mismatch_count

    _initialized = True
    try:
        from opentelemetry import metrics

        meter = metrics.get_meter("pipeline", version="1.0")
        _stage_duration = meter.create_histogram(
            name="pipeline.stage.duration_ms",
            description="Duration of each pipeline stage in milliseconds",
            unit="ms",
        )
        _regen_count = meter.create_counter(
            name="pipeline.regen.count",
            description="Number of REGENERATE decisions made by VALIDATE_BLOCKS",
        )
        _fallback_count = meter.create_counter(
            name="pipeline.fallback.count",
            description="Number of FALLBACK decisions (template substitutions) made by VALIDATE_BLOCKS",
        )
        _published_count = meter.create_counter(
            name="pipeline.flow.published.count",
            description="Number of flows successfully persisted by FINALIZE_MOMENTS",
        )
        _score_mismatch_count = meter.create_counter(
            name="pipeline.score_mismatch",
            description="Flows written whose embedded score differed from the authoritative Boxscore score",
        )
    except ImportError:
        _logger.debug("opentelemetry not available — pipeline metrics are no-ops")
        _stage_duration = _regen_count = _fallback_count = _published_count = _score_mismatch_count = _NOOP

    return _stage_duration, _regen_count, _fallback_count, _published_count, _score_mismatch_count


def record_stage_duration(stage_name: str, sport: str, duration_ms: float) -> None:
    """Record how long a pipeline stage took to execute."""
    hist, _, _, _, _ = _instruments()
    hist.record(duration_ms, attributes={"stage": stage_name, "sport": sport})


def increment_regen(sport: str, reason: str) -> None:
    """Increment the REGENERATE decision counter.

    Args:
        sport: League code (e.g. "NBA", "NFL").
        reason: Why regeneration was triggered — "coverage_fail" or "quality_fail".
    """
    _, counter, _, _, _ = _instruments()
    counter.add(1, attributes={"sport": sport, "reason": reason})


def increment_fallback(sport: str, reason: str = "max_regen_exceeded") -> None:
    """Increment the FALLBACK decision counter (template substitution path)."""
    _, _, counter, _, _ = _instruments()
    counter.add(1, attributes={"sport": sport, "reason": reason})


def increment_published(sport: str) -> None:
    """Increment the published-flow counter on successful FINALIZE_MOMENTS."""
    _, _, _, counter, _ = _instruments()
    counter.add(1, attributes={"sport": sport})


def _quality_instruments():
    global _quality_initialized, _quality_score_hist
    if _quality_initialized:
        return _quality_score_hist

    _quality_initialized = True
    try:
        from opentelemetry import metrics

        meter = metrics.get_meter("pipeline", version="1.0")
        _quality_score_hist = meter.create_histogram(
            name="pipeline.flow.quality_score",
            description="Combined narrative quality score (0–100) for each graded flow",
            unit="1",
        )
    except ImportError:
        _logger.debug("opentelemetry not available — quality_score metric is a no-op")
        _quality_score_hist = _NOOP

    return _quality_score_hist


def record_flow_quality_score(sport: str, tier: str, score: float) -> None:
    """Record the narrative quality score for a flow.

    Args:
        sport: League code (e.g. "NBA").
        tier: Which grader tier produced the score — "tier1", "tier2", or "combined".
        score: Score in the 0–100 range.
    """
    hist = _quality_instruments()
    hist.record(score, attributes={"sport": sport, "tier": tier})


def increment_score_mismatch(sport: str) -> None:
    """Increment the score-mismatch counter.

    Called when a flow is written (or nearly written) with embedded scores that
    differ from the authoritative Boxscore values in the DB.  Any increment of
    this counter should be investigated — it means published narrative may cite
    incorrect final scores.

    Args:
        sport: League code (e.g. "NBA", "NFL").
    """
    _, _, _, _, counter = _instruments()
    counter.add(1, attributes={"sport": sport})
