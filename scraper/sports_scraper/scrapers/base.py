"""Base classes for sport-specific scrapers with HTML caching."""

from __future__ import annotations

import random
import time
from collections.abc import Iterable, Iterator, Sequence
from datetime import date, timedelta

import httpx
from bs4 import BeautifulSoup, Tag
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from ..config import settings
from ..logging import logger
from ..models import NormalizedGame, NormalizedPlayByPlay, TeamIdentity
from ..normalization import normalize_team_name
from ..utils.cache import HTMLCache
from ..utils.date_utils import season_from_date
from ..utils.parsing import parse_int


class ScraperError(RuntimeError):
    """Raised when a scraper encounters an unrecoverable error."""


class NoGamesFoundError(ScraperError):
    """Raised when no games are found for a date (e.g., redirect detected).

    This is not retried - it's an expected condition, not a failure.
    """


# HTMLCache moved to utils/cache.py


class BaseSportsReferenceScraper:
    """Shared utilities for scraping Sports Reference scoreboards.

    Features:
    - Local HTML cache (only fetch each page once)
    - Polite scraping (5-9 second random delays)
    - Automatic retry with exponential backoff
    """

    sport: str  # e.g., "nba" or "cbb"
    league_code: str
    base_url: str

    def __init__(self, timeout_seconds: int | None = None) -> None:
        timeout = timeout_seconds or settings.scraper_config.request_timeout_seconds
        self.client = httpx.Client(
            timeout=timeout,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
            }
        )
        self._last_request_time = 0.0
        # Polite delays: 5-9 seconds between requests
        self._min_delay = settings.scraper_config.min_request_delay
        self._max_delay = settings.scraper_config.max_request_delay
        self._rate_limit_wait = settings.scraper_config.rate_limit_wait_seconds
        self._day_delay_min = settings.scraper_config.day_delay_min
        self._day_delay_max = settings.scraper_config.day_delay_max
        self._error_delay_min = settings.scraper_config.error_delay_min
        self._error_delay_max = settings.scraper_config.error_delay_max
        # HTML cache (respect force-refresh overrides)
        self._cache = HTMLCache(
            settings.scraper_config.html_cache_dir,
            self.league_code,
            force_refresh=settings.scraper_config.force_cache_refresh,
        )

    def iter_dates(self, start: date, end: date) -> Iterator[date]:
        current = start
        while current <= end:
            yield current
            current += timedelta(days=1)

    def scoreboard_url(self, day: date) -> str:
        return f"{self.base_url}?month={day.month}&day={day.day}&year={day.year}"

    def pbp_url(self, source_game_key: str) -> str:
        """Build the play-by-play URL for a game key."""
        raise NotImplementedError

    def _polite_delay(self) -> None:
        """Wait a random 5-9 seconds since last request to be a good citizen."""
        elapsed = time.time() - self._last_request_time
        delay = random.uniform(self._min_delay, self._max_delay)
        if elapsed < delay:
            wait_time = delay - elapsed
            logger.debug("polite_delay", wait_seconds=round(wait_time, 1))
            time.sleep(wait_time)
        self._last_request_time = time.time()

    @retry(
        wait=wait_exponential(multiplier=30, min=60, max=300),
        stop=stop_after_attempt(2),
        retry=retry_if_not_exception_type(NoGamesFoundError),
    )
    def _fetch_from_network(self, url: str) -> str:
        """Fetch HTML from network with polite delays and retry logic."""
        self._polite_delay()

        logger.info("fetching_url", url=url)
        response = self.client.get(url, follow_redirects=True)

        if response.status_code == 429:
            logger.warning("rate_limit_hit", url=url, wait_seconds=self._rate_limit_wait)
            time.sleep(self._rate_limit_wait)
            raise ScraperError(f"Rate limited: {url} (429)")
        if response.status_code != 200:
            raise ScraperError(f"Failed to fetch {url} ({response.status_code})")

        # Detect redirects (e.g., Sports Reference redirects to main page for dates with no games)
        final_url = str(response.url)
        if final_url != url and "?" not in final_url:
            # Redirected to a different page (likely main page with no query params)
            logger.info("redirect_detected_no_games", original_url=url, final_url=final_url)
            raise NoGamesFoundError(f"No games found: redirected from {url} to {final_url}")

        return response.text

    def fetch_html(self, url: str, game_date: date | None = None) -> BeautifulSoup:
        """Fetch HTML, using cache if available.

        1. Check local cache first
        2. If not cached, fetch from network (with polite delay)
        3. Save to cache for future use
        4. Return parsed BeautifulSoup
        """
        # Check cache first
        cached_html = self._cache.get(url, game_date)
        if cached_html:
            return BeautifulSoup(cached_html, "lxml")

        # Fetch from network
        html = self._fetch_from_network(url)

        # Save to cache
        self._cache.put(url, html, game_date)

        return BeautifulSoup(html, "lxml")

    def fetch_games_for_date(self, day: date) -> Sequence[NormalizedGame]:
        raise NotImplementedError

    def fetch_play_by_play(self, source_game_key: str, game_date: date) -> NormalizedPlayByPlay:
        """Fetch and parse play-by-play for a single game."""
        raise NotImplementedError

    def fetch_single_boxscore(self, source_game_key: str, game_date: date) -> NormalizedGame | None:
        """Fetch boxscore for a single game by its source key.

        Used for backfilling player stats on existing games without re-scraping scoreboards.
        Override in subclass to support backfill mode.
        """
        raise NotImplementedError("Scraper does not support single-game fetch")

    def fetch_date_range(self, start: date, end: date) -> Iterable[NormalizedGame]:
        for day in self.iter_dates(start, end):
            try:
                logger.debug("scraper_fetching_date", day=str(day), league=self.league_code)
                games = self.fetch_games_for_date(day)
                games_list = list(games)  # Convert to list to get count
                logger.debug("scraper_date_complete", day=str(day), games_found=len(games_list), league=self.league_code)
                yield from games_list
                time.sleep(random.uniform(self._day_delay_min, self._day_delay_max))
            except NoGamesFoundError:
                # No games for this date - not an error, just continue to next date
                logger.debug("scraper_no_games_for_date", day=str(day), league=self.league_code)
                time.sleep(random.uniform(self._day_delay_min, self._day_delay_max))
                continue
            except ScraperError as exc:
                logger.error("scraper_date_error", day=str(day), error=str(exc), league=self.league_code, exc_info=True)
                time.sleep(random.uniform(self._error_delay_min, self._error_delay_max))
                continue
            except Exception as exc:
                logger.exception("scraper_date_unexpected_error", day=str(day), error=str(exc), league=self.league_code)
                time.sleep(random.uniform(self._error_delay_min, self._error_delay_max))
                continue

    def _parse_team_row(self, row: Tag) -> tuple[TeamIdentity, int]:
        """Parse a team row from a scoreboard table.

        Common implementation for most Sports Reference scoreboards.
        Extracts team name, normalizes it, and gets the score.

        Args:
            row: BeautifulSoup Tag representing a table row with team info

        Returns:
            Tuple of (TeamIdentity, score)

        Raises:
            ScraperError: If required elements are missing
        """
        team_link = row.find("a")
        if not team_link:
            raise ScraperError("Missing team link")
        team_name = team_link.text.strip()
        # Normalize team name to canonical form
        canonical_name, abbreviation = normalize_team_name(self.league_code, team_name)
        score_cell = row.find("td", class_="right")
        if score_cell is None:
            raise ScraperError("Missing score cell")
        score = parse_int(score_cell.text.strip())
        if score is None:
            raise ScraperError(f"Invalid score: {score_cell.text.strip()}")
        identity = TeamIdentity(
            league_code=self.league_code,
            name=canonical_name,
            short_name=canonical_name,
            abbreviation=abbreviation,
            external_ref=abbreviation.upper(),
        )
        return identity, score

    def _season_from_date(self, day: date) -> int:
        """Calculate season year from a date.

        Delegates to utils.date_utils.season_from_date with league_code.
        """
        return season_from_date(day, self.league_code)
