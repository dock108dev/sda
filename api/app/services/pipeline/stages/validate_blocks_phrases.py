"""Generic phrase density warnings (grader_rules TOML)."""

from __future__ import annotations

import logging
import tomllib
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_GENERIC_PHRASE_DENSITY_THRESHOLD = 2.0

_GENERIC_PHRASES_TOML = (
    Path(__file__).parents[5] / "scraper/sports_scraper/pipeline/grader_rules/generic_phrases.toml"
)

_GENERIC_PHRASES_FALLBACK: list[str] = [
    "gave it their all",
    "showed a lot of heart",
    "made their mark",
    "a hard-fought battle",
    "rose to the occasion",
    "when it mattered most",
    "from start to finish",
]


def _load_generic_phrases() -> tuple[list[str], float]:
    """Load phrase list and density threshold from grader_rules TOML."""
    if not _GENERIC_PHRASES_TOML.exists():
        logger.warning(
            "generic_phrases_toml_not_found",
            extra={"path": str(_GENERIC_PHRASES_TOML)},
        )
        return _GENERIC_PHRASES_FALLBACK, _GENERIC_PHRASE_DENSITY_THRESHOLD

    try:
        with open(_GENERIC_PHRASES_TOML, "rb") as f:
            data = tomllib.load(f)
        config = data.get("config", {})
        threshold = float(config.get("density_threshold", _GENERIC_PHRASE_DENSITY_THRESHOLD))
        phrases: list[str] = []
        phrases_section = data.get("phrases", {})
        for val in phrases_section.values():
            if isinstance(val, list):
                phrases.extend(str(p).lower() for p in val)
        return phrases, threshold
    except Exception:
        logger.warning(
            "generic_phrases_toml_load_failed",
            exc_info=True,
            extra={"path": str(_GENERIC_PHRASES_TOML)},
        )
        return _GENERIC_PHRASES_FALLBACK, _GENERIC_PHRASE_DENSITY_THRESHOLD


_GENERIC_PHRASES, _DENSITY_THRESHOLD = _load_generic_phrases()


def check_generic_phrase_density(
    blocks: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    """Warn when generic-phrase density in any block exceeds threshold (quality signal only)."""
    warnings: list[str] = []

    for block in blocks:
        block_idx = block.get("block_index", "?")
        narrative = block.get("narrative", "")
        if not narrative:
            continue

        lower = narrative.lower()
        matched = [p for p in _GENERIC_PHRASES if p in lower]
        if not matched:
            continue

        word_count = len(narrative.split())
        if word_count == 0:
            continue

        density = (len(matched) / word_count) * 100
        if density > _DENSITY_THRESHOLD:
            warnings.append(
                f"Block {block_idx}: generic phrase density {density:.1f}/100 words "
                f"(threshold={_DENSITY_THRESHOLD:.1f}); matched={matched}"
            )
            logger.warning(
                "generic_phrase_density_exceeded",
                extra={
                    "block_index": block_idx,
                    "density": round(density, 2),
                    "threshold": _DENSITY_THRESHOLD,
                    "matched_phrases": matched,
                    "word_count": word_count,
                },
            )

    return [], warnings
