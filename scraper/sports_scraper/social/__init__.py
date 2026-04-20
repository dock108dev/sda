"""
Social media integration for game timeline posts.

Two-phase collection architecture:
- team_collector: Scrape tweets for teams in a date range (collect)
- tweet_mapper: Assign unmapped tweets to games (map)
"""

from .bluesky_collector import BlueSkyCollector, persist_bluesky_posts
from .cache import SocialRequestCache
from .exceptions import SocialRateLimitError, XCircuitBreakerError
from .models import CollectedPost
from .playwright_collector import PlaywrightXCollector
from .rate_limit import PlatformRateLimiter
from .team_collector import TeamTweetCollector
from .tweet_mapper import get_game_window, get_mapping_stats, map_unmapped_tweets

__all__ = [
    "BlueSkyCollector",
    "persist_bluesky_posts",
    "CollectedPost",
    "PlaywrightXCollector",
    "SocialRateLimitError",
    "XCircuitBreakerError",
    "PlatformRateLimiter",
    "SocialRequestCache",
    "TeamTweetCollector",
    "map_unmapped_tweets",
    "get_game_window",
    "get_mapping_stats",
]
