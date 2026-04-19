"""Tweet-to-game mapping.

Assigns unmapped tweets to games based on posted_at timestamps
falling within game windows.

All comparisons are done in US/Eastern time. Games naturally cross midnight
ET (e.g. a 10 PM ET tip ends around 12:30 AM ET the next day), so the
postgame window extends into the following calendar day.

See team_collector.py for collecting team tweets.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from ..config import settings
from ..config_sports import LEAGUE_CONFIG, LeagueConfig
from ..logging import logger
from ..utils.datetime_utils import SPORTS_DAY_BOUNDARY_HOUR_ET, now_utc
from .models import GamePhase

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


EASTERN = ZoneInfo("America/New_York")


def _to_et(dt: datetime) -> datetime:
    """Convert a datetime to US/Eastern."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(EASTERN)


def _get_league_code(game) -> str | None:
    """Get the league code from a game object, if available."""
    if hasattr(game, "league") and game.league and hasattr(game.league, "code"):
        return game.league.code
    if hasattr(game, "league_code"):
        return game.league_code
    return None


def _game_duration_hours(game) -> float:
    """Return the estimated game duration based on the sport."""
    league_code = _get_league_code(game)
    if league_code and league_code in LEAGUE_CONFIG:
        return LEAGUE_CONFIG[league_code].estimated_game_duration_hours
    return LeagueConfig(code="", display_name="").estimated_game_duration_hours


def _get_game_start(game) -> datetime:
    """Resolve game start time from game_date, always UTC-aware."""
    game_start = game.game_date
    if game_start.tzinfo is None:
        game_start = game_start.replace(tzinfo=UTC)
    return game_start


def _get_game_end(game, game_start: datetime) -> datetime:
    """Resolve game end time from end_time or sport-specific duration."""
    if game.end_time and game.end_time > game_start:
        game_end = game.end_time
        if game_end.tzinfo is None:
            game_end = game_end.replace(tzinfo=UTC)
    else:
        game_end = game_start + timedelta(hours=_game_duration_hours(game))
    return game_end


def _pregame_start_utc(game) -> datetime:
    """Return pregame_start_hour_et on the game's ET calendar date, as a UTC datetime."""
    game_day = _to_et(game.game_date).date()
    pregame_et = datetime.combine(
        game_day, datetime.min.time(), tzinfo=EASTERN
    ).replace(hour=settings.social_config.pregame_start_hour_et)
    return pregame_et.astimezone(UTC)


def get_game_window(
    game,
    postgame_hours: int | None = None,
) -> tuple[datetime, datetime]:
    """
    Calculate the tweet window for a game.

    The window spans from pregame_start_hour_et on the game's calendar date
    through postgame_hours after game end. Game end is determined by end_time
    if available, otherwise estimated using sport-specific duration.

    The window will cross midnight ET for evening games — this is expected.

    Args:
        game: SportsGame object (must have game_date, end_time)
        postgame_hours: Hours after game end to include (default: from LeagueConfig)

    Returns:
        Tuple of (window_start, window_end) as timezone-aware UTC datetimes
    """
    if postgame_hours is None:
        league_code = _get_league_code(game)
        if league_code and league_code in LEAGUE_CONFIG:
            postgame_hours = LEAGUE_CONFIG[league_code].postgame_window_hours
        else:
            postgame_hours = LeagueConfig(code="", display_name="").postgame_window_hours

    game_start = _get_game_start(game)
    game_end = _get_game_end(game, game_start)

    window_start = _pregame_start_utc(game)
    window_end = game_end + timedelta(hours=postgame_hours)

    # Floor: window must extend to at least 4 AM ET on the day after game_date.
    # Late-night games (ending after midnight ET) need postgame tweets captured
    # until the sports day boundary.
    next_day = _to_et(game.game_date).date() + timedelta(days=1)
    floor_et = datetime.combine(
        next_day, datetime.min.time(), tzinfo=EASTERN
    ).replace(hour=SPORTS_DAY_BOUNDARY_HOUR_ET)
    floor_utc = floor_et.astimezone(UTC)
    window_end = max(window_end, floor_utc)

    return window_start, window_end


