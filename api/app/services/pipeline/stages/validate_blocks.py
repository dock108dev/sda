"""VALIDATE_BLOCKS Stage Implementation.

This stage validates the rendered blocks to ensure they meet all constraints.

VALIDATION RULES
================
1. Block count in range [3, 7]
2. No role appears more than twice
3. Each narrative >= 30 words (meaningful content)
4. Each narrative <= 120 words (up to 5 sentences)
5. First block role = SETUP
6. Last block role = RESOLUTION
7. Score continuity across block boundaries
8. Total word count <= 600
9. Each narrative has 1-5 sentences
10. Narrative coverage: final score, winning team, OT presence
11. mini_box population: cumulative stats for both teams + segment deltas

GUARANTEES
==========
- All constraints validated before returning success
- Detailed error messages for each violation
- Warnings for soft limit violations
- Coverage failures produce REGENERATE decision (FALLBACK after max retries)
- mini_box failures produce REGENERATE decision (FALLBACK after max retries)
"""

from __future__ import annotations

import logging
import re
from typing import Any

from ....db import AsyncSession
from ..models import StageInput, StageOutput
from .block_types import (
    MAX_BLOCKS,
    MAX_TOTAL_WORDS,
    MAX_WORDS_PER_BLOCK,
    MIN_BLOCKS,
    MIN_WORDS_PER_BLOCK,
    SemanticRole,
)
from .embedded_tweets import load_and_attach_embedded_tweets

logger = logging.getLogger(__name__)

# Sentence count constraints
MIN_SENTENCES_PER_BLOCK = 1  # RESOLUTION blocks may be a single powerful sentence
MAX_SENTENCES_PER_BLOCK = 5  # DECISION_POINT blocks may need more detail

# Coverage validation
MAX_REGEN_ATTEMPTS = 2  # After 2 failed regen attempts, fall back to template

# Terms that indicate overtime in generated text; padded with spaces for word-boundary matching
OT_TERMS = frozenset([
    "overtime",
    " ot ",
    "ot.",
    "ot,",
    "extra time",
    "sudden death",
    "double overtime",
    "triple overtime",
])

# Common abbreviations that contain periods but don't end sentences
# Used to avoid false sentence breaks in _count_sentences
COMMON_ABBREVIATIONS = [
    "Mr.", "Mrs.", "Ms.", "Dr.", "Jr.", "Sr.", "vs.", "etc.", "e.g.", "i.e.",
    "St.", "Ave.", "Blvd.", "Rd.", "Mt.", "Ft.",  # Addresses
    "Jan.", "Feb.", "Mar.", "Apr.", "Aug.", "Sept.", "Oct.", "Nov.", "Dec.",
]


def _normalize_text(text: str) -> str:
    """Lowercase and collapse whitespace for coverage matching."""
    return re.sub(r"\s+", " ", text.lower().strip())


def _check_score_present(text: str, home: int, away: int) -> bool:
    """Return True if the score (either order) appears in text.

    Handles hyphens, en/em dashes, and written-out 'X to Y' forms.
    """
    norm = _normalize_text(text)
    sep = r"\s*[-\u2013\u2014]\s*|\s+to\s+"
    patterns = [
        rf"\b{home}(?:{sep}){away}\b",
        rf"\b{away}(?:{sep}){home}\b",
    ]
    return any(re.search(p, norm) for p in patterns)


def _check_team_present(text: str, team: str) -> bool:
    """Return True if the team name (or its nickname) appears in text."""
    norm = _normalize_text(text)
    parts = team.split()
    variants = [_normalize_text(team)]
    if len(parts) > 1:
        variants.append(parts[-1].lower())
    return any(v in norm for v in variants)


def _check_ot_present(text: str) -> bool:
    """Return True if any overtime indicator appears in text."""
    norm = _normalize_text(text)
    # Pad to allow leading/trailing OT_TERMS like " ot "
    padded = f" {norm} "
    return any(term in padded for term in OT_TERMS)


