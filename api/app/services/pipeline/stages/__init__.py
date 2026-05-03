"""Pipeline stage implementations."""

from .analyze_drama import execute_analyze_drama
from .classify_game_shape import execute_classify_game_shape
from .embedded_tweets import (
    DefaultTweetScorer,
    apply_embedded_tweets_to_blocks,
    select_and_assign_embedded_tweets,
    select_embedded_tweets,
)
from .finalize_moments import execute_finalize_moments
from .generate_moments import execute_generate_moments
from .group_blocks import execute_group_blocks
from .guardrails import (
    MAX_BLOCKS,
    MAX_EMBEDDED_TWEETS,
    GuardrailViolationError,
    assert_guardrails,
    enforce_guardrails,
    validate_blocks_post_generation,
    validate_blocks_pre_render,
    validate_social_independence,
)
from .normalize_pbp import execute_normalize_pbp
from .render_blocks import execute_render_blocks
from .validate_blocks import execute_validate_blocks
from .validate_moments import execute_validate_moments

__all__ = [
    "execute_normalize_pbp",
    "execute_generate_moments",
    "execute_validate_moments",
    "execute_analyze_drama",
    "execute_classify_game_shape",
    "execute_group_blocks",
    "execute_render_blocks",
    "execute_validate_blocks",
    "execute_finalize_moments",
    # Embedded tweet selection
    "select_embedded_tweets",
    "apply_embedded_tweets_to_blocks",
    "select_and_assign_embedded_tweets",
    "DefaultTweetScorer",
    # Guardrails
    "validate_blocks_post_generation",
    "validate_blocks_pre_render",
    "validate_social_independence",
    "enforce_guardrails",
    "assert_guardrails",
    "GuardrailViolationError",
    "MAX_BLOCKS",
    "MAX_EMBEDDED_TWEETS",
]
