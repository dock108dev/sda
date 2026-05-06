"""Archetype-aware narrative-coherence validators (rules 13–14).

Rules 1–11 (in ``validate_blocks_rules.py``) handle structural / stylistic
checks. Rules 17–19 (in ``validate_blocks_voice.py``) enforce the v3 voice
contract. The rules in this module sit between: archetype-conditional
language gates that depend on the game's overall shape.

- Rule 13 — Blowout late-block leverage (FAIL): in blowout archetypes,
  blocks in the final 20% of the flow must not use language that implies
  the outcome is still uncertain.
- Rule 14 — Low-event drama (FAIL on regen): for low-scoring archetypes,
  exaggerated dominance descriptors are flagged so the regen feedback
  loop tones them down.

The "final 20%" notion (Rule 13) uses the block's position within the
ordered block list: the trailing 20% of blocks are the late blocks. The
RESOLUTION block is always last so a 5-block flow flags only that block;
a 7-block flow flags the last two. This avoids sport-specific clock
parsing and is consistent with how the rest of the pipeline treats block
order as the authoritative timeline ordering.
"""

from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger(__name__)

# Archetypes that classify_game_shape may emit (see classify_game_shape.py).
# Both blowout sub-types share the late-leverage prohibition.
_BLOWOUT_ARCHETYPES: frozenset[str] = frozenset(
    [
        "blowout",
        "early_avalanche_blowout",
    ]
)

# Archetype that signals a low-scoring / defensive game; exaggerated
# dominance language is inappropriate here.
_LOW_EVENT_ARCHETYPES: frozenset[str] = frozenset(["low_event"])

# Phrases that imply the outcome is still in doubt. These are *banned* in
# late blocks of blowout games — the result is already decided.
_OUTCOME_UNCERTAINTY_PHRASES: tuple[str, ...] = (
    "could still",
    "chance",
    "hope",
    "rally",
    "comeback",
)

# Exaggerated descriptors that overstate dominance in a low-scoring game.
# The bar is intentionally high — a 2-1 game does not get to call the
# winning pitcher "impenetrable".
_EXAGGERATED_DESCRIPTORS: tuple[str, ...] = (
    "dominant",
    "shutout domination",
    "impenetrable",
)

# Late-block fraction for Rule 13. Blocks whose 1-indexed position over
# total block count is >= this value are considered "late" (final 20%).
_LATE_BLOCK_FRACTION = 0.8


def _is_late_block(position: int, total: int) -> bool:
    """Return True when the 0-indexed block position is in the final 20%.

    ``ceil`` ensures small flows still flag the last block — a 3-block
    flow has ``ceil(3 * 0.8) = 3`` so only ``position >= 2`` qualifies.
    """
    if total <= 0:
        return False
    cutoff = max(1, math.ceil(total * _LATE_BLOCK_FRACTION)) - 1
    return position >= cutoff


def validate_blowout_late_leverage(
    blocks: list[dict[str, Any]],
    archetype: str | None,
) -> tuple[list[str], list[str]]:
    """Rule 13 — outcome-uncertainty language is banned in late blowout blocks.

    Only fires when the game-level archetype is a blowout variant. Other
    archetypes legitimately use comeback/rally language; we don't want
    to over-trigger.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not archetype or archetype not in _BLOWOUT_ARCHETYPES:
        return errors, warnings

    total = len(blocks)
    for position, block in enumerate(blocks):
        if not _is_late_block(position, total):
            continue

        narrative = (block.get("narrative") or "").lower()
        if not narrative:
            continue

        hits = sorted({p for p in _OUTCOME_UNCERTAINTY_PHRASES if p in narrative})
        if not hits:
            continue

        block_idx = block.get("block_index", position)
        errors.append(
            f"Block {block_idx}: blowout late-block leverage language detected — {hits}"
        )
        logger.warning(
            "blowout_late_leverage_detected",
            extra={
                "block_index": block_idx,
                "archetype": archetype,
                "matched_phrases": hits,
            },
        )

    return errors, warnings


def validate_low_event_drama(
    blocks: list[dict[str, Any]],
    archetype: str | None,
) -> tuple[list[str], list[str]]:
    """Rule 14 — exaggerated dominance descriptors in low-event games.

    Returns errors (REGENERATE) so the renderer's regen feedback loop can
    soften the language. The issue spec describes this as "WARNING →
    REGENERATE on 2nd offense"; in practice the existing pipeline only
    surfaces a single regen attempt per failure class, so we treat each
    hit as regen-eligible. The orchestrator owns the attempt counting.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not archetype or archetype not in _LOW_EVENT_ARCHETYPES:
        return errors, warnings

    for block in blocks:
        narrative = (block.get("narrative") or "").lower()
        if not narrative:
            continue

        hits = sorted({p for p in _EXAGGERATED_DESCRIPTORS if p in narrative})
        if not hits:
            continue

        block_idx = block.get("block_index", "?")
        errors.append(
            f"Block {block_idx}: low-event drama descriptor detected — {hits}"
        )
        logger.warning(
            "low_event_drama_detected",
            extra={
                "block_index": block_idx,
                "archetype": archetype,
                "matched_phrases": hits,
            },
        )

    return errors, warnings


__all__ = [
    "validate_blowout_late_leverage",
    "validate_low_event_drama",
]
