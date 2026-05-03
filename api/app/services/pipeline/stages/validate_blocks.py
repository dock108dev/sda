"""VALIDATE_BLOCKS stage — validates rendered blocks and attaches embedded tweets.

Implementation is split across ``validate_blocks_*.py`` modules. See module docstrings
there for rule details (block counts, roles, coverage, mini_box, phrase density).
"""

from __future__ import annotations

import logging
from typing import Any

from ....db import AsyncSession
from ..helpers.flow_debug_logger import get_logger as get_flow_debug_logger
from ..metrics import increment_fallback, increment_regen
from ..models import StageInput, StageOutput
from .block_types import MAX_BLOCKS, MIN_BLOCKS
from .density import check_information_density
from .embedded_tweets import load_and_attach_embedded_tweets
from .validate_blocks_constants import (
    MAX_REGEN_ATTEMPTS,
    MINI_BOX_STAT_FIELDS,
    MINI_BOX_UNKNOWN,
    REQUIRED_BLOCK_TYPES,
)
from .validate_blocks_phrases import check_banned_phrases, check_generic_phrase_density
from .validate_blocks_resolution import (
    check_resolution_specificity,
    get_final_window_plays,
)
from .validate_blocks_rules import (
    validate_block_count,
    validate_coverage,
    validate_key_plays,
    validate_mini_box,
    validate_moment_coverage,
    validate_required_block_types,
    validate_role_constraints,
    validate_score_continuity,
    validate_word_counts,
)
from .validate_blocks_segments import (
    validate_blowout_late_leverage,
    validate_evidence_present,
    validate_lead_consistency,
    validate_low_event_drama,
    validate_reason_present,
)
from .validate_blocks_text import (
    check_ot_present,
    check_score_present,
    check_team_present,
    count_sentences,
)

logger = logging.getLogger(__name__)

# --- Backward-compatible underscore aliases (tests import these names) ---
_check_ot_present = check_ot_present
_check_score_present = check_score_present
_check_team_present = check_team_present
_count_sentences = count_sentences
_check_resolution_specificity = check_resolution_specificity
_get_final_window_plays = get_final_window_plays
_validate_block_count = validate_block_count
_validate_coverage = validate_coverage
_validate_key_plays = validate_key_plays
_validate_mini_box = validate_mini_box
_validate_moment_coverage = validate_moment_coverage
_validate_required_block_types = validate_required_block_types
_validate_role_constraints = validate_role_constraints
_validate_score_continuity = validate_score_continuity
_validate_word_counts = validate_word_counts
_check_generic_phrase_density = check_generic_phrase_density
_check_banned_phrases = check_banned_phrases
_validate_lead_consistency = validate_lead_consistency
_validate_blowout_late_leverage = validate_blowout_late_leverage
_validate_low_event_drama = validate_low_event_drama
_validate_reason_present = validate_reason_present
_validate_evidence_present = validate_evidence_present


