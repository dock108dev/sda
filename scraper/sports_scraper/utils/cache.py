"""Caching utilities for scrapers (HTML and JSON API responses)."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..logging import logger
from ..utils.datetime_utils import today_et

# Minimum file size (bytes) for a valid scoreboard cache entry
# Empty scoreboards are typically < 5KB, valid ones with games are > 20KB
MIN_SCOREBOARD_SIZE_BYTES = 5000


# Recognized final/completed game states across all leagues.
# Each fetcher extracts the status from its payload and passes it here.
#   NBA: gameStatus int  (1=scheduled, 2=live, 3=final)
#   NHL: gameState str   ("FUT", "PRE", "LIVE", "OFF", "FINAL")
#   NCAAB: normalized str ("scheduled", "live", "final")
FINAL_STATES: set[str | int] = {3, "OFF", "FINAL", "final"}


def should_cache_final(has_data: bool, status: str | int | None) -> bool:
    """Decide whether an API response should be cached.

    Policy: only cache when the game is complete AND the response contains
    meaningful data.  This prevents pregame/live/empty responses from being
    permanently stuck in the no-TTL APICache.

    Args:
        has_data: Whether the payload contains non-empty data
            (e.g. player stats, play events).
        status: Game status extracted from the payload.
            NBA: gameStatus int (1=scheduled, 2=live, 3=final).
            NHL: gameState str ("FUT", "PRE", "LIVE", "OFF", "FINAL").
    """
    return has_data and status in FINAL_STATES


class HTMLCache:
    """Local file cache for scraped HTML pages.

    Stores HTML in a structured directory:
      {cache_dir}/{league}/{season}/{filename}.html

    This ensures we only scrape each page once, making us a good citizen
    and allowing re-parsing without network requests.
    """

    def __init__(self, cache_dir: str | Path, league_code: str, *, force_refresh: bool = False) -> None:
        self.cache_dir = Path(cache_dir)
        self.league_code = league_code
        self.force_refresh = force_refresh

    def _get_cache_path(self, url: str, game_date: date | None = None) -> Path:
        """Build cache path for a URL.

        For boxscore URLs, extracts game key (e.g., 202410220BOS.html).
        For scoreboard URLs, uses date-based filename.
        """
        parsed = urlparse(url)
        path_parts = parsed.path.strip("/").split("/")

        # Build filename from URL
        if "/pbp/" in parsed.path and path_parts[-1].endswith(".html"):
            # Play-by-play URL: .../boxscores/pbp/202410220BOS.html
            filename = f"pbp_{path_parts[-1]}"
        elif "boxscores" in parsed.path and path_parts[-1].endswith(".html"):
            # Boxscore URL: .../boxscores/202410220BOS.html
            filename = path_parts[-1]
        elif "boxscores" in parsed.path and parsed.query:
            # Scoreboard URL: .../boxscores/?month=10&day=22&year=2024
            # Extract date from query params
            filename = f"scoreboard_{parsed.query.replace('&', '_').replace('=', '')}.html"
        else:
            # Fallback: hash the URL
            url_hash = hashlib.md5(url.encode(), usedforsecurity=False).hexdigest()[:12]
            filename = f"page_{url_hash}.html"

        # Drop year/season directory to avoid mis-bucketing when season differs from current year
        return self.cache_dir / self.league_code / filename

    def _is_scoreboard_url(self, url: str) -> bool:
        """Check if the URL is a scoreboard page (vs boxscore or PBP)."""
        return "boxscores" in url and "?" in url and "month=" in url

    def _is_boxscore_url(self, url: str) -> bool:
        """Check if the URL is an individual boxscore page (not scoreboard or PBP)."""
        return (
            "boxscores" in url
            and not self._is_scoreboard_url(url)
            and "/pbp/" not in url
        )

    def get(self, url: str, game_date: date | None = None) -> str | None:
        """Load HTML from cache if it exists.

        Cache is bypassed (returns None) in these cases:
        1. force_refresh is True
        2. Cached scoreboard file is too small (likely empty/no games)
        3. Boxscore for a recent game (last 3 days) cached less than 12 hours ago
        """
        cache_path = self._get_cache_path(url, game_date)

        if cache_path.exists():
            if self.force_refresh:
                logger.info(
                    "cache_refresh_forced",
                    url=url,
                    path=str(cache_path),
                    league=self.league_code,
                )
                return None

            # Check if cached scoreboard is too small (likely empty)
            file_stat = cache_path.stat()
            if self._is_scoreboard_url(url) and file_stat.st_size < MIN_SCOREBOARD_SIZE_BYTES:
                logger.info(
                    "cache_skip_small_scoreboard",
                    url=url,
                    path=str(cache_path),
                    size_bytes=file_stat.st_size,
                    min_size=MIN_SCOREBOARD_SIZE_BYTES,
                    league=self.league_code,
                )
                return None

            # For recent boxscores (last 3 days), bypass cache if file is < 12 hours old.
            # Boxscores are immutable once BR fully populates them, but may be incomplete
            # if cached too soon after game end.
            if self._is_boxscore_url(url) and game_date:
                today = today_et()
                days_ago = (today - game_date).days
                if 0 <= days_ago <= 3:
                    cache_age_hours = (time.time() - file_stat.st_mtime) / 3600
                    if cache_age_hours < 12:
                        logger.info(
                            "cache_skip_recent_boxscore",
                            url=url,
                            path=str(cache_path),
                            game_date=str(game_date),
                            cache_age_hours=round(cache_age_hours, 1),
                            league=self.league_code,
                        )
                        return None

            # Read the cached content
            cached_content = cache_path.read_text(encoding="utf-8")

            # For past-date scoreboards, verify the cache has actual game content
            # This catches cases where we cached a page before games were completed
            if self._is_scoreboard_url(url) and game_date and game_date < today_et():
                if '<div class="game_summary' not in cached_content:
                    logger.info(
                        "cache_skip_no_game_content",
                        url=url,
                        path=str(cache_path),
                        game_date=str(game_date),
                        league=self.league_code,
                    )
                    return None

            logger.info(
                "cache_hit",
                url=url,
                path=str(cache_path),
                league=self.league_code,
            )
            return cached_content
        logger.debug("cache_miss", url=url, path=str(cache_path), league=self.league_code)
        return None

    def put(self, url: str, html: str, game_date: date | None = None) -> Path | None:
        """Save HTML to cache.

        Returns None without saving if:
        - Scoreboard page is too small (likely empty, no games)
        """
        # Don't cache small scoreboards (likely empty/no games)
        if self._is_scoreboard_url(url) and len(html) < MIN_SCOREBOARD_SIZE_BYTES:
            logger.info(
                "cache_skip_save_small_scoreboard",
                url=url,
                size_bytes=len(html),
                min_size=MIN_SCOREBOARD_SIZE_BYTES,
                league=self.league_code,
            )
            return None

        cache_path = self._get_cache_path(url, game_date)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(html, encoding="utf-8")
        logger.info("cache_saved", url=url, path=str(cache_path), size_kb=len(html) // 1024)
        return cache_path

    def clear_recent_scoreboards(self, days: int = 7) -> dict:
        """Clear cached scoreboard files for the last N days.

        This allows manually refreshing recent data before a scrape.

        Args:
            days: Number of days back to clear (default 7)

        Returns:
            Dict with count of deleted files and list of deleted paths
        """
        today = today_et()
        deleted_files = []

        league_cache_dir = self.cache_dir / self.league_code
        if not league_cache_dir.exists():
            logger.info("cache_clear_no_directory", path=str(league_cache_dir))
            return {"deleted_count": 0, "deleted_files": []}

        for i in range(days + 1):
            target_date = today - timedelta(days=i)
            # Scoreboard cache filename pattern: scoreboard_monthX_dayY_year20XX.html
            filename = f"scoreboard_month{target_date.month}_day{target_date.day}_year{target_date.year}.html"
            cache_path = league_cache_dir / filename

            if cache_path.exists():
                try:
                    cache_path.unlink()
                    deleted_files.append(str(cache_path))
                    logger.info(
                        "cache_file_deleted",
                        path=str(cache_path),
                        date=str(target_date),
                        league=self.league_code,
                    )
                except Exception as e:
                    logger.error(
                        "cache_file_delete_failed",
                        path=str(cache_path),
                        error=str(e),
                        league=self.league_code,
                    )

        logger.info(
            "cache_clear_complete",
            league=self.league_code,
            days=days,
            deleted_count=len(deleted_files),
        )

        return {"deleted_count": len(deleted_files), "deleted_files": deleted_files}


class APICache:
    """Local file cache for API JSON responses.

    Stores JSON in a structured directory:
      {cache_dir}/{api_name}/{filename}.json

    This reduces API calls for rate-limited APIs like College Basketball Data API.
    """

    def __init__(self, cache_dir: str | Path, api_name: str) -> None:
        self.cache_dir = Path(cache_dir)
        self.api_name = api_name

    def _get_cache_path(self, cache_key: str) -> Path:
        """Build cache path for a cache key."""
        # Sanitize the key for filesystem
        safe_key = cache_key.replace("/", "_").replace(":", "_").replace("?", "_")
        return self.cache_dir / self.api_name / f"{safe_key}.json"

    def get(self, cache_key: str) -> Any | None:
        """Load JSON from cache if it exists.

        Args:
            cache_key: Unique key for this cached item (e.g., "teams_2026-01-20_2026-01-27")

        Returns:
            Parsed JSON data, or None if not cached
        """
        cache_path = self._get_cache_path(cache_key)

        if cache_path.exists():
            try:
                data = json.loads(cache_path.read_text(encoding="utf-8"))
                logger.info(
                    "api_cache_hit",
                    api=self.api_name,
                    key=cache_key,
                    path=str(cache_path),
                )
                return data
            except (OSError, json.JSONDecodeError) as e:
                logger.warning(
                    "api_cache_read_error",
                    api=self.api_name,
                    key=cache_key,
                    path=str(cache_path),
                    error=str(e),
                )
                return None

        logger.debug("api_cache_miss", api=self.api_name, key=cache_key)
        return None

    def put(self, cache_key: str, data: Any) -> Path | None:
        """Save JSON to cache.

        Args:
            cache_key: Unique key for this cached item
            data: JSON-serializable data to cache

        Returns:
            Path where data was cached, or None on error
        """
        cache_path = self._get_cache_path(cache_key)

        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps(data, indent=2, default=str),
                encoding="utf-8",
            )
            logger.info(
                "api_cache_saved",
                api=self.api_name,
                key=cache_key,
                path=str(cache_path),
                size_kb=len(json.dumps(data)) // 1024,
            )
            return cache_path
        except (OSError, TypeError) as e:
            logger.warning(
                "api_cache_write_error",
                api=self.api_name,
                key=cache_key,
                path=str(cache_path),
                error=str(e),
            )
            return None

    def clear(self, pattern: str | None = None) -> dict:
        """Clear cached files.

        Args:
            pattern: Optional glob pattern to match (e.g., "teams_*"). If None, clears all.

        Returns:
            Dict with count of deleted files
        """
        api_cache_dir = self.cache_dir / self.api_name
        if not api_cache_dir.exists():
            return {"deleted_count": 0, "deleted_files": []}

        deleted_files = []
        glob_pattern = f"{pattern}.json" if pattern else "*.json"

        for cache_file in api_cache_dir.glob(glob_pattern):
            try:
                cache_file.unlink()
                deleted_files.append(str(cache_file))
                logger.info(
                    "api_cache_file_deleted",
                    api=self.api_name,
                    path=str(cache_file),
                )
            except Exception as e:
                logger.warning(
                    "api_cache_delete_error",
                    api=self.api_name,
                    path=str(cache_file),
                    error=str(e),
                )

        return {"deleted_count": len(deleted_files), "deleted_files": deleted_files}
