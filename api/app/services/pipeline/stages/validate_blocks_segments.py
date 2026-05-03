"""Segment-level quality validation rules (rules 12–16).

Rules 1–11 (in ``validate_blocks_rules.py`` and adjacent helpers) handle
structural and stylistic checks. The rules in this module enforce
narrative-coherence guarantees that depend on archetype, per-block lead
metadata, and v2 schema fields (``reason``, ``evidence``).

Rule numbering matches the issue spec and the orchestration in
``validate_blocks.execute_validate_blocks``:

- Rule 12 — Lead consistency (FAIL): adjacent blocks must agree on the
  shared boundary lead value (``lead_after[N] == lead_before[N+1]``).
- Rule 13 — Blowout late-block leverage (FAIL): in blowout archetypes,
  blocks in the final 20% of the flow must not use language that implies
  the outcome is still uncertain.
- Rule 14 — Low-event drama (FAIL on regen): for low-scoring archetypes,
  exaggerated dominance descriptors are flagged so the regen feedback
  loop tones them down.
- Rule 15 — Block ``reason`` present (WARNING): the v2 ``reason`` field
  should be populated and informative (>= 10 characters).
- Rule 16 — Evidence present when asserting (WARNING): a block with no
  evidence events but a substantial narrative (> 30 words) is asserting
  without grounding.

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

# Minimum length for the ``reason`` field to count as informative.
_MIN_REASON_LENGTH = 10

# Word-count threshold above which a block must cite at least one
# evidence event (Rule 16).
_EVIDENCE_REQUIRED_WORD_COUNT = 30

# Late-block fraction for Rule 13. Blocks whose 1-indexed position over
# total block count is >= this value are considered "late" (final 20%).
_LATE_BLOCK_FRACTION = 0.8


def _normalize_lead(value: Any) -> int | None:
    """Coerce a lead value to ``int`` when possible, else ``None``.

    Blocks may carry ``None`` when score data is missing; those gaps are
    skipped rather than reported as discontinuities.
    """
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def validate_lead_consistency(
    blocks: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    """Rule 12 — adjacent blocks must agree on the shared boundary lead.

    For each adjacent pair, ``lead_after[N]`` must equal ``lead_before[N+1]``.
    A mismatch indicates the renderer (or flow pass) drifted across the
    boundary and produced narratives describing inconsistent score states.
    """
    errors: list[str] = []
    warnings: list[str] = []

    for i in range(len(blocks) - 1):
        current = blocks[i]
        nxt = blocks[i + 1]

        current_after = _normalize_lead(current.get("lead_after"))
        next_before = _normalize_lead(nxt.get("lead_before"))

        if current_after is None or next_before is None:
            continue

        if current_after != next_before:
            errors.append(
                f"Lead discontinuity between blocks {i} and {i + 1}: "
                f"lead_after={current_after} -> lead_before={next_before}"
            )
            logger.warning(
                "lead_discontinuity_detected",
                extra={
                    "block_index": i,
                    "next_block_index": i + 1,
                    "lead_after": current_after,
                    "lead_before_next": next_before,
                },
            )

    return errors, warnings


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


def validate_reason_present(
    blocks: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    """Rule 15 — every block should carry an informative ``reason``.

    Empty or near-empty (< 10 chars) reason fields are warnings; they
    don't block publish but flag that the upstream stage failed to record
    why this block was created.
    """
    errors: list[str] = []
    warnings: list[str] = []

    for block in blocks:
        reason = (block.get("reason") or "").strip()
        if len(reason) >= _MIN_REASON_LENGTH:
            continue

        block_idx = block.get("block_index", "?")
        warnings.append(
            f"Block {block_idx}: reason missing or too short "
            f"(len={len(reason)}, min={_MIN_REASON_LENGTH})"
        )

    return errors, warnings


def validate_evidence_present(
    blocks: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    """Rule 16 — substantial blocks must cite evidence events.

    A block with no evidence and >30 words is asserting without grounding.
    Evidence may be a list of events or any non-empty container; we accept
    anything truthy on the ``evidence`` field.
    """
    errors: list[str] = []
    warnings: list[str] = []

    for block in blocks:
        evidence = block.get("evidence")
        has_evidence = bool(evidence)

        narrative = block.get("narrative") or ""
        word_count = len(narrative.split())

        if has_evidence or word_count <= _EVIDENCE_REQUIRED_WORD_COUNT:
            continue

        block_idx = block.get("block_index", "?")
        warnings.append(
            f"Block {block_idx}: no evidence with {word_count} words "
            f"(threshold={_EVIDENCE_REQUIRED_WORD_COUNT}) — block asserts without grounding"
        )

    return errors, warnings


__all__ = [
    "validate_blowout_late_leverage",
    "validate_evidence_present",
    "validate_lead_consistency",
    "validate_low_event_drama",
    "validate_reason_present",
]
