"""Embedded tweet selection for collapsed game flow.

EMBEDDED TWEET CONTRACT
=======================
Embedded tweets are the ONLY social elements allowed in the collapsed game flow.
They act as reaction beats, not narrative drivers.

Key principles:
1. OPTIONAL: Flow must read correctly with zero embedded tweets
2. LIMITED: Max 5 per game, max 1 per block
3. DETERMINISTIC: Selection is reproducible given same inputs
4. NON-STRUCTURAL: Tweets never create/split blocks

Embedded tweets may enhance pacing but must NEVER:
- Add length to the flow
- Compromise the 20-60 second read invariant
- Drive narrative decisions
- Couple to specific plays or moments

Related modules:
- tweet_scorer.py: Data structures and scoring
- tweet_temporal.py: Wall-clock timing and block assignment
- block_types.py: Block structures
- social_events.py: Social post processing
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

# Public API: re-export from sub-modules to provide a single import surface
from .tweet_scorer import (
    MAX_EMBEDDED_TWEETS,
    MAX_TWEETS_PER_BLOCK,
    MIN_EMBEDDED_TWEETS,
    PREFERRED_MAX_EMBEDDED,
    PREFERRED_MIN_EMBEDDED,
    BlockTweetAssignment,
    DefaultTweetScorer,
    EmbeddedTweetSelection,
    ScoredTweet,
    TweetScorer,
)
from .tweet_temporal import (
    DEFAULT_TWEET_LAG_SECONDS,
    assign_tweets_to_blocks_by_time,
)

if TYPE_CHECKING:
    from ....db import AsyncSession

logger = logging.getLogger(__name__)

# Make re-exports visible to importers
__all__ = [
    # Constants
    "MIN_EMBEDDED_TWEETS",
    "MAX_EMBEDDED_TWEETS",
    "PREFERRED_MIN_EMBEDDED",
    "PREFERRED_MAX_EMBEDDED",
    "MAX_TWEETS_PER_BLOCK",
    "DEFAULT_TWEET_LAG_SECONDS",
    # Data structures
    "ScoredTweet",
    "EmbeddedTweetSelection",
    "BlockTweetAssignment",
    # Scorer
    "TweetScorer",
    "DefaultTweetScorer",
    # Temporal matching
    "assign_tweets_to_blocks_by_time",
    # Selection pipeline
    "select_embedded_tweets",
    "apply_embedded_tweets_to_blocks",
    "select_and_assign_embedded_tweets",
    "load_and_attach_embedded_tweets",
]


# =============================================================================
# EMBEDDED TWEET SELECTION
# =============================================================================


def select_embedded_tweets(
    tweets: Sequence[dict[str, Any]],
    game_start: datetime,
    scorer: TweetScorer | None = None,
) -> EmbeddedTweetSelection:
    """Score all candidate tweets for embedded display.

    Scores every tweet and returns them sorted by posted_at.
    Actual block assignment is handled by assign_tweets_to_blocks_by_time.

    Args:
        tweets: List of tweet dicts to select from
        game_start: Game start time
        scorer: Tweet scorer (uses DefaultTweetScorer if None)

    Returns:
        EmbeddedTweetSelection with all scored tweets
    """
    if scorer is None:
        scorer = DefaultTweetScorer()

    # Handle empty input
    if not tweets:
        return EmbeddedTweetSelection(
            tweets=[],
            total_candidates=0,
            selection_method="none",
        )

    # Score all tweets
    scored_tweets: list[ScoredTweet] = []
    for tweet in tweets:
        # Skip tweets with empty text
        text = tweet.get("text", "")
        if not text or not text.strip():
            continue

        # Parse posted_at
        posted_at = tweet.get("posted_at")
        if isinstance(posted_at, str):
            try:
                posted_at = datetime.fromisoformat(posted_at.replace("Z", "+00:00"))
            except ValueError:
                continue
        elif not isinstance(posted_at, datetime):
            continue

        raw_id = tweet.get("id")
        if raw_id is None:
            continue
        try:
            tweet_id = int(raw_id)
        except (ValueError, TypeError):
            continue

        score = scorer.score(tweet)

        scored_tweet = ScoredTweet(
            tweet_id=tweet_id,
            posted_at=posted_at,
            text=text,
            author=tweet.get("author", ""),
            phase=tweet.get("phase", "unknown"),
            score=score,
            has_media=bool(tweet.get("has_media")),
            media_type=tweet.get("media_type"),
            engagement=tweet.get("engagement", 0),
            is_verified=tweet.get("is_verified", False),
            is_team_account=tweet.get("is_team_account", False),
        )
        scored_tweets.append(scored_tweet)

    total_candidates = len(scored_tweets)

    # Sort by time for deterministic ordering
    scored_tweets.sort(key=lambda t: t.posted_at)

    return EmbeddedTweetSelection(
        tweets=scored_tweets,
        total_candidates=total_candidates,
        selection_method="scored",
    )


def apply_embedded_tweets_to_blocks(
    blocks: list[dict[str, Any]],
    assignments: list[BlockTweetAssignment],
) -> list[dict[str, Any]]:
    """Apply embedded tweet assignments to block dicts.

    Sets embedded_social_post_id (display tweet) and
    additional_social_post_ids (extra context) on each block.
    Does NOT modify block structure (no splitting, no new blocks).

    Args:
        blocks: List of block dicts
        assignments: Tweet assignments from assign_tweets_to_blocks_by_time

    Returns:
        Updated blocks with embedded tweet fields
    """
    # Create a map of block_index -> assignment
    assignment_map: dict[int, BlockTweetAssignment] = {
        a.block_index: a for a in assignments
    }

    updated_blocks = []
    for block in blocks:
        block_copy = dict(block)
        block_index = block_copy.get("block_index", 0)

        assignment = assignment_map.get(block_index)
        if assignment and assignment.tweet:
            block_copy["embedded_social_post_id"] = assignment.tweet.tweet_id
            block_copy["additional_social_post_ids"] = [
                t.tweet_id for t in assignment.additional_tweets
            ]
        else:
            block_copy["embedded_social_post_id"] = None
            block_copy["additional_social_post_ids"] = []

        updated_blocks.append(block_copy)

    return updated_blocks


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def select_and_assign_embedded_tweets(
    tweets: Sequence[dict[str, Any]],
    blocks: list[dict[str, Any]],
    game_start: datetime,
    league_code: str = "NBA",
    scorer: TweetScorer | None = None,
    tweet_lag_seconds: int = DEFAULT_TWEET_LAG_SECONDS,
) -> tuple[list[dict[str, Any]], EmbeddedTweetSelection]:
    """Complete embedded tweet pipeline: score and assign by temporal match.

    Convenience function that combines:
    1. select_embedded_tweets -- score all candidates
    2. assign_tweets_to_blocks_by_time -- temporal block matching
    3. apply_embedded_tweets_to_blocks -- write IDs onto block dicts

    Args:
        tweets: Available tweets to select from
        blocks: Narrative blocks to assign tweets to
        game_start: Game start time
        league_code: League code for period timing ("NBA", "NHL", "NCAAB")
        scorer: Optional custom scorer
        tweet_lag_seconds: Seconds to subtract from tweet timestamps to
            compensate for posting delay (default 90s).

    Returns:
        Tuple of (updated_blocks, selection_result)
    """
    # Score all tweets
    selection = select_embedded_tweets(tweets, game_start, scorer)

    # Assign to blocks by temporal matching
    assignments = assign_tweets_to_blocks_by_time(
        selection.tweets, blocks, game_start, league_code, tweet_lag_seconds
    )

    # Apply to blocks
    updated_blocks = apply_embedded_tweets_to_blocks(blocks, assignments)

    return updated_blocks, selection


# =============================================================================
# SHARED SSOT: Load + Attach (used by pipeline and backfill)
# =============================================================================


async def load_and_attach_embedded_tweets(
    session: AsyncSession,
    game_id: int,
    blocks: list[dict[str, Any]],
    league_code: str = "NBA",
    scorer: TweetScorer | None = None,
    tweet_lag_seconds: int = DEFAULT_TWEET_LAG_SECONDS,
) -> tuple[list[dict[str, Any]], EmbeddedTweetSelection | None]:
    """Load social posts for a game and attach to blocks.

    Single source of truth called from both:
    - validate_blocks._attach_embedded_tweets (pipeline path)
    - backfill_embedded_tweets.backfill_embedded_tweets_for_game (backfill path)

    Args:
        session: Async database session.
        game_id: Game ID to load social posts for.
        blocks: Blocks to attach tweets to.
        league_code: League code for period timing.
        scorer: Optional custom scorer.
        tweet_lag_seconds: Seconds to subtract from tweet timestamps to
            compensate for posting delay (default 90s).

    Returns:
        Tuple of (updated blocks, EmbeddedTweetSelection or None).
    """
    from ....db.social import TeamSocialPost
    from ....db.sports import SportsGame

    # Load game for game_date (scheduled start time)
    game_result = await session.execute(
        select(SportsGame).where(SportsGame.id == game_id)
    )
    game = game_result.scalar_one_or_none()

    if not game:
        logger.debug("load_and_attach_no_game", extra={"game_id": game_id})
        return blocks, None

    game_start = game.game_date
    if game_start and game_start.tzinfo is None:
        game_start = game_start.replace(tzinfo=UTC)

    # Load mapped social posts
    social_result = await session.execute(
        select(TeamSocialPost)
        .where(
            TeamSocialPost.game_id == game_id,
            TeamSocialPost.mapping_status == "mapped",
        )
        .order_by(TeamSocialPost.posted_at)
    )
    social_posts = social_result.scalars().all()

    if not social_posts:
        return blocks, None

    # Convert to dict format and filter to in_game only
    tweets: list[dict[str, Any]] = []
    for post in social_posts:
        if not post.tweet_text:
            continue
        tweets.append({
            "id": post.id,
            "posted_at": post.posted_at,
            "text": post.tweet_text,
            "author": post.source_handle or "",
            "phase": post.game_phase or "in_game",
            "has_media": post.has_video or bool(post.image_url),
            "media_type": post.media_type,
            "post_url": post.post_url,
            "is_team_account": bool(post.source_handle),
        })

    tweets = [t for t in tweets if t["phase"] == "in_game"]

    if not tweets:
        return blocks, None

    updated_blocks, selection = select_and_assign_embedded_tweets(
        tweets=tweets,
        blocks=blocks,
        game_start=game_start,
        league_code=league_code,
        scorer=scorer,
        tweet_lag_seconds=tweet_lag_seconds,
    )
    return updated_blocks, selection
