"""Calendar polling Celery task."""

from __future__ import annotations

from datetime import UTC

from celery import shared_task

from ..logging import logger

_CALENDAR_LOOKAHEAD_DAYS = 7


@shared_task(name="poll_game_calendars")
def poll_game_calendars() -> dict:
    """Lightweight calendar poll that creates game stubs for all leagues.

    Looks 7 days ahead so upcoming games (including postseason matchups,
    schedule changes, and rain-delay reschedules) are in the DB well
    before tip-off.  Runs every 15 minutes.  Idempotent — existing
    games are not duplicated.
    """
    from datetime import datetime, timedelta

    from ..db import get_session
    from ..models import TeamIdentity
    from ..persistence.games import upsert_game_stub
    from ..utils.datetime_utils import sports_today_et

    today = sports_today_et()
    end_day = today + timedelta(days=_CALENDAR_LOOKAHEAD_DAYS)
    days = [today + timedelta(days=i) for i in range(_CALENDAR_LOOKAHEAD_DAYS)]

    results: dict[str, dict] = {}

    # --- NBA (scoreboard is per-day) ---
    try:
        from ..live.nba import NBALiveFeedClient

        client = NBALiveFeedClient()
        created = 0
        with get_session() as session:
            for day in days:
                for game in client.fetch_scoreboard(day):
                    try:
                        _gid, was_created = upsert_game_stub(
                            session,
                            league_code="NBA",
                            game_date=game.game_date,
                            home_team=TeamIdentity(name="", abbreviation=game.home_abbr),
                            away_team=TeamIdentity(name="", abbreviation=game.away_abbr),
                            status=game.status,
                            home_score=game.home_score,
                            away_score=game.away_score,
                        )
                        if was_created:
                            created += 1
                    except Exception as exc:
                        logger.debug("game_stub_error", error=str(exc))
            session.commit()
        results["NBA"] = {"created": created, "status": "ok"}
    except Exception as exc:
        logger.warning("calendar_poll_nba_failed", error=str(exc))
        results["NBA"] = {"created": 0, "status": "error", "error": str(exc)}

    # --- NHL (schedule supports date range) ---
    try:
        from ..live.nhl import NHLLiveFeedClient

        client = NHLLiveFeedClient()
        created = 0
        with get_session() as session:
            for game in client.fetch_schedule(today, end_day):
                try:
                    _gid, was_created = upsert_game_stub(
                        session,
                        league_code="NHL",
                        game_date=game.game_date,
                        home_team=game.home_team,
                        away_team=game.away_team,
                        status=game.status,
                        home_score=game.home_score,
                        away_score=game.away_score,
                        external_ids={"nhl_game_id": str(game.game_id)},
                    )
                    if was_created:
                        created += 1
                except Exception as exc:
                    logger.debug("game_stub_error", error=str(exc))
            session.commit()
        results["NHL"] = {"created": created, "status": "ok"}
    except Exception as exc:
        logger.warning("calendar_poll_nhl_failed", error=str(exc))
        results["NHL"] = {"created": 0, "status": "error", "error": str(exc)}

    # --- MLB (schedule supports date range) ---
    try:
        from ..services.mlb_boxscore_ingestion import populate_mlb_games_from_schedule

        with get_session() as session:
            created = populate_mlb_games_from_schedule(
                session, start_date=today, end_date=end_day,
            )
            session.commit()
        results["MLB"] = {"created": created, "status": "ok"}
    except Exception as exc:
        logger.warning("calendar_poll_mlb_failed", error=str(exc))
        results["MLB"] = {"created": 0, "status": "error", "error": str(exc)}

    # --- NCAAB (scoreboard is per-day; future dates may have limited data) ---
    try:
        import httpx

        from ..live.ncaa_scoreboard import NCAAScoreboardClient

        client = NCAAScoreboardClient(httpx.Client(timeout=20))
        created = 0
        with get_session() as session:
            for day in days:
                try:
                    scoreboard_games = client.fetch_scoreboard(day)
                except Exception as exc:
                    logger.debug(
                        "ncaa_scoreboard_day_unavailable",
                        day=str(day),
                        error=str(exc),
                    )
                    continue  # NCAA API may not support all future dates
                for game in scoreboard_games:
                    try:
                        if game.start_time_epoch:
                            game_date = datetime.fromtimestamp(
                                game.start_time_epoch / 1000, tz=UTC,
                            )
                        else:
                            game_date = datetime.combine(
                                day, datetime.min.time(),
                            ).replace(hour=12, tzinfo=UTC)

                        _gid, was_created = upsert_game_stub(
                            session,
                            league_code="NCAAB",
                            game_date=game_date,
                            home_team=TeamIdentity(
                                name=game.home_team_short, abbreviation="",
                            ),
                            away_team=TeamIdentity(
                                name=game.away_team_short, abbreviation="",
                            ),
                            status=game.game_state,
                            home_score=game.home_score,
                            away_score=game.away_score,
                            external_ids={"ncaa_game_id": game.ncaa_game_id},
                        )
                        if was_created:
                            created += 1
                    except Exception as exc:
                        logger.debug("game_stub_error", error=str(exc))
            session.commit()
        results["NCAAB"] = {"created": created, "status": "ok"}
    except Exception as exc:
        logger.warning("calendar_poll_ncaab_failed", error=str(exc))
        results["NCAAB"] = {"created": 0, "status": "error", "error": str(exc)}

    # --- NFL (ESPN scoreboard, date range via per-day iteration) ---
    try:
        from ..live.nfl import NFLLiveFeedClient

        client = NFLLiveFeedClient()
        created = 0
        with get_session() as session:
            for game in client.fetch_schedule(today, end_day):
                try:
                    if game.season_type == "preseason":
                        continue
                    _gid, was_created = upsert_game_stub(
                        session,
                        league_code="NFL",
                        game_date=game.game_date,
                        home_team=game.home_team,
                        away_team=game.away_team,
                        status=game.status,
                        home_score=game.home_score,
                        away_score=game.away_score,
                        external_ids={"espn_game_id": game.game_id},
                        season_type=game.season_type or "regular",
                    )
                    if was_created:
                        created += 1
                except Exception as exc:
                    logger.debug("game_stub_error", error=str(exc))
            session.commit()
        results["NFL"] = {"created": created, "status": "ok"}
    except Exception as exc:
        logger.warning("calendar_poll_nfl_failed", error=str(exc))
        results["NFL"] = {"created": 0, "status": "error", "error": str(exc)}

    total_created = sum(r.get("created", 0) for r in results.values())
    logger.info(
        "calendar_poll_complete",
        total_created=total_created,
        results=results,
    )

    return {"total_created": total_created, "leagues": results}

