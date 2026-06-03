"""Date-range orchestration for team tweet collection."""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING

from ..config import settings
from ..logging import logger
from ..utils.datetime_utils import date_to_utc_datetime
from .exceptions import XCircuitBreakerError

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class TeamTweetRangeMixin:
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
                # Commit before sleeping so we don't hold any lock from the
                # previous iteration's writes across a 30–60s wall-clock wait.
                session.commit()
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
                    try:
                        session.rollback()
                    except Exception:
                        logger.exception("team_collector_rollback_failed", team_id=team_id)
                    if consecutive_breaker_hits >= social_cfg.max_consecutive_breaker_hits:
                        logger.error(
                            "team_collector_batch_abort",
                            teams_processed=teams_processed,
                            consecutive_hits=consecutive_breaker_hits,
                        )
                        break
                    # Back off before trying the next team. Commit (after the
                    # rollback above) so we hold no lock across the backoff.
                    logger.info("team_collector_rate_limit_backoff", backoff_seconds=social_cfg.breaker_backoff_seconds)
                    session.commit()
                    time.sleep(social_cfg.breaker_backoff_seconds)
                except Exception as exc:
                    error_msg = f"Team {team_id}: {str(exc)}"
                    errors.append(error_msg)
                    logger.exception(
                        "team_collector_team_failed",
                        team_id=team_id,
                        error=str(exc),
                    )
                    # Roll back so a failure mid-query doesn't poison the session's
                    # transaction and cascade an InFailedSqlTransaction into every
                    # subsequent team's first query.
                    try:
                        session.rollback()
                    except Exception:
                        logger.exception("team_collector_rollback_failed", team_id=team_id)
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
