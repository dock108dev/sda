"""Voice / contract validators (rules 17–19) for the v3 gameflow schema.

These rules enforce the gameflow brief's "narrative is evidence, not
decoration" contract. They run after structural and language checks
(rules 1–16) and feed into the same regen feedback loop.

- Rule 17 — Final-score repetition (FAIL): the closing score must not
  appear verbatim in more than one block. Repeating "12-1" or "104-102"
  across blocks is a tell that the generator is padding chunks with the
  outcome instead of describing what happened inside each segment.
- Rule 18 — Featured-player reason required (FAIL when present): if a
  block lists ``featured_players``, every entry must carry a non-empty
  ``reason`` field. Player callouts must explain why the player matters
  to the segment, not decorate it.
- Rule 19 — Story role present (WARNING; promoted to FAIL once the v3
  segmenter ships): every block should declare which beat it represents
  (opening, first_separation, response, lead_change, turning_point,
  closeout, blowout_compression). Stays a warning during Pass 1 because
  the upstream segmenter does not populate ``story_role`` yet.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

VALID_STORY_ROLES: frozenset[str] = frozenset(
    [
        "opening",
        "first_separation",
        "response",
        "lead_change",
        "turning_point",
        "closeout",
        "blowout_compression",
    ]
)


def _final_score_patterns(home_score: int, away_score: int) -> list[re.Pattern[str]]:
    """Return regexes that match the final score in either home–away order.

    A literal substring search would false-match scores from inside the game
    (e.g. a 12-1 final would clobber legitimate use of "1-2" elsewhere).
    Anchoring on word-boundary keeps the check tight.
    """
    pairs = {(home_score, away_score), (away_score, home_score)}
    patterns: list[re.Pattern[str]] = []
    for left, right in pairs:
        if left < 0 or right < 0:
            continue
        # Match "12-1", "12–1" (en dash), and "12 to 1".
        patterns.append(
            re.compile(rf"\b{left}\s*[-–]\s*{right}\b|\b{left}\s+to\s+{right}\b")
        )
    return patterns


def validate_no_repeated_final_score(
    blocks: list[dict[str, Any]],
    home_score: int,
    away_score: int,
) -> tuple[list[str], list[str]]:
    """Final-score string must not appear in more than one block narrative.

    The RESOLUTION block legitimately carries the final number; any earlier
    block that also drops "12-1" is padding. Empty narratives and blocks
    without scores are skipped.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if home_score < 0 or away_score < 0:
        return errors, warnings
    patterns = _final_score_patterns(home_score, away_score)
    if not patterns:
        return errors, warnings

    hits: list[int] = []
    for block in blocks:
        narrative = block.get("narrative") or ""
        if not narrative:
            continue
        if any(pat.search(narrative) for pat in patterns):
            hits.append(block.get("block_index", -1))

    if len(hits) > 1:
        errors.append(
            f"Final score {home_score}-{away_score} appears in "
            f"{len(hits)} blocks (indices {hits}); restrict to the closing block."
        )
        logger.warning(
            "final_score_repeated",
            extra={
                "home_score": home_score,
                "away_score": away_score,
                "block_indices": hits,
            },
        )
    return errors, warnings


def validate_featured_players_have_reason(
    blocks: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    """Every entry in ``featured_players`` must carry a non-empty ``reason``.

    Skipped entirely when a block has no ``featured_players`` — Pass 1 is
    additive, so we only constrain what the new segmenter actually populates.
    Once Pass 3 fills the field on every block, the absent-list check
    becomes redundant with rule 19.
    """
    errors: list[str] = []
    warnings: list[str] = []

    for block in blocks:
        featured = block.get("featured_players")
        if not featured:
            continue
        block_idx = block.get("block_index", "?")
        for player_idx, player in enumerate(featured):
            if not isinstance(player, dict):
                errors.append(
                    f"Block {block_idx}: featured_players[{player_idx}] "
                    f"is not an object."
                )
                continue
            reason = player.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                name = player.get("name", "<unknown>")
                errors.append(
                    f"Block {block_idx}: featured_players[{player_idx}] "
                    f"({name}) is missing a reason — player callouts must "
                    f"explain the segment beat, not decorate it."
                )
    if errors:
        logger.warning(
            "featured_players_missing_reason",
            extra={"errors": errors},
        )
    return errors, warnings


def validate_story_role_present(
    blocks: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    """Every block must declare a ``story_role`` from VALID_STORY_ROLES.

    Promoted to ERROR in Pass 3: the GROUP_BLOCKS classifier now populates
    ``story_role`` on every block, so absence is a real bug rather than a
    historical-data gap. Failing here triggers REGENERATE which re-runs
    the classifier — if the second attempt still has missing roles, the
    pipeline falls back to the template engine.
    """
    errors: list[str] = []
    warnings: list[str] = []

    for block in blocks:
        block_idx = block.get("block_index", "?")
        story_role = block.get("story_role")
        if story_role is None:
            errors.append(
                f"Block {block_idx}: missing story_role (v3 contract)."
            )
            continue
        if story_role not in VALID_STORY_ROLES:
            errors.append(
                f"Block {block_idx}: story_role={story_role!r} is not in "
                f"{sorted(VALID_STORY_ROLES)}."
            )
    return errors, warnings