def classify_game_phase(
    posted_at: datetime,
    game,
) -> str:
    """Classify a tweet as pregame/in_game/postgame relative to a game.

    All comparisons in ET. Boundaries:
    - pregame:  posted_at < game_date
    - in_game:  game_date <= posted_at <= end_time
    - postgame: end_time < posted_at

    Uses sport-specific game duration when end_time is unavailable.
    """
    game_start = _get_game_start(game)
    game_end = _get_game_end(game, game_start)

    if posted_at < game_start:
        return "pregame"
    if posted_at <= game_end:
        return "in_game"
    return "postgame"


def _search_dates_for_tweet(posted_at: datetime) -> tuple[datetime, datetime]:
    """Return the game_date search range for a tweet.

    Convert tweet to ET, then search for games on that ET date and the
    previous day. This handles games that cross midnight ET — a postgame
    tweet at 1 AM ET on Feb 7 needs to find the Feb 6 game.
    """
    tweet_et = _to_et(posted_at)
    tweet_et_date = tweet_et.date()

    # Search the tweet's ET date and the day before (for games that cross midnight).
    # game_date is stored as midnight ET → UTC (e.g. 05:00 UTC for EST),
    # so bounds must also be midnight ET → UTC to match.
    search_start = datetime.combine(
        tweet_et_date - timedelta(days=1),
        datetime.min.time(),
        tzinfo=EASTERN,
    ).astimezone(UTC)
    search_end = datetime.combine(
        tweet_et_date,
        datetime.min.time(),
        tzinfo=EASTERN,
    ).astimezone(UTC)
    return search_start, search_end


def map_unmapped_tweets(
    session: Session,
    batch_size: int = 1000,
) -> dict:
    """
    Assign unmapped tweets to games.

    For each unmapped tweet:
    1. Convert posted_at to ET to determine the calendar date
    2. Search for games on that ET date and the previous day
    3. Check if posted_at falls within a game's window (5 AM ET → end + 3h)
    4. Set game_id and mapping_status='mapped', or 'no_game' if no match

    Args:
        session: Database session
        batch_size: Number of tweets to process per batch

    Returns:
        Summary stats dict with mapped, no_game, errors counts
    """
    from sqlalchemy import or_

    from ..db import db_models

    # Counters
    total_processed = 0
    mapped_count = 0
    no_game_count = 0
    errors: list[str] = []

    logger.info("tweet_mapper_start", batch_size=batch_size)

    # Process in batches to avoid memory issues
    while True:
        # Get batch of unmapped tweets
        unmapped_tweets = (
            session.query(db_models.TeamSocialPost)
            .filter(db_models.TeamSocialPost.mapping_status == "unmapped")
            .limit(batch_size)
            .all()
        )

        if not unmapped_tweets:
            break

        logger.debug("tweet_mapper_batch", batch_count=len(unmapped_tweets))

        for tweet in unmapped_tweets:
            total_processed += 1

            try:
                # Ensure posted_at is timezone-aware
                posted_at = tweet.posted_at
                if posted_at.tzinfo is None:
                    posted_at = posted_at.replace(tzinfo=UTC)

                # Search for games on the tweet's ET date and previous day
                search_start, search_end = _search_dates_for_tweet(posted_at)

                potential_games = (
                    session.query(db_models.SportsGame)
                    .filter(
                        or_(
                            db_models.SportsGame.home_team_id == tweet.team_id,
                            db_models.SportsGame.away_team_id == tweet.team_id,
                        ),
                        db_models.SportsGame.game_date >= search_start,
                        db_models.SportsGame.game_date <= search_end,
                    )
                    .all()
                )

                # Check each potential game's window
                matched_game = None
                for game in potential_games:
                    window_start, window_end = get_game_window(game)
                    if window_start <= posted_at <= window_end:
                        matched_game = game
                        break

                if matched_game:
                    tweet.game_id = matched_game.id
                    tweet.mapping_status = "mapped"
                    tweet.game_phase = classify_game_phase(posted_at, matched_game)
                    tweet.updated_at = now_utc()
                    mapped_count += 1
                    logger.debug(
                        "tweet_mapper_matched",
                        tweet_id=tweet.id,
                        game_id=matched_game.id,
                        posted_at=str(posted_at),
                        game_phase=tweet.game_phase,
                    )
                else:
                    tweet.mapping_status = "no_game"
                    tweet.game_phase = GamePhase.unknown
                    tweet.updated_at = now_utc()
                    no_game_count += 1
                    logger.debug(
                        "tweet_mapper_no_match",
                        tweet_id=tweet.id,
                        team_id=tweet.team_id,
                        posted_at=str(posted_at),
                    )

            except Exception as exc:
                error_msg = f"Tweet {tweet.id}: {str(exc)}"
                errors.append(error_msg)
                logger.exception(
                    "tweet_mapper_error",
                    tweet_id=tweet.id,
                    error=str(exc),
                )

        # Commit batch
        session.commit()

        logger.debug(
            "tweet_mapper_batch_complete",
            total_processed=total_processed,
            mapped=mapped_count,
            no_game=no_game_count,
        )

    logger.info(
        "tweet_mapper_complete",
        total_processed=total_processed,
        mapped=mapped_count,
        no_game=no_game_count,
        errors_count=len(errors),
    )

    return {
        "total_processed": total_processed,
        "mapped": mapped_count,
        "no_game": no_game_count,
        "errors": errors if errors else None,
    }


