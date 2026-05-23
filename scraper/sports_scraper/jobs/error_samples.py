from __future__ import annotations

SUPPRESSED_ERROR_TEXT_LIMIT = 500


def suppressed_error_sample(
    phase: str,
    exc: Exception,
    *,
    game_id: int | None = None,
) -> dict[str, object]:
    sample: dict[str, object] = {
        "phase": phase,
        "error": str(exc)[:SUPPRESSED_ERROR_TEXT_LIMIT],
    }
    if game_id is not None:
        sample["game_id"] = game_id
    return sample
