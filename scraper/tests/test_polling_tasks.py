from __future__ import annotations

from sports_scraper.jobs.error_samples import (
    SUPPRESSED_ERROR_TEXT_LIMIT,
    suppressed_error_sample,
)


def test_suppressed_error_sample_truncates_large_errors() -> None:
    sample = suppressed_error_sample("pbp", RuntimeError("x" * 1000), game_id=42)

    assert sample == {
        "phase": "pbp",
        "game_id": 42,
        "error": "x" * SUPPRESSED_ERROR_TEXT_LIMIT,
    }
