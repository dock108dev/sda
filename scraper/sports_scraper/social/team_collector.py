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
from .playwright_collector import PlaywrightXCollector, playwright_available
from .rate_limit import PlatformRateLimiter
from .registry import fetch_team_accounts
from .utils import extract_x_post_id

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class TeamTweetCollector:
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
        skip_if_fresh: bool = False,
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
            skip_if_fresh: If True, skip the scrape entirely when the team
                already has posts in our DB for the requested window. Used
                by collect_game_social to avoid redundant Playwright loads.
            min_posts_per_day: If set, count existing posts per day in the
                window. Days with >= this many posts are considered covered.
                The scrape range is narrowed to only uncovered days. If all
                days are covered, the scrape is skipped entirely. Used by
                backfill to avoid re-scraping days already collected.

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
        except Exception:
            pass  # Non-critical — scrolling just won't terminate early

        # Skip the Playwright scrape entirely if this team already has
        # recent posts in the window.  Used by collect_game_social to
        # avoid launching a browser for teams we already covered.
        if skip_if_fresh and recent_post_ids:
            # Check if we have any posts within the requested date range
            window_start_dt = date_to_utc_datetime(start_date)
            window_end_dt = date_to_utc_datetime(end_date) + timedelta(days=2)
            existing_in_window = (
                session.query(db_models.TeamSocialPost.id)
                .filter(
                    db_models.TeamSocialPost.team_id == team_id,
                    db_models.TeamSocialPost.posted_at >= window_start_dt,
                    db_models.TeamSocialPost.posted_at < window_end_dt,
                )
                .limit(1)
                .count()
            )
            if existing_in_window > 0:
                logger.info(
                    "team_collector_skip_fresh",
                    team_id=team_id,
                    team_abbr=team.abbreviation,
                    start_date=str(start_date),
                    end_date=str(end_date),
                )
                return 0

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

        # Collect tweets using the configured strategy
        try:
            posts = self.strategy.collect_posts(
                x_handle=x_handle,
                window_start=window_start,
                window_end=window_end,
                known_post_ids=recent_post_ids or None,
            )
        except XCircuitBreakerError:
            # Circuit breaker tripped - propagate to stop the entire scrape
            raise
        except Exception as exc:
            logger.exception(
                "team_collector_scrape_failed",
                team_id=team_id,
                handle=x_handle,
                error=str(exc),
            )
            return 0

        self.rate_limiter.record()

        # Save tweets to team_social_posts
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
                existing.media_type = post.media_type or "none"
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
                # Insert new record with mapping_status='unmapped'
                new_post = db_models.TeamSocialPost(
                    team_id=team_id,
                    platform=self.platform,
                    external_post_id=external_id,
                    post_url=post.post_url,
                    posted_at=normalized_posted_at,
                    tweet_text=post.text,
                    has_video=post.has_video,
                    video_url=post.video_url,
                    image_url=post.image_url,
                    media_type=post.media_type or "none",
                    source_handle=post.author_handle,
                    mapping_status="unmapped",
                )
                session.add(new_post)
                new_count += 1

        logger.info(
            "team_collector_complete",
            team_id=team_id,
            team_abbr=team.abbreviation,
            posts_found=len(posts),
            new_saved=new_count,
        )

        return new_count

    def collect_for_date_range(
        self,
        session: Session,
        league_code: str,
        start_date: date,
        end_date: date,
        on_batch_commit: callable | None = None,
    ) -> dict:
        """
        Collect tweets for all teams that played in date range.

        Args:
            session: Database session
            league_code: League code (NBA, NHL, NCAAB)
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            on_batch_commit: Optional callback invoked after each batch commit
                (e.g. to run incremental tweet mapping)

        Returns:
            Summary stats dict with teams_processed, total_new_tweets, errors
        """
        from ..db import db_models

        # Get league
        league = (
            session.query(db_models.SportsLeague)
            .filter(db_models.SportsLeague.code == league_code)
            .first()
        )
        if not league:
            logger.error("team_collector_league_not_found", league_code=league_code)
            return {"error": f"League not found: {league_code}"}

        # Convert dates to datetimes for game query
        start_dt = date_to_utc_datetime(start_date)
        end_dt = date_to_utc_datetime(end_date) + timedelta(days=1)

        # Find all games in the date range for this league
        games = (
            session.query(db_models.SportsGame)
            .filter(
                db_models.SportsGame.league_id == league.id,
                db_models.SportsGame.game_date >= start_dt,
                db_models.SportsGame.game_date < end_dt,
            )
            .all()
        )

        if not games:
            logger.info(
                "team_collector_no_games",
                league_code=league_code,
                start_date=str(start_date),
                end_date=str(end_date),
            )
            return {
                "league": league_code,
                "teams_processed": 0,
                "total_new_tweets": 0,
                "games_in_range": 0,
            }

        logger.info(
            "team_collector_range_start",
            league_code=league_code,
            start_date=str(start_date),
            end_date=str(end_date),
            games_found=len(games),
        )

        # Iterate game-by-game: scrape both teams per game, then wait
        # before the next game to avoid X rate limits.
        # Posts are committed in batches to survive
        # mid-run failures — completed batches remain persisted.
        import random
        import time

        social_cfg = settings.social_config

        teams_processed = 0
        total_new_tweets = 0
        errors: list[str] = []
        consecutive_breaker_hits = 0
        scraped_team_ids: set[int] = set()
        games_completed = 0
        batch_new_tweets = 0
        game_new_tweets = 0  # Track per-game new tweets for adaptive delay

        for i, game in enumerate(games):
            # Wait between games (skip before the first one).
            # Use a short delay when the previous game found no new tweets
            # (early-exit means minimal X load, so full delay is wasteful).
            if i > 0:
                if game_new_tweets == 0:
                    delay = social_cfg.early_exit_delay_seconds
                else:
                    delay = random.uniform(
                        social_cfg.inter_game_delay_seconds,
                        social_cfg.inter_game_delay_max_seconds,
                    )
                logger.info(
                    "team_collector_inter_game_delay",
                    delay_seconds=round(delay, 1),
                    games_remaining=len(games) - i,
                    fast=game_new_tweets == 0,
                )
                time.sleep(delay)

            game_new_tweets = 0
            for team_id in (game.home_team_id, game.away_team_id):
                if team_id in scraped_team_ids:
                    continue
                scraped_team_ids.add(team_id)

                try:
                    new_tweets = self.collect_team_tweets(
                        session=session,
                        team_id=team_id,
                        start_date=start_date,
                        end_date=end_date,
                        min_posts_per_day=10,
                    )
                    teams_processed += 1
                    total_new_tweets += new_tweets
                    batch_new_tweets += new_tweets
                    game_new_tweets += new_tweets
                    consecutive_breaker_hits = 0  # Reset on success
                except XCircuitBreakerError as exc:
                    consecutive_breaker_hits += 1
                    errors.append(f"Team {team_id}: rate limited ({str(exc)})")
                    logger.warning(
                        "team_collector_rate_limited",
                        team_id=team_id,
                        consecutive_hits=consecutive_breaker_hits,
                        error=str(exc),
                    )
                    if consecutive_breaker_hits >= social_cfg.max_consecutive_breaker_hits:
                        logger.error(
                            "team_collector_batch_abort",
                            teams_processed=teams_processed,
                            consecutive_hits=consecutive_breaker_hits,
                        )
                        break
                    # Back off before trying the next team
                    logger.info("team_collector_rate_limit_backoff", backoff_seconds=social_cfg.breaker_backoff_seconds)
                    time.sleep(social_cfg.breaker_backoff_seconds)
                except Exception as exc:
                    error_msg = f"Team {team_id}: {str(exc)}"
                    errors.append(error_msg)
                    logger.exception(
                        "team_collector_team_failed",
                        team_id=team_id,
                        error=str(exc),
                    )
            else:
                # Only reached if inner loop didn't break — game completed
                games_completed += 1
                if games_completed % social_cfg.game_batch_size == 0:
                    session.commit()
                    logger.info(
                        "team_collector_batch_committed",
                        games_processed=games_completed,
                        posts=batch_new_tweets,
                    )
                    batch_new_tweets = 0
                    # Run incremental mapping after each batch commit
                    if on_batch_commit:
                        try:
                            on_batch_commit()
                        except Exception as exc:
                            logger.warning(
                                "team_collector_on_batch_commit_error",
                                error=str(exc),
                            )
                continue
            # Inner loop broke (batch abort) — stop outer loop too
            break

        # Final flush for remaining games (< batch size) or abort
        session.commit()
        if batch_new_tweets > 0:
            logger.info(
                "team_collector_batch_committed",
                games_processed=games_completed,
                posts=batch_new_tweets,
            )
        # Run mapping for the final partial batch
        if on_batch_commit:
            try:
                on_batch_commit()
            except Exception as exc:
                logger.warning(
                    "team_collector_on_batch_commit_error",
                    error=str(exc),
                )

        logger.info(
            "team_collector_range_complete",
            league_code=league_code,
            teams_processed=teams_processed,
            total_new_tweets=total_new_tweets,
            errors_count=len(errors),
        )

        return {
            "league": league_code,
            "start_date": str(start_date),
            "end_date": str(end_date),
            "games_in_range": len(games),
            "teams_processed": teams_processed,
            "total_new_tweets": total_new_tweets,
            "errors": errors if errors else None,
        }
