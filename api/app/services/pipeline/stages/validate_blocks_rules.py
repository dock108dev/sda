"""Structural and content validation rules for rendered narrative blocks."""

from __future__ import annotations

from typing import Any

from .block_types import (
    MAX_BLOCKS,
    MAX_TOTAL_WORDS,
    MAX_WORDS_PER_BLOCK,
    MIN_BLOCKS,
    MIN_WORDS_PER_BLOCK,
    SemanticRole,
)
from .validate_blocks_constants import (
    MAX_SENTENCES_PER_BLOCK,
    MIN_SENTENCES_PER_BLOCK,
    MINI_BOX_STAT_FIELDS,
    MINI_BOX_UNKNOWN,
    REQUIRED_BLOCK_TYPES,
)
from .validate_blocks_text import (
    count_sentences,
    validate_narrative_coverage,
)


def validate_block_count(blocks: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Validate block count is in range [3, 7]."""
    errors: list[str] = []
    warnings: list[str] = []

    count = len(blocks)

    if count < MIN_BLOCKS:
        errors.append(f"Too few blocks: {count} (minimum: {MIN_BLOCKS})")
    elif count > MAX_BLOCKS:
        errors.append(f"Too many blocks: {count} (maximum: {MAX_BLOCKS})")

    return errors, warnings


def validate_required_block_types(
    blocks: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    """Validate that SETUP and RESOLUTION block types are present."""
    errors: list[str] = []
    warnings: list[str] = []

    present_roles = {block.get("role") for block in blocks}
    for required_role in sorted(REQUIRED_BLOCK_TYPES):
        if required_role not in present_roles:
            errors.append(
                f"Required block type missing: {required_role} "
                f"(present roles: {sorted(r for r in present_roles if r)})"
            )

    return errors, warnings


def validate_role_constraints(blocks: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Validate role constraints: max two per role, SETUP first, RESOLUTION last."""
    errors: list[str] = []
    warnings: list[str] = []

    if not blocks:
        return errors, warnings

    first_role = blocks[0].get("role")
    if first_role != SemanticRole.SETUP.value:
        errors.append(f"First block must be SETUP, got: {first_role}")

    last_role = blocks[-1].get("role")
    if last_role != SemanticRole.RESOLUTION.value:
        errors.append(f"Last block must be RESOLUTION, got: {last_role}")

    role_counts: dict[str, int] = {}
    for block in blocks:
        role = block.get("role", "")
        role_counts[role] = role_counts.get(role, 0) + 1

    for role, count in role_counts.items():
        if count > 2:
            errors.append(f"Role {role} appears {count} times (maximum: 2)")

    return errors, warnings


def validate_word_counts(blocks: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Validate word counts and sentence counts per block and total."""
    errors: list[str] = []
    warnings: list[str] = []

    total_words = 0

    for block in blocks:
        block_idx = block.get("block_index", "?")
        narrative = block.get("narrative", "")

        if not narrative:
            errors.append(f"Block {block_idx}: Missing narrative")
            continue

        word_count = len(narrative.split())
        total_words += word_count

        if word_count < MIN_WORDS_PER_BLOCK:
            warnings.append(
                f"Block {block_idx}: Too short ({word_count} words, min: {MIN_WORDS_PER_BLOCK})"
            )

        if word_count > MAX_WORDS_PER_BLOCK:
            warnings.append(
                f"Block {block_idx}: Too long ({word_count} words, max: {MAX_WORDS_PER_BLOCK})"
            )

        sentence_count = count_sentences(narrative)
        if sentence_count < MIN_SENTENCES_PER_BLOCK:
            warnings.append(
                f"Block {block_idx}: Too few sentences ({sentence_count}, min: {MIN_SENTENCES_PER_BLOCK})"
            )

        if sentence_count > MAX_SENTENCES_PER_BLOCK:
            warnings.append(
                f"Block {block_idx}: Too many sentences ({sentence_count}, max: {MAX_SENTENCES_PER_BLOCK})"
            )

    if total_words > MAX_TOTAL_WORDS:
        warnings.append(f"Total word count too high: {total_words} (target max: {MAX_TOTAL_WORDS})")

    return errors, warnings


def validate_score_continuity(blocks: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Validate score continuity across block boundaries."""
    errors: list[str] = []
    warnings: list[str] = []

    for i in range(len(blocks) - 1):
        current_block = blocks[i]
        next_block = blocks[i + 1]

        current_after = current_block.get("score_after", [0, 0])
        next_before = next_block.get("score_before", [0, 0])

        if list(current_after) != list(next_before):
            errors.append(
                f"Score discontinuity between blocks {i} and {i + 1}: "
                f"{current_after} -> {next_before}"
            )

    return errors, warnings


def validate_moment_coverage(
    blocks: list[dict[str, Any]],
    total_moments: int,
) -> tuple[list[str], list[str]]:
    """Validate that all moments are covered by blocks."""
    errors: list[str] = []
    warnings: list[str] = []

    covered_moments: set[int] = set()
    for block in blocks:
        moment_indices = block.get("moment_indices", [])
        for idx in moment_indices:
            if idx in covered_moments:
                errors.append(f"Moment {idx} is in multiple blocks")
            covered_moments.add(idx)

    expected_moments = set(range(total_moments))
    missing = expected_moments - covered_moments
    extra = covered_moments - expected_moments

    if missing:
        errors.append(f"Moments not covered by any block: {sorted(missing)}")

    if extra:
        warnings.append(f"Blocks reference non-existent moments: {sorted(extra)}")

    return errors, warnings


def validate_key_plays(blocks: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Validate key plays per block."""
    errors: list[str] = []
    warnings: list[str] = []

    for block in blocks:
        block_idx = block.get("block_index", "?")
        key_play_ids = block.get("key_play_ids", [])
        play_ids = block.get("play_ids", [])

        if not key_play_ids:
            warnings.append(f"Block {block_idx}: No key plays selected")
            continue

        if len(key_play_ids) > 3:
            warnings.append(f"Block {block_idx}: Too many key plays ({len(key_play_ids)}, max: 3)")

        play_id_set = set(play_ids)
        for key_id in key_play_ids:
            if key_id not in play_id_set:
                errors.append(f"Block {block_idx}: Key play {key_id} not in block's play_ids")

    return errors, warnings


def validate_mini_box(blocks: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Validate mini_box cumulative and delta stats."""
    errors: list[str] = []
    warnings: list[str] = []

    for block in blocks:
        block_idx = block.get("block_index", "?")
        mini_box = block.get("mini_box")

        if not mini_box or not isinstance(mini_box, dict):
            errors.append(f"Block {block_idx}: mini_box is missing or empty")
            continue

        cumulative = mini_box.get("cumulative")
        if not cumulative or not isinstance(cumulative, dict):
            errors.append(f"Block {block_idx}: mini_box missing cumulative stats")
        else:
            for side in ("home", "away"):
                team_stats = cumulative.get(side)
                if team_stats is None:
                    errors.append(f"Block {block_idx}: mini_box cumulative missing {side} stats")
                elif isinstance(team_stats, dict):
                    for field in sorted(MINI_BOX_STAT_FIELDS):
                        if team_stats.get(field) is None:
                            team_stats[field] = MINI_BOX_UNKNOWN
                            warnings.append(
                                f"Block {block_idx}: mini_box cumulative.{side}.{field} "
                                f"absent — filled with {MINI_BOX_UNKNOWN!r}"
                            )

        delta = mini_box.get("delta")
        if not delta or not isinstance(delta, dict):
            errors.append(f"Block {block_idx}: mini_box missing segment delta stats")
        else:
            for side in ("home", "away"):
                side_stats = delta.get(side)
                if isinstance(side_stats, dict):
                    for field in sorted(MINI_BOX_STAT_FIELDS):
                        if side_stats.get(field) is None:
                            side_stats[field] = MINI_BOX_UNKNOWN
                            warnings.append(
                                f"Block {block_idx}: mini_box delta.{side}.{field} "
                                f"absent — filled with {MINI_BOX_UNKNOWN!r}"
                            )

    return errors, warnings


def validate_coverage(
    blocks: list[dict[str, Any]],
    home_team: str,
    away_team: str,
    home_score: int,
    away_score: int,
    has_overtime: bool,
) -> tuple[list[str], list[str]]:
    """Validate narrative coverage (score, winner, OT)."""
    return validate_narrative_coverage(
        blocks, home_team, away_team, home_score, away_score, has_overtime
    )
