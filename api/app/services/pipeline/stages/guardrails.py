"""Guardrails & Invariant Enforcement.

This module enforces hard invariants that define the product experience.
Violations are CORRECTNESS BUGS, not stylistic issues.

INVARIANTS (Non-negotiable)
===========================
1. Narrative blocks ≤ 7
2. Embedded tweets ≤ 5
3. Zero required social dependencies

ENFORCEMENT RULES
=================
- Violations must be logged LOUDLY (error level with context)
- Violations must be visible in dev builds
- Logging must include: game_id, block_count, tweet_count, social_presence
- NO silent truncation
- NO auto-correction without surfacing the issue

If a future change violates any invariant, the change is INCORRECT.
These guardrails define the product.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .block_types import MAX_BLOCKS, MIN_BLOCKS
from .tweet_scorer import MAX_EMBEDDED_TWEETS, MAX_TWEETS_PER_BLOCK

logger = logging.getLogger(__name__)


# =============================================================================
# INVARIANT CONSTANTS
# =============================================================================

# Read time targets (seconds)
MIN_READ_TIME_SECONDS = 20
MAX_READ_TIME_SECONDS = 60

# Words per minute for read time calculation
WORDS_PER_MINUTE = 250

# Word limits derived from read time
MAX_TOTAL_WORDS = int(MAX_READ_TIME_SECONDS / 60 * WORDS_PER_MINUTE)  # ~104 words at 60s


# =============================================================================
# VALIDATION RESULT
# =============================================================================


@dataclass
class GuardrailViolation:
    """A single guardrail violation."""

    invariant: str
    message: str
    actual_value: Any
    limit_value: Any
    severity: str = "error"  # "error" or "warning"

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "invariant": self.invariant,
            "message": self.message,
            "actual_value": self.actual_value,
            "limit_value": self.limit_value,
            "severity": self.severity,
        }


@dataclass
class GuardrailResult:
    """Result of guardrail validation."""

    game_id: int | None
    passed: bool
    violations: list[GuardrailViolation] = field(default_factory=list)
    block_count: int = 0
    embedded_tweet_count: int = 0
    total_words: int = 0
    has_social_data: bool = False
    social_required: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "game_id": self.game_id,
            "passed": self.passed,
            "violations": [v.to_dict() for v in self.violations],
            "metrics": {
                "block_count": self.block_count,
                "embedded_tweet_count": self.embedded_tweet_count,
                "total_words": self.total_words,
                "has_social_data": self.has_social_data,
                "social_required": self.social_required,
            },
        }


# =============================================================================
# POST-GENERATION VALIDATION
# =============================================================================


def validate_blocks_post_generation(
    blocks: list[dict[str, Any]],
    game_id: int | None = None,
) -> GuardrailResult:
    """Validate blocks after generation.

    Called after GROUP_BLOCKS and RENDER_BLOCKS stages.

    Checks:
    - Block count in range [MIN_BLOCKS, MAX_BLOCKS]
    - Embedded tweet count ≤ MAX_EMBEDDED_TWEETS
    - Max 1 tweet per block
    - Total word count within read time bounds

    Args:
        blocks: List of block dicts from generation
        game_id: Game identifier for logging

    Returns:
        GuardrailResult with any violations
    """
    violations: list[GuardrailViolation] = []

    # Count metrics
    block_count = len(blocks)
    embedded_tweet_count = sum(
        1 for b in blocks if b.get("embedded_social_post_id") is not None
    )
    total_words = sum(
        len((b.get("narrative") or "").split()) for b in blocks
    )

    # Check block count upper bound
    if block_count > MAX_BLOCKS:
        violations.append(
            GuardrailViolation(
                invariant="MAX_BLOCKS",
                message=f"Block count {block_count} exceeds maximum {MAX_BLOCKS}",
                actual_value=block_count,
                limit_value=MAX_BLOCKS,
                severity="error",
            )
        )

    # Check block count lower bound (warning, not error)
    if block_count < MIN_BLOCKS and block_count > 0:
        violations.append(
            GuardrailViolation(
                invariant="MIN_BLOCKS",
                message=f"Block count {block_count} below minimum {MIN_BLOCKS}",
                actual_value=block_count,
                limit_value=MIN_BLOCKS,
                severity="warning",
            )
        )

    # Check embedded tweet count
    if embedded_tweet_count > MAX_EMBEDDED_TWEETS:
        violations.append(
            GuardrailViolation(
                invariant="MAX_EMBEDDED_TWEETS",
                message=f"Embedded tweet count {embedded_tweet_count} exceeds maximum {MAX_EMBEDDED_TWEETS}",
                actual_value=embedded_tweet_count,
                limit_value=MAX_EMBEDDED_TWEETS,
                severity="error",
            )
        )

    # Check max 1 tweet per block
    for i, block in enumerate(blocks):
        tweet = block.get("embedded_social_post_id")
        if tweet is not None:
            # Check if there are somehow multiple tweets (shouldn't happen)
            if isinstance(tweet, list) and len(tweet) > 1:
                violations.append(
                    GuardrailViolation(
                        invariant="MAX_TWEETS_PER_BLOCK",
                        message=f"Block {i} has {len(tweet)} tweets, max is {MAX_TWEETS_PER_BLOCK}",
                        actual_value=len(tweet),
                        limit_value=MAX_TWEETS_PER_BLOCK,
                        severity="error",
                    )
                )

    # Check total word count (warning for upper bound)
    if total_words > MAX_TOTAL_WORDS:
        violations.append(
            GuardrailViolation(
                invariant="MAX_TOTAL_WORDS",
                message=f"Total word count {total_words} may exceed {MAX_READ_TIME_SECONDS}s read time",
                actual_value=total_words,
                limit_value=MAX_TOTAL_WORDS,
                severity="warning",
            )
        )

    passed = not any(v.severity == "error" for v in violations)

    result = GuardrailResult(
        game_id=game_id,
        passed=passed,
        violations=violations,
        block_count=block_count,
        embedded_tweet_count=embedded_tweet_count,
        total_words=total_words,
        has_social_data=embedded_tweet_count > 0,
        social_required=False,
    )

    # Log result
    _log_validation_result(result, "post_generation")

    return result


def validate_social_independence(
    blocks_with_social: list[dict[str, Any]],
    blocks_without_social: list[dict[str, Any]] | None,
    game_id: int | None = None,
) -> GuardrailResult:
    """Validate that social data is not required.

    Checks that the flow structure is identical with or without social data.
    This ensures zero required social dependencies.

    Args:
        blocks_with_social: Blocks including embedded tweets
        blocks_without_social: Blocks without any social (or None to skip)
        game_id: Game identifier for logging

    Returns:
        GuardrailResult with any violations
    """
    violations: list[GuardrailViolation] = []
    social_required = False

    # If we have both versions, compare them
    if blocks_without_social is not None:
        # Block count should be identical
        if len(blocks_with_social) != len(blocks_without_social):
            violations.append(
                GuardrailViolation(
                    invariant="SOCIAL_INDEPENDENCE",
                    message=f"Block count differs with/without social: {len(blocks_with_social)} vs {len(blocks_without_social)}",
                    actual_value=len(blocks_with_social),
                    limit_value=len(blocks_without_social),
                    severity="error",
                )
            )
            social_required = True

        # Narrative content should be identical (excluding embedded tweets)
        for i, (with_social, without_social) in enumerate(
            zip(blocks_with_social, blocks_without_social, strict=False)
        ):
            # Compare narratives
            if with_social.get("narrative") != without_social.get("narrative"):
                violations.append(
                    GuardrailViolation(
                        invariant="SOCIAL_INDEPENDENCE",
                        message=f"Block {i} narrative differs with/without social",
                        actual_value="with_social",
                        limit_value="without_social",
                        severity="error",
                    )
                )
                social_required = True

            # Compare roles
            if with_social.get("role") != without_social.get("role"):
                violations.append(
                    GuardrailViolation(
                        invariant="SOCIAL_INDEPENDENCE",
                        message=f"Block {i} role differs with/without social",
                        actual_value=with_social.get("role"),
                        limit_value=without_social.get("role"),
                        severity="error",
                    )
                )
                social_required = True

    # Count metrics
    block_count = len(blocks_with_social)
    embedded_tweet_count = sum(
        1 for b in blocks_with_social if b.get("embedded_social_post_id") is not None
    )

    passed = not any(v.severity == "error" for v in violations)

    result = GuardrailResult(
        game_id=game_id,
        passed=passed,
        violations=violations,
        block_count=block_count,
        embedded_tweet_count=embedded_tweet_count,
        has_social_data=embedded_tweet_count > 0,
        social_required=social_required,
    )

    # Log result
    _log_validation_result(result, "social_independence")

    return result


# =============================================================================
# PRE-RENDER VALIDATION
# =============================================================================


def validate_blocks_pre_render(
    blocks: list[dict[str, Any]],
    game_id: int | None = None,
) -> GuardrailResult:
    """Validate blocks before rendering to UI.

    Final validation checkpoint before user sees the content.
    Same checks as post-generation plus structural integrity.

    Args:
        blocks: List of block dicts to render
        game_id: Game identifier for logging

    Returns:
        GuardrailResult with any violations
    """
    # Run standard post-generation checks
    result = validate_blocks_post_generation(blocks, game_id)

    # Additional pre-render checks
    violations = list(result.violations)

    # Check that each block has required fields
    required_fields = ["block_index", "role", "narrative"]
    for i, block in enumerate(blocks):
        missing = [f for f in required_fields if f not in block or block[f] is None]
        if missing:
            violations.append(
                GuardrailViolation(
                    invariant="BLOCK_STRUCTURE",
                    message=f"Block {i} missing required fields: {missing}",
                    actual_value=missing,
                    limit_value=required_fields,
                    severity="error",
                )
            )

    # Check block indices are sequential
    indices = [b.get("block_index", -1) for b in blocks]
    expected = list(range(len(blocks)))
    if indices != expected:
        violations.append(
            GuardrailViolation(
                invariant="BLOCK_SEQUENCE",
                message=f"Block indices not sequential: {indices}",
                actual_value=indices,
                limit_value=expected,
                severity="warning",
            )
        )

    passed = not any(v.severity == "error" for v in violations)

    result = GuardrailResult(
        game_id=game_id,
        passed=passed,
        violations=violations,
        block_count=result.block_count,
        embedded_tweet_count=result.embedded_tweet_count,
        total_words=result.total_words,
        has_social_data=result.has_social_data,
        social_required=result.social_required,
    )

    # Log result
    _log_validation_result(result, "pre_render")

    return result


# =============================================================================
# LOGGING
# =============================================================================


def _log_validation_result(result: GuardrailResult, checkpoint: str) -> None:
    """Log validation result with appropriate level.

    Violations are logged at WARNING level for visibility.
    """
    if result.passed and not result.violations:
        logger.info(
            f"guardrail_validation_passed_{checkpoint}",
            extra={
                "game_id": result.game_id,
                "checkpoint": checkpoint,
                "block_count": result.block_count,
                "embedded_tweet_count": result.embedded_tweet_count,
                "total_words": result.total_words,
                "has_social_data": result.has_social_data,
            },
        )
    else:
        # Log each violation separately for visibility
        for violation in result.violations:
            log_level = logging.ERROR if violation.severity == "error" else logging.WARNING
            logger.log(
                log_level,
                f"GUARDRAIL_VIOLATION_{checkpoint.upper()}",
                extra={
                    "game_id": result.game_id,
                    "checkpoint": checkpoint,
                    "invariant": violation.invariant,
                    "violation_message": violation.message,
                    "actual_value": violation.actual_value,
                    "limit_value": violation.limit_value,
                    "severity": violation.severity,
                    "block_count": result.block_count,
                    "embedded_tweet_count": result.embedded_tweet_count,
                    "has_social_data": result.has_social_data,
                },
            )

        # Summary log
        error_count = sum(1 for v in result.violations if v.severity == "error")
        warning_count = sum(1 for v in result.violations if v.severity == "warning")

        if error_count > 0:
            logger.error(
                f"GUARDRAIL_VALIDATION_FAILED_{checkpoint.upper()}",
                extra={
                    "game_id": result.game_id,
                    "checkpoint": checkpoint,
                    "error_count": error_count,
                    "warning_count": warning_count,
                    "passed": result.passed,
                },
            )
        else:
            logger.warning(
                f"guardrail_validation_warnings_{checkpoint}",
                extra={
                    "game_id": result.game_id,
                    "checkpoint": checkpoint,
                    "warning_count": warning_count,
                    "passed": result.passed,
                },
            )


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def enforce_guardrails(
    blocks: list[dict[str, Any]],
    game_id: int | None = None,
    checkpoint: str = "default",
) -> GuardrailResult:
    """Main entry point for guardrail enforcement.

    Use this function to validate blocks at any checkpoint.

    Args:
        blocks: List of block dicts to validate
        game_id: Game identifier for logging
        checkpoint: Name of validation checkpoint

    Returns:
        GuardrailResult with any violations
    """
    if checkpoint == "post_generation":
        return validate_blocks_post_generation(blocks, game_id)
    elif checkpoint == "pre_render":
        return validate_blocks_pre_render(blocks, game_id)
    else:
        return validate_blocks_post_generation(blocks, game_id)


def assert_guardrails(
    blocks: list[dict[str, Any]],
    game_id: int | None = None,
) -> None:
    """Assert that guardrails pass, raising if they don't.

    Use this for strict enforcement where failures should halt execution.

    Args:
        blocks: List of block dicts to validate
        game_id: Game identifier for logging

    Raises:
        GuardrailViolationError: If any error-level violations occur
    """
    result = validate_blocks_post_generation(blocks, game_id)
    if not result.passed:
        error_violations = [v for v in result.violations if v.severity == "error"]
        raise GuardrailViolationError(
            f"Guardrail violations for game {game_id}: "
            + "; ".join(v.message for v in error_violations),
            result=result,
        )


class GuardrailViolationError(Exception):
    """Raised when guardrail validation fails with error-level violations."""

    def __init__(self, message: str, result: GuardrailResult):
        super().__init__(message)
        self.result = result
