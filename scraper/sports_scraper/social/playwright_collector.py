"""Playwright-backed collector for public X posts."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from importlib.util import find_spec

from tenacity import retry, stop_after_attempt, wait_fixed

from ..config import settings
from ..logging import logger
from .exceptions import XCircuitBreakerError
from .models import CollectedPost
from .utils import extract_x_post_id

if find_spec("playwright.sync_api") is not None:
    from playwright.sync_api import sync_playwright
else:  # pragma: no cover - optional dependency
    sync_playwright = None


def playwright_available() -> bool:  # pragma: no cover
    return sync_playwright is not None


class PlaywrightXCollector:
    """
    Headless collector that visits public X profiles and extracts recent posts.

    This avoids X API dependency. It scrapes minimal metadata:
    - post URL
    - timestamp
    - has_video flag

    Authentication:
        Set X_AUTH_TOKEN and X_CT0 environment variables from your browser cookies.
        Cookies are injected directly into each fresh browser context.

        To get these values:
        1. Log into x.com in your browser
        2. Open DevTools > Application > Cookies > x.com
        3. Copy the values of 'auth_token' and 'ct0' cookies

    Rate Limiting:
        - Polite delay of 30-60 seconds between requests
        - Random 5-10 second delay per scroll action
        - Random jitter to appear more human-like
        - Concurrency=1 in Celery naturally caps throughput

    Retry Logic:
        - On "login wall" or "Something went wrong": sleep 120s (configurable), retry up to 2 times (configurable via SocialConfig)
        - On "No results": return empty list (not an error)
        - After max failures: raise XCircuitBreakerError to fail the job
        - No class-level state — each collect_posts() call is self-contained
    """

    def __init__(  # pragma: no cover - browser config
        self,
        max_scrolls: int = 8,
        wait_ms: int = 2000,  # X's JS needs time to render
        timeout_ms: int = 30000,
        auth_token: str | None = None,
        ct0: str | None = None,
        min_delay_seconds: float = 30.0,
        max_delay_seconds: float = 60.0,
    ):
        import os

        self.max_scrolls = max_scrolls
        self.wait_ms = wait_ms
        self.timeout_ms = timeout_ms
        self.min_delay_seconds = min_delay_seconds
        self.max_delay_seconds = max_delay_seconds
        self._last_request_time = 0.0

        # Auth tokens — injected directly into each fresh browser context
        self.auth_token = auth_token or os.environ.get("X_AUTH_TOKEN")
        self.ct0 = ct0 or os.environ.get("X_CT0")

        # Persistent browser state — started lazily, reused across scrapes
        self._pw = None
        self._browser = None
        self._context = None

        # Dedicated thread for all Playwright operations.
        # Celery workers using psycopg v3 run inside an asyncio event loop,
        # which prevents Playwright's sync API from starting.  A single-thread
        # executor keeps all browser work on a thread without an event loop.
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pw")

        if self.auth_token and self.ct0:
            logger.info("x_auth_configured", token_len=len(self.auth_token), ct0_len=len(self.ct0))
        else:
            logger.warning("x_auth_missing", message="X_AUTH_TOKEN and/or X_CT0 not set - search will not work")

    def _run_in_thread(self, fn, *args, **kwargs):
        """Run *fn* in the dedicated browser thread (no asyncio loop)."""
        future = self._executor.submit(fn, *args, **kwargs)
        return future.result()

    def _ensure_browser(self) -> None:  # pragma: no cover - browser lifecycle
        """Lazily start Playwright + Chromium if not already running."""
        if self._browser is not None:
            return

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        self._context = self._browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        if self.auth_token and self.ct0:
            self._context.add_cookies(
                [
                    {"name": "auth_token", "value": self.auth_token, "domain": ".x.com", "path": "/"},
                    {"name": "ct0", "value": self.ct0, "domain": ".x.com", "path": "/"},
                ]
            )
        logger.info("x_browser_started")

    def _close_browser(self) -> None:  # pragma: no cover - browser lifecycle
        """Internal close — must run on the browser thread."""
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:
                logger.debug("browser_close_failed", exc_info=True)
            self._browser = None
            self._context = None
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:
                logger.debug("playwright_stop_failed", exc_info=True)
            self._pw = None
            logger.info("x_browser_stopped")

    def close(self) -> None:  # pragma: no cover - browser lifecycle
        """Shut down the browser and Playwright server."""
        if self._browser is not None or self._pw is not None:
            try:
                self._run_in_thread(self._close_browser)
            except Exception:
                # Executor already shut down or other error — force cleanup
                self._close_browser()
        try:
            self._executor.shutdown(wait=True)
        except Exception:
            logger.debug("executor_shutdown_failed", exc_info=True)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __del__(self):  # pragma: no cover
        self.close()

    def _polite_delay(self) -> None:  # pragma: no cover - timing-dependent
        """Wait between requests to be a good citizen (30-60 seconds)."""
        import random
        import time

        if self._last_request_time == 0:
            return

        elapsed = time.time() - self._last_request_time
        delay = random.uniform(self.min_delay_seconds, self.max_delay_seconds)
        if elapsed < delay:
            wait_time = delay - elapsed
            logger.debug("x_polite_delay", wait_seconds=round(wait_time, 1))
            time.sleep(wait_time)

    def _mark_request_done(self) -> None:  # pragma: no cover - timing-dependent
        """Mark that a request just completed (for polite delay calculation)."""
        import time

        self._last_request_time = time.time()

    @retry(stop=stop_after_attempt(2), wait=wait_fixed(1))
    def _build_search_url(self, x_handle: str, window_start: datetime, window_end: datetime) -> str:  # pragma: no cover
        """
        Build X search URL for historical tweet lookup.

        Uses X's advanced search syntax:
            from:handle since:YYYY-MM-DD until:YYYY-MM-DD
        """
        handle_clean = x_handle.lstrip("@")
        start_date = window_start.strftime("%Y-%m-%d")
        end_date = (window_end + timedelta(days=1)).strftime("%Y-%m-%d")
        query = f"from:{handle_clean} since:{start_date} until:{end_date}"
        from urllib.parse import quote

        return f"https://x.com/search?q={quote(query)}&src=typed_query&f=live"

    def _parse_post_time(self, datetime_str: str) -> datetime | None:  # pragma: no cover
        try:
            from dateutil import parser
            return parser.isoparse(datetime_str)
        except Exception:
            return None

    def _scrape_once(  # pragma: no cover - requires browser
        self,
        x_handle: str,
        window_start: datetime,
        window_end: datetime,
        known_post_ids: set[str] | None = None,
    ) -> tuple[list[CollectedPost], str | None]:
        """Dispatch scrape to the dedicated browser thread."""
        return self._run_in_thread(
            self._scrape_once_impl, x_handle, window_start, window_end, known_post_ids
        )

    def _scrape_once_impl(  # pragma: no cover - requires browser
        self,
        x_handle: str,
        window_start: datetime,
        window_end: datetime,
        known_post_ids: set[str] | None = None,
    ) -> tuple[list[CollectedPost], str | None]:
        """Execute a single scrape attempt (runs on the browser thread).

        Returns:
            Tuple of (posts, error_message). error_message is None on success
            or "no_results" for empty-but-valid responses.
        """
        posts: list[CollectedPost] = []
        page_error_message: str | None = None

        self._ensure_browser()
        page = self._context.new_page()

        try:
            search_url = self._build_search_url(x_handle, window_start, window_end)
            logger.debug("x_playwright_search_url", url=search_url)

            page.goto(search_url, timeout=self.timeout_ms, wait_until="domcontentloaded")

            # Wait for tweets to appear. X's JS rendering can be slow
            # under sequential load, so try twice with increasing timeouts.
            tweet_selector = 'article[data-testid="tweet"]'
            tweets_found = False
            try:
                page.wait_for_selector(tweet_selector, timeout=15000, state="attached")
                tweets_found = True
            except Exception as exc:
                logger.debug(
                    "x_tweet_selector_wait_timeout",
                    handle=x_handle,
                    error=str(exc),
                )

            if not tweets_found:
                # Check for explicit error pages before giving up
                content = page.content()
                if "Something went wrong" in content:
                    page_error_message = "X returned 'Something went wrong' - possible rate limit or auth issue"
                    logger.error("x_page_error", handle=x_handle, error=page_error_message)
                elif page.url and "/login" in page.url:
                    page_error_message = "X returned login wall - auth tokens may be expired"
                    logger.error("x_page_error", handle=x_handle, error=page_error_message)
                elif "No results" in content:
                    logger.debug("x_page_no_results", handle=x_handle)
                    page_error_message = "no_results"
                else:
                    # No error detected but no tweets yet — wait longer and try once more
                    logger.debug("x_slow_render_retry", handle=x_handle)
                    page.wait_for_timeout(5000)
                    try:
                        page.wait_for_selector(tweet_selector, timeout=10000, state="attached")
                    except Exception:
                        # Still nothing — check for login wall in final content
                        final_content = page.content()
                        if "Log in to X" in final_content or "Sign in to X" in final_content:
                            page_error_message = "X returned login wall - auth tokens may be expired"
                            logger.error("x_page_error", handle=x_handle, error=page_error_message)
                        else:
                            page_error_message = "no_results"
                            logger.debug("x_page_no_results_after_retry", handle=x_handle)

            page.wait_for_timeout(self.wait_ms)

            def extract_posts_from_page() -> set[str]:
                """Extract all posts currently visible and return set of post IDs."""
                extracted_ids: set[str] = set()
                articles = page.query_selector_all('article[data-testid="tweet"]')

                for article in articles:
                    # Skip retweets
                    social_context = article.query_selector('[data-testid="socialContext"]')
                    if social_context:
                        context_text = social_context.inner_text()
                        if context_text and "Retweeted" in context_text:
                            continue

                    # Extract post URL
                    anchor = article.query_selector('a[href*="/status/"]')
                    post_url = None
                    if anchor:
                        href = anchor.get_attribute("href")
                        if href:
                            post_url = f"https://x.com{href}" if href.startswith("/") else href

                    if not post_url:
                        continue

                    post_id = extract_x_post_id(post_url)
                    if not post_id or post_id in seen_post_ids:
                        continue

                    extracted_ids.add(post_id)
                    seen_post_ids.add(post_id)

                    # Extract timestamp
                    time_el = article.query_selector("time")
                    posted_at = None
                    if time_el:
                        datetime_str = time_el.get_attribute("datetime")
                        if datetime_str:
                            posted_at = self._parse_post_time(datetime_str)

                    if not posted_at:
                        continue

                    # Extract text content
                    text_content = None
                    text_el = article.query_selector('[data-testid="tweetText"]')
                    if text_el:
                        text_content = text_el.inner_text()

                    # Detect media. media_type stays None for text-only posts —
                    # team_social_posts has a CHECK constraint allowing only
                    # {video, image, NULL}.
                    video_url = None
                    image_url = None
                    media_type: str | None = None

                    video_container = (
                        article.query_selector('[data-testid="videoPlayer"]')
                        or article.query_selector('[data-testid="videoComponent"]')
                        or article.query_selector('[data-testid="previewInterstitial"]')
                        or article.query_selector('video')
                    )
                    has_video = video_container is not None

                    if has_video:
                        media_type = "video"
                        video_el = article.query_selector("video")
                        if video_el:
                            video_url = video_el.get_attribute("src")
                    else:
                        img_el = article.query_selector('[data-testid="tweetPhoto"] img')
                        if img_el:
                            image_url = img_el.get_attribute("src")
                            media_type = "image"

                    posts.append(
                        CollectedPost(
                            post_url=post_url,
                            external_post_id=post_id,
                            posted_at=posted_at,
                            has_video=has_video,
                            text=text_content,
                            author_handle=x_handle.lstrip("@"),
                            video_url=video_url,
                            image_url=image_url,
                            media_type=media_type,
                        )
                    )

                return extracted_ids

            # Track seen posts to dedupe across scrolls
            seen_post_ids: set[str] = set()

            # Initial extraction
            new_ids = extract_posts_from_page()
            logger.debug("x_initial_extract", handle=x_handle, new_posts=len(new_ids), total=len(posts))

            # Scroll and extract until no new posts appear
            for scroll_num in range(self.max_scrolls):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                # Random 5-10s delay per scroll to mimic human behavior
                import random as _rng
                page.wait_for_timeout(int(_rng.uniform(5, 10) * 1000))

                new_ids = extract_posts_from_page()
                logger.debug(
                    "x_scroll_extract",
                    handle=x_handle,
                    scroll=scroll_num + 1,
                    new_posts=len(new_ids),
                    total=len(posts),
                )

                # Stop early if no new posts or all posts already known
                if len(new_ids) == 0:
                    logger.debug("x_scroll_complete_early", handle=x_handle, reason="no_new_posts")
                    break
                if known_post_ids and new_ids.issubset(known_post_ids):
                    logger.debug("x_scroll_complete_early", handle=x_handle, reason="all_posts_known")
                    break

            self._mark_request_done()

        finally:
            page.close()

        return posts, page_error_message

    def collect_posts(  # pragma: no cover - requires browser
        self,
        x_handle: str,
        window_start: datetime,
        window_end: datetime,
        known_post_ids: set[str] | None = None,
    ) -> list[CollectedPost]:
        if not sync_playwright:
            logger.warning("x_playwright_missing", handle=x_handle)
            return []

        logger.info(
            "x_playwright_collect_start",
            handle=x_handle,
            window_start=str(window_start),
            window_end=str(window_end),
        )

        self._polite_delay()

        social_cfg = settings.social_config
        max_attempts = social_cfg.playwright_max_attempts
        backoff_seconds = social_cfg.playwright_backoff_seconds

        last_error: str = ""
        for attempt in range(1, max_attempts + 1):
            posts, error_message = self._scrape_once(x_handle, window_start, window_end, known_post_ids=known_post_ids)

            # "no_results" is not an error — just no tweets in that window
            if error_message == "no_results":
                logger.info("x_playwright_collect_done", handle=x_handle, count=0)
                return []

            # Success — got posts (or no error and no posts)
            if error_message is None:
                logger.info("x_playwright_collect_done", handle=x_handle, count=len(posts))
                return posts

            # Retryable error (login wall, "Something went wrong")
            last_error = error_message
            logger.warning(
                "x_scrape_retry",
                handle=x_handle,
                attempt=attempt,
                max_attempts=max_attempts,
                error=error_message,
                backoff_seconds=backoff_seconds,
            )

            if attempt < max_attempts:
                time.sleep(backoff_seconds)

        # All attempts exhausted — fail the job loudly
        logger.error(
            "x_scrape_failed_permanently",
            handle=x_handle,
            attempts=max_attempts,
            error=last_error,
        )
        raise XCircuitBreakerError(
            f"X scrape failed after {max_attempts} attempts: {last_error}",
            retry_after_seconds=0,
        )
