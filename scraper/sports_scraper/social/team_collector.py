"""Team-centric tweet collection.

Scrapes all tweets for teams in a date range,
saving them to team_social_posts with mapping_status='unmapped'.

See tweet_mapper.py for mapping unmapped tweets to games.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from ..config import settings
from ..logging import logger
from ..utils.datetime_utils import date_to_utc_datetime, now_utc
from .exceptions import XCircuitBreakerError
from .metrics import increment_scrape_result
from .playwright_collector import PlaywrightXCollector, playwright_available
from .rate_limit import PlatformRateLimiter
from .registry import fetch_team_accounts
from .team_range_collector import TeamTweetRangeMixin
from .utils import extract_x_post_id

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class TeamTweetCollector(TeamTweetRangeMixin):
    """
    Collect tweets for teams and save to team_social_posts table.

    This collector is team-centric rather than game-centric. It scrapes
    a team's timeline for a date range, then saves all tweets for later
    mapping to games.
    """

    def __init__(
        self,
        strategy: PlaywrightXCollector | None = None,
    ):
        if strategy:
            self.strategy = strategy
        elif playwright_available():
            self.strategy = PlaywrightXCollector()
        else:
            raise RuntimeError("Playwright is required for social collection but not installed")
        self.platform = "x"
        social_config = settings.social_config
        self.rate_limiter = PlatformRateLimiter(
            max_requests=social_config.platform_rate_limit_max_requests,
            window_seconds=social_config.platform_rate_limit_window_seconds,
        )

    def close(self) -> None:
        """Shut down the underlying browser if it's running."""
        if hasattr(self.strategy, "close"):
            self.strategy.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _normalize_posted_at(self, posted_at: datetime) -> datetime:
        if posted_at.tzinfo is None:
            return posted_at.replace(tzinfo=UTC)
        return posted_at.astimezone(UTC)

    def collect_team_tweets(
        self,
        session: Session,
        team_id: int,
        start_date: date,
        end_date: date,
        *,
        min_posts_per_day: int | None = None,
    ) -> int:
        """
        Scrape all tweets for a team in date range.

        Posts are added to the session but NOT committed — the caller
        (collect_for_date_range) owns commit timing for batch persistence.

        Args:
            session: Database session
            team_id: ID of the team in sports_teams
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            min_posts_per_day: If set, count existing posts per day in the
                window. Days with >= this many posts are considered covered.
                The scrape range is narrowed to only uncovered days. If all
                days are covered, the scrape is skipped entirely. New tweets
                are still captured on covered days via collect_game_social
                (the consecutive-known-posts early exit handles efficiency).

        Returns:
            Count of new tweets saved
        """
        from ..db import db_models

        team = session.query(db_models.SportsTeam).get(team_id)
        if not team:
            logger.warning("team_collector_team_not_found", team_id=team_id)
            return 0

        # Get X handle from team_social_accounts or fall back to x_handle on team
        account_map = fetch_team_accounts(
            session, team_ids=[team_id], platform=self.platform
        )
        account = account_map.get(team_id)
        x_handle = account.handle if account else team.x_handle

        if not x_handle:
            logger.debug(
                "team_collector_no_handle",
                team_id=team_id,
                team_abbr=team.abbreviation,
            )
            return 0

        # Convert ET game dates to a scrape window in ET.
        # Games tip in the evening and cross midnight ET, so the window
        # runs from 5 AM ET on the game date through 8 AM ET the next day
        # (covers latest postgame ~3 AM ET + buffer).
        eastern = ZoneInfo("America/New_York")
        window_start = datetime.combine(start_date, datetime.min.time(), tzinfo=eastern).replace(hour=settings.social_config.pregame_start_hour_et)
        window_end = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=eastern).replace(hour=8)

        logger.info(
            "team_collector_start",
            team_id=team_id,
            team_abbr=team.abbreviation,
            handle=x_handle,
            start_date=str(start_date),
            end_date=str(end_date),
        )

        # Query recent post IDs for this team so the collector can stop
        # scrolling early when it hits posts we already have.
        recent_post_ids: set[str] = set()
        try:
            recent_rows = (
                session.query(db_models.TeamSocialPost.external_post_id)
                .filter(
                    db_models.TeamSocialPost.team_id == team_id,
                    db_models.TeamSocialPost.external_post_id.isnot(None),
                )
                .order_by(db_models.TeamSocialPost.posted_at.desc())
                .limit(50)
                .all()
            )
            recent_post_ids = {row[0] for row in recent_rows}
        except Exception as recent_lookup_exc:
            # Non-critical — scroll won't short-circuit, but the scrape still
            # collects. Log at warning so persistent DB errors surface in ops
            # dashboards instead of dying silently.
            # See docs/audits/error-handling-report.md Appendix B.
            logger.warning(
                "team_collector_recent_posts_lookup_failed",
                team_id=team_id,
                error=str(recent_lookup_exc),
            )

        # Narrow the scrape range by skipping days that already have
        # sufficient coverage.  Used by backfill so we don't re-scrape
        # days that are already fully collected.
        if min_posts_per_day is not None and start_date <= end_date:
            from sqlalchemy import cast, func
            from sqlalchemy.types import Date

            post_day = cast(db_models.TeamSocialPost.posted_at, Date)
            day_counts = dict(
                session.query(post_day, func.count())
                .filter(
                    db_models.TeamSocialPost.team_id == team_id,
                    db_models.TeamSocialPost.posted_at >= date_to_utc_datetime(start_date),
                    db_models.TeamSocialPost.posted_at < date_to_utc_datetime(end_date) + timedelta(days=2),
                )
                .group_by(post_day)
                .all()
            )

            # Find earliest and latest uncovered days
            uncovered_days = []
            current = start_date
            while current <= end_date:
                if day_counts.get(current, 0) < min_posts_per_day:
                    uncovered_days.append(current)
                current += timedelta(days=1)

            if not uncovered_days:
                logger.info(
                    "team_collector_skip_covered",
                    team_id=team_id,
                    team_abbr=team.abbreviation,
                    start_date=str(start_date),
                    end_date=str(end_date),
                    threshold=min_posts_per_day,
                    days_total=(end_date - start_date).days + 1,
                )
                return 0

            new_start = uncovered_days[0]
            new_end = uncovered_days[-1]
            if new_start != start_date or new_end != end_date:
                logger.info(
                    "team_collector_range_narrowed",
                    team_id=team_id,
                    team_abbr=team.abbreviation,
                    original=f"{start_date} to {end_date}",
                    narrowed=f"{new_start} to {new_end}",
                    days_skipped=(end_date - start_date).days + 1 - len(uncovered_days),
                )
                start_date = new_start
                end_date = new_end

        # Release any AccessShareLocks acquired by the read queries above
        # before the multi-second Playwright fetch. A held lock here will
        # block any concurrent ALTER TABLE on team_social_posts /
        # sports_teams (e.g. during a migration) and stack subsequent
        # workers behind it.
        session.commit()

        # Collect tweets using the configured strategy
        try:
            posts = self.strategy.collect_posts(
                x_handle=x_handle,
                window_start=window_start,
                window_end=window_end,
                known_post_ids=recent_post_ids or None,
            )
            increment_scrape_result(team_id, success=True)
        except XCircuitBreakerError:
            increment_scrape_result(team_id, success=False)
            # Circuit breaker tripped - propagate to stop the entire scrape
            raise
        except Exception as exc:
            increment_scrape_result(team_id, success=False)
            logger.exception(
                "team_collector_scrape_failed",
                team_id=team_id,
                handle=x_handle,
                error=str(exc),
            )
            # Re-raise so callers (collect_game_social) can track the failure
            # and avoid stamping last_social_at on broken scrapes.
            raise

        self.rate_limiter.record()

        # Save tweets to team_social_posts using upsert (ON CONFLICT) to handle
        # race conditions with collect_game_social running concurrently.
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        new_count = 0
        consecutive_known = 0
        for post in posts:
            normalized_posted_at = self._normalize_posted_at(post.posted_at)
            external_id = post.external_post_id or extract_x_post_id(post.post_url)

            # Check if this post already exists (by external_post_id)
            existing = None
            if external_id:
                existing = (
                    session.query(db_models.TeamSocialPost)
                    .filter(db_models.TeamSocialPost.external_post_id == external_id)
                    .first()
                )

            if existing:
                consecutive_known += 1
                # Update existing record
                existing.posted_at = normalized_posted_at
                existing.tweet_text = post.text
                existing.has_video = post.has_video
                existing.video_url = post.video_url
                existing.image_url = post.image_url
                existing.media_type = post.media_type or None
                existing.source_handle = post.author_handle
                existing.updated_at = now_utc()
                logger.debug(
                    "team_collector_updated_existing",
                    external_id=external_id,
                    team_id=team_id,
                )
                # Early exit: N consecutive known posts means we've caught up
                if consecutive_known >= settings.social_config.consecutive_known_post_exit:
                    logger.info(
                        "team_collector_early_exit_known_posts",
                        team_id=team_id,
                        consecutive_known=consecutive_known,
                        posts_processed=posts.index(post) + 1,
                        total_posts=len(posts),
                    )
                    break
            else:
                consecutive_known = 0
                # Upsert: insert new post or skip if another worker already inserted it
                stmt = pg_insert(db_models.TeamSocialPost).values(
                    team_id=team_id,
                    platform=self.platform,
                    external_post_id=external_id,
                    post_url=post.post_url,
                    posted_at=normalized_posted_at,
                    tweet_text=post.text,
                    has_video=post.has_video,
                    video_url=post.video_url,
                    image_url=post.image_url,
                    # Column is nullable and CHECK allows only {video, image, NULL}.
                    media_type=post.media_type or None,
                    source_handle=post.author_handle,
                    mapping_status="unmapped",
                    # Initial value; tweet_mapper reclassifies to pregame/in_game/postgame
                    # once a game is matched. Explicit here because the DB column is
                    # NOT NULL and prod doesn't carry a SQL-level DEFAULT.
                    game_phase="unknown",
                ).on_conflict_do_nothing(index_elements=["external_post_id"])
                result = session.execute(stmt)
                if result.rowcount:
                    new_count += 1

        logger.info(
            "team_collector_complete",
            team_id=team_id,
            team_abbr=team.abbreviation,
            posts_found=len(posts),
            new_saved=new_count,
        )

        return new_count
