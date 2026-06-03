"""Parsing and hashing helpers for the narrative quality grader."""

from __future__ import annotations

import hashlib
import json
import re


def _count_words(text: str) -> int:
    return len(text.split())


def _all_block_narratives(blocks: list[dict]) -> str:
    return " ".join(b.get("narrative", "") for b in blocks)


def _compute_prompt_hash(blocks: list[dict], game_data: dict) -> str:
    """Stable 16-char hex hash over scoring inputs for cache keying."""
    payload = json.dumps(
        {
            "blocks": blocks,
            "game": {
                k: game_data.get(k)
                for k in ("sport", "home_team", "away_team", "home_score", "away_score")
            },
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


# Rubric dimensions scored by both the Haiku and Sonnet Tier 2 prompts;
# the per-prompt instructions above ask for these exact JSON keys.
_TIER2_RUBRIC_DIMS: tuple[str, ...] = (
    "factual_accuracy",
    "sport_specific_voice",
    "narrative_coherence",
    "no_generic_filler",
)


def _strip_code_fence(text: str) -> str:
    """Strip a leading Markdown ```lang fence and trailing backticks/whitespace."""
    if text.startswith("```"):
        return re.sub(r"^```[a-z]*\n?", "", text).rstrip("` \n")
    return text


def _parse_tier2_rubric_json(raw: str) -> tuple[float, dict[str, float]]:
    """Parse cleaned rubric JSON into ``(score, rubric)``.

    Each dimension is clamped to ``[0, 25]`` and the score is the rounded
    sum. Raises ``json.JSONDecodeError``/``ValueError``/``KeyError``/
    ``IndexError``/``TypeError`` on malformed responses; the Tier 2 callers
    turn those into a neutral 50 + structured warning log.
    """
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError(f"expected JSON object, got {type(parsed).__name__}")
    rubric = {
        dim: float(min(max(parsed.get(dim, 0), 0), 25))
        for dim in _TIER2_RUBRIC_DIMS
    }
    return round(sum(rubric.values()), 1), rubric