def map_tweets_for_team(
    session: Session,
    team_id: int,
) -> dict:
    """
    Map unmapped tweets for a specific team.

    Args:
        session: Database session
        team_id: Team ID to process

    Returns:
        Summary stats dict
    """
    from ..db import db_models

    logger.info("tweet_mapper_team_start", team_id=team_id)

    # Get unmapped tweets for this team
    unmapped_tweets = (
        session.query(db_models.TeamSocialPost)
        .filter(
            db_models.TeamSocialPost.team_id == team_id,
            db_models.TeamSocialPost.mapping_status == "unmapped",
        )
        .all()
    )

    if not unmapped_tweets:
        logger.info("tweet_mapper_team_no_unmapped", team_id=team_id)
        return {"team_id": team_id, "processed": 0, "mapped": 0, "no_game": 0}

    # Process each tweet
    mapped_count = 0
    no_game_count = 0

    for tweet in unmapped_tweets:
        posted_at = tweet.posted_at
        if posted_at.tzinfo is None:
            posted_at = posted_at.replace(tzinfo=UTC)

        # Search for games on the tweet's ET date and previous day
        search_start, search_end = _search_dates_for_tweet(posted_at)

        potential_games = (
            session.query(db_models.SportsGame)
            .filter(
                db_models.SportsGame.home_team_id == team_id,
                db_models.SportsGame.game_date >= search_start,
                db_models.SportsGame.game_date <= search_end,
            )
            .union(
                session.query(db_models.SportsGame).filter(
                    db_models.SportsGame.away_team_id == team_id,
                    db_models.SportsGame.game_date >= search_start,
                    db_models.SportsGame.game_date <= search_end,
                )
            )
            .all()
        )

        matched_game = None
        for game in potential_games:
            window_start, window_end = get_game_window(game)
            if window_start <= posted_at <= window_end:
                matched_game = game
                break

        if matched_game:
            tweet.game_id = matched_game.id
            tweet.mapping_status = "mapped"
            tweet.game_phase = classify_game_phase(posted_at, matched_game)
            tweet.updated_at = now_utc()
            mapped_count += 1
        else:
            tweet.mapping_status = "no_game"
            tweet.game_phase = GamePhase.unknown
            tweet.updated_at = now_utc()
            no_game_count += 1

    session.commit()

    logger.info(
        "tweet_mapper_team_complete",
        team_id=team_id,
        processed=len(unmapped_tweets),
        mapped=mapped_count,
        no_game=no_game_count,
    )

    return {
        "team_id": team_id,
        "processed": len(unmapped_tweets),
        "mapped": mapped_count,
        "no_game": no_game_count,
    }


def get_mapping_stats(session: Session) -> dict:
    """
    Get current mapping status distribution.

    Args:
        session: Database session

    Returns:
        Dict with counts per mapping_status
    """
    from sqlalchemy import func

    from ..db import db_models

    results = (
        session.query(
            db_models.TeamSocialPost.mapping_status,
            func.count(db_models.TeamSocialPost.id),
        )
        .group_by(db_models.TeamSocialPost.mapping_status)
        .all()
    )

    return {status: count for status, count in results}