def _validate_coverage(
    blocks: list[dict[str, Any]],
    home_team: str,
    away_team: str,
    home_score: int,
    away_score: int,
    has_overtime: bool,
) -> tuple[list[str], list[str]]:
    """Validate that narrative coverage includes required game facts.

    Checks for: final score, winning team name, overtime mention (if applicable).

    Args:
        blocks: Rendered narrative blocks.
        home_team: Home team name.
        away_team: Away team name.
        home_score: Final home score.
        away_score: Final away score.
        has_overtime: Whether the game went to overtime.

    Returns:
        Tuple of (errors, warnings).
    """
    errors: list[str] = []
    warnings: list[str] = []

    full_text = " ".join(
        b.get("narrative", "") for b in blocks if b.get("narrative")
    ).strip()

    if not full_text:
        errors.append("Coverage: No narrative text to validate")
        return errors, warnings

    # Skip score/winner checks when no score data is available (both default to 0)
    if home_score == 0 and away_score == 0:
        warnings.append("Coverage: Score data unavailable, skipping score/winner checks")
    else:
        if not _check_score_present(full_text, home_score, away_score):
            errors.append(
                f"Coverage: Final score {home_score}-{away_score} not mentioned in narrative"
            )

        if home_score != away_score:
            winning_team = home_team if home_score > away_score else away_team
            if winning_team and not _check_team_present(full_text, winning_team):
                errors.append(
                    f"Coverage: Winning team '{winning_team}' not mentioned in narrative"
                )

    if has_overtime and not _check_ot_present(full_text):
        errors.append(
            "Coverage: Game went to overtime but no OT mention found in narrative"
        )

    return errors, warnings


def _count_sentences(text: str) -> int:
    """Count the number of sentences in text.

    Uses sentence-ending punctuation (. ! ?) to split, with handling for
    common abbreviations to avoid false positives.

    Known limitations:
    - May not handle all abbreviations (only common ones are protected)
    - Single-letter initials like "J. Smith" may cause false splits
    - Decimal numbers like "3.5" are not specially handled

    Since this is used for soft validation warnings (not hard failures),
    approximate counts are acceptable.
    """
    if not text:
        return 0

    # Protect common abbreviations by temporarily replacing their periods
    # Use a marker that won't be split by [.!?]
    protected = text
    for abbrev in COMMON_ABBREVIATIONS:
        # Case-insensitive replacement
        pattern = re.escape(abbrev)
        protected = re.sub(pattern, abbrev.replace(".", "\x00"), protected, flags=re.IGNORECASE)

    # Collapse ellipsis to single marker (not a sentence break)
    protected = re.sub(r"\.{2,}", "\x00", protected)

    # Split on sentence-ending punctuation
    sentences = re.split(r"[.!?]+", protected)

    # Count non-empty segments
    return len([s for s in sentences if s.strip()])


