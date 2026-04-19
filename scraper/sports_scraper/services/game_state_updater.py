"""Game state updater: promote games through lifecycle states.

Pure DB operations — no external API calls. Designed to run every 3 minutes
via Celery beat. State transitions:

- scheduled → pregame: when now() >= game_date - pregame_window_hours
- pregame → live: when game_date < now() AND game_date + estimated_game_duration > now()
  (time-based fallback when scoreboard APIs don't report "live")
- scheduled/pregame/live → final: when game_date + estimated_game_duration_hours
  + postgame_window_hours < now() (stale timeout safety net — also catches
  live games whose polling missed the final update)
- final → archived: when game has timeline artifacts AND end_time < now() - 7 days

The live → final transition normally comes from API responses in the PBP
polling task. The stale timeout acts as a safety net in case polling misses
the final update (network issue, API glitch, worker crash).
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import exists
from sqlalchemy.orm import Session

from ..config_sports import LEAGUE_CONFIG
from ..db import db_models
from ..logging import logger
from ..utils.datetime_utils import now_utc

# How many days after final before archiving
_ARCHIVE_AFTER_DAYS = 7


def update_game_states(session: Session) -> dict[str, int]:
    """Run all state promotions. Returns counts of transitions made.

    This function is idempotent and safe to call at any frequency.
    Every transition is logged individually for traceability.
    """
    counts: dict[str, int] = {
        "scheduled_to_pregame": 0,
        "pregame_to_live": 0,
        "stale_to_final": 0,
        "phantom_canceled": 0,
        "final_to_archived": 0,
    }

    counts["scheduled_to_pregame"] = _promote_scheduled_to_pregame(session)
    counts["pregame_to_live"] = _promote_pregame_to_live(session)
    counts["stale_to_final"] = _promote_stale_to_final(session)
    counts["phantom_canceled"] = _cancel_phantom_finals(session)
    counts["final_to_archived"] = _promote_final_to_archived(session)

    total = sum(counts.values())
    if total > 0:
        logger.info("game_state_updater_transitions", **counts, total=total)
    else:
        logger.debug("game_state_updater_no_transitions")

    return counts


def _promote_scheduled_to_pregame(session: Session) -> int:
    """Promote scheduled games to pregame when within the pregame window.

    Uses per-league pregame_window_hours from config.
    """
    now = now_utc()
    promoted = 0

    # Group by league to apply per-league pregame windows
    for league_code, config in LEAGUE_CONFIG.items():
        cutoff = now + timedelta(hours=config.pregame_window_hours)

        league_id = (
            session.query(db_models.SportsLeague.id)
            .filter(db_models.SportsLeague.code == league_code)
            .scalar()
        )
        if league_id is None:
            continue

        games = (
            session.query(db_models.SportsGame)
            .filter(
                db_models.SportsGame.league_id == league_id,
                db_models.SportsGame.status == db_models.GameStatus.scheduled.value,
                db_models.SportsGame.game_date.isnot(None),
                db_models.SportsGame.game_date <= cutoff,
            )
            .all()
        )

        for game in games:
            game.status = db_models.GameStatus.pregame.value
            game.updated_at = now
            promoted += 1
            logger.info(
                "game_state_transition",
                game_id=game.id,
                league=league_code,
                from_status="scheduled",
                to_status="pregame",
                game_date=str(game.game_date),
            )

    return promoted


def _promote_pregame_to_live(session: Session) -> int:
    """Promote pregame games to live based on game_date.

    Time-based fallback for when scoreboard APIs don't reliably report "live".
    Condition: game_date < now AND game_date + estimated_game_duration > now.
    This ensures we only promote games that are plausibly in progress.
    """
    now = now_utc()
    promoted = 0

    for league_code, config in LEAGUE_CONFIG.items():
        duration = timedelta(hours=config.estimated_game_duration_hours)

        league_id = (
            session.query(db_models.SportsLeague.id)
            .filter(db_models.SportsLeague.code == league_code)
            .scalar()
        )
        if league_id is None:
            continue

        games = (
            session.query(db_models.SportsGame)
            .filter(
                db_models.SportsGame.league_id == league_id,
                db_models.SportsGame.status == db_models.GameStatus.pregame.value,
                db_models.SportsGame.game_date.isnot(None),
                db_models.SportsGame.game_date < now,  # past start time
                db_models.SportsGame.game_date > now - duration,  # not yet expired
            )
            .all()
        )

        for game in games:
            game.status = db_models.GameStatus.live.value
            game.updated_at = now
            promoted += 1
            logger.info(
                "game_state_transition",
                game_id=game.id,
                league=league_code,
                from_status="pregame",
                to_status="live",
                game_date=str(game.game_date),
                reason="time_based_promotion",
            )

    return promoted


def _is_phantom_game(game: db_models.SportsGame) -> bool:
    """Return True if a game has no evidence of being played.

    Phantom games are stubs created by odds feeds for conditional matchups
    (e.g., tournament "if-necessary" games) that never actually occurred.
    They have no scores, no PBP, no boxscore, and no scrape data.
    """
    return (
        game.home_score is None
        and game.away_score is None
        and game.last_pbp_at is None
        and game.last_boxscore_at is None
        and game.last_scraped_at is None
    )


def _cancel_phantom_finals(session: Session) -> int:
    """Cancel final games that were never actually played.

    Catches phantom games that were already promoted to final by
    earlier runs (before the phantom detection was added).
    """
    now = now_utc()
    canceled = 0

    games = (
        session.query(db_models.SportsGame)
        .filter(
            db_models.SportsGame.status == db_models.GameStatus.final.value,
            db_models.SportsGame.home_score.is_(None),
            db_models.SportsGame.away_score.is_(None),
            db_models.SportsGame.last_pbp_at.is_(None),
            db_models.SportsGame.last_boxscore_at.is_(None),
            db_models.SportsGame.last_scraped_at.is_(None),
        )
        .all()
    )

    for game in games:
        game.status = db_models.GameStatus.CANCELLED.value
        game.end_time = None
        game.updated_at = now
        canceled += 1
        logger.info(
            "game_state_transition",
            game_id=game.id,
            from_status="final",
            to_status="cancelled",
            game_date=str(game.game_date),
            reason="phantom_final_cancelled",
        )

    return canceled


def _has_recent_data(game: db_models.SportsGame, now, minutes: int = 30) -> bool:
    """Return True if the game received fresh PBP or boxscore data recently.

    Used to protect live games from the stale timeout during rain delays
    or extra innings — if data is still flowing, the game isn't stale.
    """
    cutoff = now - timedelta(minutes=minutes)
    return (
        (game.last_pbp_at is not None and game.last_pbp_at > cutoff)
        or (game.last_boxscore_at is not None and game.last_boxscore_at > cutoff)
    )


def _promote_stale_to_final(session: Session) -> int:
    """Force overdue scheduled/pregame/live games to final.

    Safety net for when APIs fail to report correct status. Also catches
    live games whose PBP polling missed the final update (network issue,
    API glitch, worker crash). Uses per-league estimated_game_duration_hours
    + postgame_window_hours as the maximum time before we infer the game
    is over.

    Live games that have received fresh data within the last 30 minutes
    are protected from the stale timeout — rain delays and extra innings
    can push games well past the estimated duration, but as long as data
    is still flowing the game should remain live.
    """
    now = now_utc()
    promoted = 0

    for league_code, config in LEAGUE_CONFIG.items():
        max_hours = config.estimated_game_duration_hours + config.postgame_window_hours
        stale_cutoff = now - timedelta(hours=max_hours)

        league_id = (
            session.query(db_models.SportsLeague.id)
            .filter(db_models.SportsLeague.code == league_code)
            .scalar()
        )
        if league_id is None:
            continue

        games = (
            session.query(db_models.SportsGame)
            .filter(
                db_models.SportsGame.league_id == league_id,
                db_models.SportsGame.status.in_(
                    [
                        db_models.GameStatus.scheduled.value,
                        db_models.GameStatus.pregame.value,
                        db_models.GameStatus.live.value,
                    ]
                ),
                db_models.SportsGame.game_date.isnot(None),
                db_models.SportsGame.game_date < stale_cutoff,
            )
            .all()
        )

        for game in games:
            old_status = game.status

            # Protect live games with recent data from the stale timeout.
            # Rain delays/extras can push games far past estimated duration,
            # but if data is still arriving the game isn't actually stale.
            if old_status == db_models.GameStatus.live.value and _has_recent_data(game, now):
                logger.info(
                    "game_state_transition_deferred",
                    game_id=game.id,
                    league=league_code,
                    from_status=old_status,
                    game_date=str(game.game_date),
                    last_pbp_at=str(game.last_pbp_at),
                    reason="recent_data_still_flowing",
                )
                continue

            never_played = _is_phantom_game(game)

            if never_played:
                game.status = db_models.GameStatus.CANCELLED.value
                game.end_time = None
                game.updated_at = now
                promoted += 1
                logger.info(
                    "game_state_transition",
                    game_id=game.id,
                    league=league_code,
                    from_status=old_status,
                    to_status="cancelled",
                    game_date=str(game.game_date),
                    reason="phantom_game_cancelled",
                )
            else:
                game.status = db_models.GameStatus.final.value
                game.end_time = game.game_date + timedelta(hours=config.estimated_game_duration_hours)
                game.updated_at = now
                promoted += 1
                if old_status == db_models.GameStatus.live.value:
                    logger.warning(
                        "game_state_transition",
                        game_id=game.id,
                        league=league_code,
                        from_status=old_status,
                        to_status="final",
                        game_date=str(game.game_date),
                        reason="stale_live_timeout",
                    )
                else:
                    logger.info(
                        "game_state_transition",
                        game_id=game.id,
                        league=league_code,
                        from_status=old_status,
                        to_status="final",
                        game_date=str(game.game_date),
                        reason="stale_timeout",
                    )

    return promoted


def _promote_final_to_archived(session: Session) -> int:
    """Archive final games that are complete and old enough.

    Criteria:
    - status = 'final'
    - end_time is set and > ARCHIVE_AFTER_DAYS days ago
    - Has at least one timeline artifact (flows generated)
    """
    now = now_utc()
    archive_cutoff = now - timedelta(days=_ARCHIVE_AFTER_DAYS)
    promoted = 0

    # Subquery: games with timeline artifacts
    has_artifacts = exists().where(
        db_models.SportsGameTimelineArtifact.game_id == db_models.SportsGame.id
    )

    games = (
        session.query(db_models.SportsGame)
        .filter(
            db_models.SportsGame.status == db_models.GameStatus.final.value,
            db_models.SportsGame.end_time.isnot(None),
            db_models.SportsGame.end_time < archive_cutoff,
            has_artifacts,
            db_models.SportsGame.social_scrape_2_at.isnot(None),
        )
        .all()
    )

    for game in games:
        game.status = db_models.GameStatus.archived.value
        game.closed_at = now
        game.updated_at = now
        promoted += 1
        logger.info(
            "game_state_transition",
            game_id=game.id,
            from_status="final",
            to_status="archived",
            end_time=str(game.end_time),
        )

    return promoted