async def _attach_embedded_tweets(
    session: AsyncSession,
    game_id: int,
    blocks: list[dict[str, Any]],
    output: StageOutput,
    league_code: str = "NBA",
) -> tuple[list[dict[str, Any]], Any]:
    """Load social posts and attach embedded tweets to blocks."""
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
    """Execute VALIDATE_BLOCKS: structural checks, coverage, density, embedded tweets."""
    output = StageOutput(data={})
    game_id = stage_input.game_id

    output.add_log(f"Starting VALIDATE_BLOCKS for game {game_id}")

    previous_output = stage_input.previous_output
    if not previous_output:
        raise ValueError("VALIDATE_BLOCKS requires previous stage output")

    blocks_rendered = previous_output.get("blocks_rendered")
    if blocks_rendered is not True:
        raise ValueError(
            f"VALIDATE_BLOCKS requires RENDER_BLOCKS to complete. Got blocks_rendered={blocks_rendered}"
        )

    blocks = previous_output.get("blocks", [])
    if not blocks:
        raise ValueError("No blocks in previous stage output")

    total_moments = previous_output.get("total_moments", 0)
    if not total_moments:
        moments = previous_output.get("moments", [])
        total_moments = len(moments)

    output.add_log(f"Validating {len(blocks)} blocks covering {total_moments} moments")

    ctx = stage_input.game_context or {}
    home_team = ctx.get("home_team", "")
    away_team = ctx.get("away_team", "")
    has_overtime = bool(ctx.get("has_overtime", False))
    regen_attempt = int(ctx.get("regen_attempt", 0))
    sport = ctx.get("sport", "UNKNOWN")

    home_score_ctx = ctx.get("home_score")
    if home_score_ctx is None and blocks:
        last_score = blocks[-1].get("score_after", [0, 0])
        home_score = int(last_score[0]) if last_score else 0
        away_score = int(last_score[1]) if last_score else 0
    else:
        home_score = int(home_score_ctx or 0)
        away_score = int(ctx.get("away_score") or 0)

    all_errors: list[str] = []
    all_warnings: list[str] = []

    output.add_log("Checking Rule 1: Block count in range [3, 7]")
    errors, warnings = validate_block_count(blocks)
    all_errors.extend(errors)
    all_warnings.extend(warnings)
    if errors:
        logger.warning(
            "block_count_out_of_range",
            extra={
                "game_id": game_id,
                "observed": len(blocks),
                "expected_min": MIN_BLOCKS,
                "expected_max": MAX_BLOCKS,
            },
        )
        output.add_log(f"Rule 1 FAILED: {errors}", level="error")
    else:
        output.add_log("Rule 1 PASSED")

    output.add_log("Checking Rule 2: Role constraints")
    errors, warnings = validate_role_constraints(blocks)
    all_errors.extend(errors)
    all_warnings.extend(warnings)
    type_errors, type_warnings = validate_required_block_types(blocks)
    all_errors.extend(type_errors)
    all_warnings.extend(type_warnings)
    if errors or type_errors:
        output.add_log(f"Rule 2 FAILED: {errors + type_errors}", level="error")
    else:
        output.add_log("Rule 2 PASSED")

    output.add_log("Checking Rule 3: Word count limits")
    errors, warnings = validate_word_counts(blocks)
    all_errors.extend(errors)
    all_warnings.extend(warnings)
    if errors:
        output.add_log(f"Rule 3 FAILED: {errors}", level="error")
    else:
        output.add_log("Rule 3 PASSED")

    output.add_log("Checking Rule 4: Score continuity")
    errors, warnings = validate_score_continuity(blocks)
    all_errors.extend(errors)
    all_warnings.extend(warnings)
    if errors:
        output.add_log(f"Rule 4 FAILED: {errors}", level="error")
    else:
        output.add_log("Rule 4 PASSED")

    output.add_log("Checking Rule 5: Moment coverage")
    errors, warnings = validate_moment_coverage(blocks, total_moments)
    all_errors.extend(errors)
    all_warnings.extend(warnings)
    if errors:
        output.add_log(f"Rule 5 FAILED: {errors}", level="error")
    else:
        output.add_log("Rule 5 PASSED")

    output.add_log("Checking Rule 6: Key plays")
    errors, warnings = validate_key_plays(blocks)
    all_errors.extend(errors)
    all_warnings.extend(warnings)
    if errors:
        output.add_log(f"Rule 6 FAILED: {errors}", level="error")
    else:
        output.add_log("Rule 6 PASSED")

    output.add_log("Checking Rule 7: mini_box population")
    errors, warnings = validate_mini_box(blocks)
    all_errors.extend(errors)
    all_warnings.extend(warnings)
    if errors:
        output.add_log(f"Rule 7 FAILED: {errors}", level="error")
    else:
        output.add_log("Rule 7 PASSED")

    output.add_log("Checking Rule 8: Narrative coverage")
    coverage_errors, coverage_warnings = validate_coverage(
        blocks, home_team, away_team, home_score, away_score, has_overtime
    )
    all_warnings.extend(coverage_warnings)
    if coverage_errors:
        output.add_log(f"Rule 8 FAILED: {coverage_errors}", level="error")
    else:
        output.add_log("Rule 8 PASSED")

    _, density_warnings = check_generic_phrase_density(blocks)
    all_warnings.extend(density_warnings)
    if density_warnings:
        output.add_log(
            f"Rule 9 WARNING: generic phrase density exceeded in {len(density_warnings)} block(s)",
            level="warning",
        )
    else:
        output.add_log("Rule 9 PASSED")

    banned_errors, speculation_warnings = check_banned_phrases(blocks)
    all_errors.extend(banned_errors)
    all_warnings.extend(speculation_warnings)
    if banned_errors:
        output.add_log(
            f"Rule 9b FAILED: banned phrases in {len(banned_errors)} block(s) → {banned_errors}",
            level="error",
        )
    elif speculation_warnings:
        output.add_log(
            f"Rule 9b WARNING: speculation language in {len(speculation_warnings)} block(s)",
            level="warning",
        )
    else:
        output.add_log("Rule 9b PASSED")

    pbp_events_for_check = previous_output.get("pbp_events", [])
    sport_for_check = (stage_input.game_context or {}).get("sport", "")
    _, specificity_warnings = check_resolution_specificity(
        blocks, pbp_events_for_check, sport_for_check
    )
    all_warnings.extend(specificity_warnings)
    if specificity_warnings:
        output.add_log(
            "Rule 10 WARNING: RESOLUTION block lacks traceable final-window play reference",
            level="warning",
        )
    else:
        output.add_log("Rule 10 PASSED")

    density_score, density_passed, density_warnings = check_information_density(
        blocks,
        sport=sport,
        home_team=home_team,
        away_team=away_team,
    )
    all_warnings.extend(density_warnings)
    if density_warnings:
        output.add_log(
            f"Rule 11 WARNING: information density check failed "
            f"(jaccard={density_score:.2f}) — narrative may be template regurgitation",
            level="warning",
        )
    else:
        output.add_log(f"Rule 11 PASSED (jaccard={density_score:.2f})")

    archetype = previous_output.get("archetype")

    output.add_log("Checking Rule 12: Lead consistency across block boundaries")
    errors, warnings = validate_lead_consistency(blocks)
    all_errors.extend(errors)
    all_warnings.extend(warnings)
    if errors:
        output.add_log(f"Rule 12 FAILED: {errors}", level="error")
    else:
        output.add_log("Rule 12 PASSED")

    output.add_log("Checking Rule 13: Blowout late-block leverage language")
    errors, warnings = validate_blowout_late_leverage(blocks, archetype)
    all_errors.extend(errors)
    all_warnings.extend(warnings)
    if errors:
        output.add_log(f"Rule 13 FAILED: {errors}", level="error")
    else:
        output.add_log("Rule 13 PASSED")

    output.add_log("Checking Rule 14: Low-event drama descriptors")
    errors, warnings = validate_low_event_drama(blocks, archetype)
    all_errors.extend(errors)
    all_warnings.extend(warnings)
    if errors:
        output.add_log(f"Rule 14 FAILED: {errors}", level="error")
    else:
        output.add_log("Rule 14 PASSED")

    _, reason_warnings = validate_reason_present(blocks)
    all_warnings.extend(reason_warnings)
    if reason_warnings:
        output.add_log(
            f"Rule 15 WARNING: {len(reason_warnings)} block(s) missing or short reason",
            level="warning",
        )
    else:
        output.add_log("Rule 15 PASSED")

    _, evidence_warnings = validate_evidence_present(blocks)
    all_warnings.extend(evidence_warnings)
    if evidence_warnings:
        output.add_log(
            f"Rule 16 WARNING: {len(evidence_warnings)} block(s) assert without evidence",
            level="warning",
        )
    else:
        output.add_log("Rule 16 PASSED")

    total_words = sum(len(b.get("narrative", "").split()) for b in blocks)

    passed = len(all_errors) == 0
    coverage_passed = len(coverage_errors) == 0

    has_any_failure = not passed or not coverage_passed
    if not has_any_failure:
        decision = "PUBLISH"
    elif regen_attempt < MAX_REGEN_ATTEMPTS:
        decision = "REGENERATE"
        reason = "coverage_fail" if coverage_errors else "quality_fail"
        increment_regen(sport, reason)
    else:
        decision = "FALLBACK"
        fallback_reason = "coverage_fail" if coverage_errors else "quality_fail"
        increment_fallback(sport, fallback_reason)

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

    # Record validation + decision into the structured per-game debug log.
    debug = get_flow_debug_logger(stage_input.run_id)
    if debug is not None:
        validation_status = "passed" if (passed and coverage_passed) else "failed"
        merged_errors = list(all_errors) + list(coverage_errors)
        debug.record_validation_result(
            status=validation_status,
            warnings=all_warnings,
            errors=merged_errors,
        )
        if decision == "FALLBACK":
            fb_reason = "coverage_fail" if coverage_errors else "quality_fail"
            debug.record_generation_result(decision, fallback_reason=fb_reason)
        else:
            debug.record_generation_result(decision)

    fallback_used = False
    if decision == "FALLBACK":
        from .templates import GameMiniBox as _TMiniBox
        from .templates import TemplateEngine as _TEngine

        _ctx = stage_input.game_context or {}
        _home_team = _ctx.get("home_team_name", _ctx.get("home_team", "Home Team"))
        _away_team = _ctx.get("away_team_name", _ctx.get("away_team", "Away Team"))
        _tmb = _TMiniBox(
            home_team=_home_team,
            away_team=_away_team,
            home_score=home_score,
            away_score=away_score,
            sport=sport,
            has_overtime=has_overtime,
            total_moments=total_moments,
        )
        blocks = _TEngine.render(sport, _tmb)
        total_words = sum(len(b.get("narrative", "").split()) for b in blocks)
        passed = True
        coverage_passed = True
        coverage_errors = []
        decision = "PUBLISH"
        fallback_used = True
        output.add_log(
            f"FALLBACK: generated {len(blocks)} template blocks for sport={sport}, "
            f"total_words={total_words}"
        )

    embedded_tweet_selection = None
    if passed:
        league_code = (
            stage_input.game_context.get("sport", "NBA") if stage_input.game_context else "NBA"
        )
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
        "fallback_used": fallback_used,
        "information_density_score": round(density_score, 4),
        "information_density_warning": not density_passed,
        "embedded_tweet_selection": (
            embedded_tweet_selection.to_dict() if embedded_tweet_selection else None
        ),
        "moments": previous_output.get("moments", []),
        "pbp_events": previous_output.get("pbp_events", []),
        "validated": previous_output.get("validated", True),
        "blocks_grouped": True,
        "blocks_rendered": True,
        "rendered": previous_output.get("rendered"),
    }

    return output


__all__ = [
    "execute_validate_blocks",
    "MINI_BOX_STAT_FIELDS",
    "MINI_BOX_UNKNOWN",
    "REQUIRED_BLOCK_TYPES",
    "_check_banned_phrases",
    "_check_generic_phrase_density",
    "_check_ot_present",
    "_check_resolution_specificity",
    "_check_score_present",
    "_check_team_present",
    "_count_sentences",
    "_get_final_window_plays",
    "_validate_block_count",
    "_validate_blowout_late_leverage",
    "_validate_coverage",
    "_validate_evidence_present",
    "_validate_key_plays",
    "_validate_lead_consistency",
    "_validate_low_event_drama",
    "_validate_mini_box",
    "_validate_moment_coverage",
    "_validate_reason_present",
    "_validate_required_block_types",
    "_validate_role_constraints",
    "_validate_score_continuity",
    "_validate_word_counts",
]