def _validate_block_count(blocks: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Validate block count is in range [3, 7]."""
    errors: list[str] = []
    warnings: list[str] = []

    count = len(blocks)

    if count < MIN_BLOCKS:
        errors.append(f"Too few blocks: {count} (minimum: {MIN_BLOCKS})")
    elif count > MAX_BLOCKS:
        errors.append(f"Too many blocks: {count} (maximum: {MAX_BLOCKS})")

    return errors, warnings


def _validate_role_constraints(blocks: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Validate role constraints.

    - No role appears more than twice
    - First block is SETUP
    - Last block is RESOLUTION
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not blocks:
        return errors, warnings

    # Check first block is SETUP
    first_role = blocks[0].get("role")
    if first_role != SemanticRole.SETUP.value:
        errors.append(f"First block must be SETUP, got: {first_role}")

    # Check last block is RESOLUTION
    last_role = blocks[-1].get("role")
    if last_role != SemanticRole.RESOLUTION.value:
        errors.append(f"Last block must be RESOLUTION, got: {last_role}")

    # Count role occurrences
    role_counts: dict[str, int] = {}
    for block in blocks:
        role = block.get("role", "")
        role_counts[role] = role_counts.get(role, 0) + 1

    # Check no role appears more than twice
    for role, count in role_counts.items():
        if count > 2:
            errors.append(f"Role {role} appears {count} times (maximum: 2)")

    return errors, warnings


def _validate_word_counts(blocks: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Validate word counts and sentence counts for each block and total."""
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

        # Validate sentence count
        sentence_count = _count_sentences(narrative)
        if sentence_count < MIN_SENTENCES_PER_BLOCK:
            warnings.append(
                f"Block {block_idx}: Too few sentences ({sentence_count}, min: {MIN_SENTENCES_PER_BLOCK})"
            )

        if sentence_count > MAX_SENTENCES_PER_BLOCK:
            warnings.append(
                f"Block {block_idx}: Too many sentences ({sentence_count}, max: {MAX_SENTENCES_PER_BLOCK})"
            )

    if total_words > MAX_TOTAL_WORDS:
        warnings.append(
            f"Total word count too high: {total_words} (target max: {MAX_TOTAL_WORDS})"
        )

    return errors, warnings


def _validate_score_continuity(blocks: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Validate score continuity across block boundaries.

    Each block's score_after should equal the next block's score_before.
    """
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


def _validate_moment_coverage(
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


def _validate_key_plays(blocks: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Validate that each block has key plays and they are valid."""
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
            warnings.append(
                f"Block {block_idx}: Too many key plays ({len(key_play_ids)}, max: 3)"
            )

        # Verify key plays are subset of play_ids
        play_id_set = set(play_ids)
        for key_id in key_play_ids:
            if key_id not in play_id_set:
                errors.append(
                    f"Block {block_idx}: Key play {key_id} not in block's play_ids"
                )

    return errors, warnings


def _validate_mini_box(blocks: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Validate each block has a populated mini_box with cumulative and delta stats.

    Each block must carry:
    - mini_box.cumulative.home — cumulative home stats up to this block
    - mini_box.cumulative.away — cumulative away stats up to this block
    - mini_box.delta           — stats for just this block's time window
    """
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
            if not cumulative.get("home"):
                errors.append(f"Block {block_idx}: mini_box cumulative missing home stats")
            if not cumulative.get("away"):
                errors.append(f"Block {block_idx}: mini_box cumulative missing away stats")

        delta = mini_box.get("delta")
        if not delta or not isinstance(delta, dict):
            errors.append(f"Block {block_idx}: mini_box missing segment delta stats")

    return errors, warnings


async def _attach_embedded_tweets(
    session: AsyncSession,
    game_id: int,
    blocks: list[dict[str, Any]],
    output: StageOutput,
    league_code: str = "NBA",
) -> tuple[list[dict[str, Any]], Any]:
    """Load social posts and attach embedded tweets to blocks.

    Delegates to the shared load_and_attach_embedded_tweets SSOT function.
    Embedded tweets are optional and do not affect flow structure.

    Args:
        session: Database session
        game_id: Game ID to load social posts for
        blocks: Validated blocks to attach tweets to
        output: StageOutput to add logs to
        league_code: League code for period timing

    Returns:
        Tuple of (updated blocks, EmbeddedTweetSelection or None)
    """
    updated_blocks, selection = await load_and_attach_embedded_tweets(
        session, game_id, blocks, league_code=league_code
    )

    if selection:
        assigned_count = sum(1 for b in updated_blocks if b.get("embedded_social_post_id"))
        output.add_log(
            f"Embedded tweets: scored {selection.total_candidates} candidates, "
            f"assigned to {assigned_count} blocks"
        )
    else:
        output.add_log("No social posts available for embedded tweets")

    return updated_blocks, selection


async def execute_validate_blocks(
    session: AsyncSession,
    stage_input: StageInput,
) -> StageOutput:
    """Execute the VALIDATE_BLOCKS stage.

    Validates all block constraints before finalization. After validation passes,
    loads social posts and attaches embedded tweets to blocks.

    Args:
        session: Async database session for loading social posts
        stage_input: Input containing previous_output with rendered blocks

    Returns:
        StageOutput with validation results and embedded tweets

    Raises:
        ValueError: If prerequisites not met
    """
    output = StageOutput(data={})
    game_id = stage_input.game_id

    output.add_log(f"Starting VALIDATE_BLOCKS for game {game_id}")

    # Get input data from previous stages
    previous_output = stage_input.previous_output
    if not previous_output:
        raise ValueError("VALIDATE_BLOCKS requires previous stage output")

    # Verify RENDER_BLOCKS completed
    blocks_rendered = previous_output.get("blocks_rendered")
    if blocks_rendered is not True:
        raise ValueError(
            f"VALIDATE_BLOCKS requires RENDER_BLOCKS to complete. Got blocks_rendered={blocks_rendered}"
        )

    # Get blocks
    blocks = previous_output.get("blocks", [])
    if not blocks:
        raise ValueError("No blocks in previous stage output")

    total_moments = previous_output.get("total_moments", 0)
    if not total_moments:
        moments = previous_output.get("moments", [])
        total_moments = len(moments)

    output.add_log(f"Validating {len(blocks)} blocks covering {total_moments} moments")

    # Extract coverage-relevant game context
    ctx = stage_input.game_context or {}
    home_team = ctx.get("home_team", "")
    away_team = ctx.get("away_team", "")
    has_overtime = bool(ctx.get("has_overtime", False))
    regen_attempt = int(ctx.get("regen_attempt", 0))

    # Derive final score: prefer explicit context values, fall back to last block
    home_score_ctx = ctx.get("home_score")
    if home_score_ctx is None and blocks:
        last_score = blocks[-1].get("score_after", [0, 0])
        home_score = int(last_score[0]) if last_score else 0
        away_score = int(last_score[1]) if last_score else 0
    else:
        home_score = int(home_score_ctx or 0)
        away_score = int(ctx.get("away_score") or 0)

    # Run all validations
    all_errors: list[str] = []
    all_warnings: list[str] = []

    # 1. Block count
    output.add_log("Checking Rule 1: Block count in range [3, 7]")
    errors, warnings = _validate_block_count(blocks)
    all_errors.extend(errors)
    all_warnings.extend(warnings)
    if errors:
        output.add_log(f"Rule 1 FAILED: {errors}", level="error")
    else:
        output.add_log("Rule 1 PASSED")

    # 2. Role constraints
    output.add_log("Checking Rule 2: Role constraints")
    errors, warnings = _validate_role_constraints(blocks)
    all_errors.extend(errors)
    all_warnings.extend(warnings)
    if errors:
        output.add_log(f"Rule 2 FAILED: {errors}", level="error")
    else:
        output.add_log("Rule 2 PASSED")

    # 3. Word counts
    output.add_log("Checking Rule 3: Word count limits")
    errors, warnings = _validate_word_counts(blocks)
    all_errors.extend(errors)
    all_warnings.extend(warnings)
    if errors:
        output.add_log(f"Rule 3 FAILED: {errors}", level="error")
    else:
        output.add_log("Rule 3 PASSED")

    # 4. Score continuity
    output.add_log("Checking Rule 4: Score continuity")
    errors, warnings = _validate_score_continuity(blocks)
    all_errors.extend(errors)
    all_warnings.extend(warnings)
    if errors:
        output.add_log(f"Rule 4 FAILED: {errors}", level="error")
    else:
        output.add_log("Rule 4 PASSED")

    # 5. Moment coverage
    output.add_log("Checking Rule 5: Moment coverage")
    errors, warnings = _validate_moment_coverage(blocks, total_moments)
    all_errors.extend(errors)
    all_warnings.extend(warnings)
    if errors:
        output.add_log(f"Rule 5 FAILED: {errors}", level="error")
    else:
        output.add_log("Rule 5 PASSED")

    # 6. Key plays
    output.add_log("Checking Rule 6: Key plays")
    errors, warnings = _validate_key_plays(blocks)
    all_errors.extend(errors)
    all_warnings.extend(warnings)
    if errors:
        output.add_log(f"Rule 6 FAILED: {errors}", level="error")
    else:
        output.add_log("Rule 6 PASSED")

    # 7. mini_box population
    output.add_log("Checking Rule 7: mini_box population")
    errors, warnings = _validate_mini_box(blocks)
    all_errors.extend(errors)
    all_warnings.extend(warnings)
    if errors:
        output.add_log(f"Rule 7 FAILED: {errors}", level="error")
    else:
        output.add_log("Rule 7 PASSED")

    # 8. Narrative coverage (final score, winning team, OT presence)
    output.add_log("Checking Rule 8: Narrative coverage")
    coverage_errors, coverage_warnings = _validate_coverage(
        blocks, home_team, away_team, home_score, away_score, has_overtime
    )
    all_warnings.extend(coverage_warnings)
    if coverage_errors:
        output.add_log(f"Rule 8 FAILED: {coverage_errors}", level="error")
    else:
        output.add_log("Rule 8 PASSED")

    # Calculate total words
    total_words = sum(len(b.get("narrative", "").split()) for b in blocks)

    # Structural pass/fail (Rules 1–7); coverage tracked separately
    passed = len(all_errors) == 0
    coverage_passed = len(coverage_errors) == 0

    has_any_failure = not passed or not coverage_passed
    if not has_any_failure:
        decision = "PUBLISH"
    elif regen_attempt < MAX_REGEN_ATTEMPTS:
        decision = "REGENERATE"
    else:
        decision = "FALLBACK"

    if passed and coverage_passed:
        output.add_log(f"VALIDATE_BLOCKS PASSED with {len(all_warnings)} warnings")
    else:
        total_errors = len(all_errors) + len(coverage_errors)
        output.add_log(
            f"VALIDATE_BLOCKS FAILED with {total_errors} errors, "
            f"{len(all_warnings)} warnings → decision={decision}",
            level="error",
        )

    output.add_log(f"Total word count: {total_words}")

    # After validation passes, attach embedded tweets (social enhancement)
    embedded_tweet_selection = None
    if passed:
        league_code = stage_input.game_context.get("sport", "NBA") if stage_input.game_context else "NBA"
        blocks, embedded_tweet_selection = await _attach_embedded_tweets(
            session, game_id, blocks, output, league_code=league_code
        )

    output.data = {
        "blocks_validated": passed,
        "coverage_passed": coverage_passed,
        "coverage_errors": coverage_errors,
        "decision": decision,
        "blocks": blocks,
        "block_count": len(blocks),
        "total_words": total_words,
        "errors": all_errors,
        "warnings": all_warnings,
        # Embedded tweet metadata
        "embedded_tweet_selection": (
            embedded_tweet_selection.to_dict() if embedded_tweet_selection else None
        ),
        # Pass through
        "moments": previous_output.get("moments", []),
        "pbp_events": previous_output.get("pbp_events", []),
        "validated": previous_output.get("validated", True),
        "blocks_grouped": True,
        "blocks_rendered": True,
        # From earlier stages
        "rendered": previous_output.get("rendered"),
    }

    return output
