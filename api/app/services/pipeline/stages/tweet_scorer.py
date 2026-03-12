"""Tweet scoring data structures and scorer implementations.

Data structures for scored tweets, selection results, and block assignments.
TweetScorer protocol and DefaultTweetScorer implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

# =============================================================================
# SELECTION LIMIT CONSTANTS
# =============================================================================

MIN_EMBEDDED_TWEETS = 0  # Embedded tweets are optional
MAX_EMBEDDED_TWEETS = 5  # Hard cap per game
PREFERRED_MIN_EMBEDDED = 2  # Prefer at least 2 if available
PREFERRED_MAX_EMBEDDED = 5  # Prefer up to 5

MAX_TWEETS_PER_BLOCK = 1  # Hard cap: 1 tweet per block


# =============================================================================
# DATA STRUCTURES
# =============================================================================


@dataclass
class ScoredTweet:
    """A tweet with its computed score and metadata.

    This is the internal representation used during selection.
    The score determines priority when enforcing caps.
    """

    tweet_id: int
    posted_at: datetime
    text: str
    author: str
    phase: str
    score: float  # Computed by scorer
    has_media: bool = False
    media_type: str | None = None

    # Optional metadata for scoring
    engagement: int = 0
    is_verified: bool = False
    is_team_account: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "tweet_id": self.tweet_id,
            "posted_at": self.posted_at.isoformat(),
            "text": self.text,
            "author": self.author,
            "phase": self.phase,
            "score": self.score,
            "has_media": self.has_media,
            "media_type": self.media_type,
        }


@dataclass
class EmbeddedTweetSelection:
    """Result of the embedded tweet selection process.

    Contains selected tweets and metadata about the selection.
    """

    tweets: list[ScoredTweet]
    total_candidates: int
    selection_method: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "tweets": [t.to_dict() for t in self.tweets],
            "total_candidates": self.total_candidates,
            "selection_method": self.selection_method,
            "selected_count": len(self.tweets),
        }


@dataclass
class BlockTweetAssignment:
    """Assignment of embedded tweets to narrative blocks.

    Each block gets at most one display tweet (highest-scored temporal match)
    plus additional tweets for consuming apps to use as context.
    """

    block_index: int
    tweet: ScoredTweet | None  # Best tweet for display (None if no match)
    additional_tweets: list[ScoredTweet] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "block_index": self.block_index,
            "tweet": self.tweet.to_dict() if self.tweet else None,
            "additional_tweets": [t.to_dict() for t in self.additional_tweets],
        }


# =============================================================================
# SCORER PROTOCOL (Pluggable)
# =============================================================================


class TweetScorer(Protocol):
    """Protocol for tweet scoring implementations.

    Scoring must be:
    - Deterministic given the same inputs
    - Independent of play/moment/narrative data
    - Replaceable without changing selection logic
    """

    def score(self, tweet: dict[str, Any]) -> float:
        """Compute a score for a tweet.

        Args:
            tweet: Tweet data dict with fields like text, author, engagement

        Returns:
            Score as float (higher = more likely to be selected)
        """
        ...


class DefaultTweetScorer:
    """Default tweet scorer using simple heuristics.

    Scoring factors (all configurable):
    - Media presence: +2.0
    - Team account: +1.5
    - Verified account: +0.5
    - Engagement (normalized): +0-2.0
    - Text length (sweet spot): +0-1.0
    """

    def __init__(
        self,
        media_weight: float = 2.0,
        team_account_weight: float = 1.5,
        verified_weight: float = 0.5,
        engagement_weight: float = 2.0,
        length_weight: float = 1.0,
    ):
        self.media_weight = media_weight
        self.team_account_weight = team_account_weight
        self.verified_weight = verified_weight
        self.engagement_weight = engagement_weight
        self.length_weight = length_weight

    def score(self, tweet: dict[str, Any]) -> float:
        """Compute score using weighted heuristics."""
        score = 0.0

        # Media presence (images/videos are engaging)
        if tweet.get("has_media"):
            score += self.media_weight

        # Team account (authoritative source)
        if tweet.get("is_team_account"):
            score += self.team_account_weight

        # Verified account (credibility)
        if tweet.get("is_verified"):
            score += self.verified_weight

        # Engagement (normalized to 0-1 scale, capped at 1000)
        engagement = tweet.get("engagement", 0)
        if engagement > 0:
            normalized = min(engagement / 1000, 1.0)
            score += normalized * self.engagement_weight

        # Text length (prefer medium-length tweets: 50-150 chars)
        text = tweet.get("text", "")
        text_len = len(text) if text else 0
        if 50 <= text_len <= 150:
            score += self.length_weight
        elif 30 <= text_len <= 200:
            score += self.length_weight * 0.5

        return score
