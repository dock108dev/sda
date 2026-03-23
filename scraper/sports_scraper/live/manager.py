"""Orchestrates live feed polling and play-by-play ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import db_models
from ..logging import logger
from ..models import IngestionConfig, NormalizedPlay
from ..persistence.games import update_game_from_live_feed, upsert_game_stub
from ..persistence.plays import upsert_plays
from .mlb import MLBLiveFeedClient
from .mlb_constants import MLB_GAME_TYPE_MAP
from .nba import NBALiveFeedClient
from .nfl import NFLLiveFeedClient
from .nhl import NHLLiveFeedClient


@dataclass(frozen=True)
class LiveFeedSummary:
    games_touched: int
    pbp_games: int
    pbp_events: int


class LiveFeedManager:
    """Live feed integration that complements post-game Sports Reference data."""

    def __init__(self) -> None:
        self._nba_client = NBALiveFeedClient()
        self._nhl_client = NHLLiveFeedClient()
        self._mlb_client = MLBLiveFeedClient()
        self._nfl_client = NFLLiveFeedClient()

    def ingest_live_data(
        self,
        session: Session,
        *,
        config: IngestionConfig,
        updated_before: datetime | None,
    ) -> LiveFeedSummary:
        logger.info(
            "live_feed_poll_start",
            league=config.league_code,
            start_date=str(config.start_date),
            end_date=str(config.end_date),
        )

        if config.league_code == "NBA":
            summary = self._sync_nba(session, config, updated_before)
        elif config.league_code == "NHL":
            summary = self._sync_nhl(session, config, updated_before)
        elif config.league_code == "MLB":
            summary = self._sync_mlb(session, config, updated_before)
        elif config.league_code == "NFL":
            summary = self._sync_nfl(session, config, updated_before)
        elif config.league_code == "NCAAB":
            logger.info("live_feed_skipped", league=config.league_code, reason="no_live_pbp_feed")
            summary = LiveFeedSummary(games_touched=0, pbp_games=0, pbp_events=0)
        else:
            logger.info("live_feed_skipped", league=config.league_code, reason="unsupported_league")
            summary = LiveFeedSummary(games_touched=0, pbp_games=0, pbp_events=0)

        logger.info(
            "live_feed_poll_complete",
            league=config.league_code,
            games_touched=summary.games_touched,
            pbp_games=summary.pbp_games,
            pbp_events=summary.pbp_events,
        )
        return summary

    def _sync_nba(
        self,
        session: Session,
        config: IngestionConfig,
        updated_before: datetime | None,
    ) -> LiveFeedSummary:
        if not config.start_date or not config.end_date:
            return LiveFeedSummary(games_touched=0, pbp_games=0, pbp_events=0)

        games_touched = 0
        pbp_games = 0
        pbp_events = 0

        for day in _iter_dates(config.start_date, config.end_date):
            for live_game in self._nba_client.fetch_scoreboard(day):
                game = _find_game_by_abbr(session, "NBA", live_game.home_abbr, live_game.away_abbr, day)
                if not game:
                    logger.warning(
                        "nba_live_game_unmatched",
                        home=live_game.home_abbr,
                        away=live_game.away_abbr,
                        game_date=str(day),
                    )
                    continue

                # Live feeds keep game status/timelines accurate; post-game boxscores remain Sports Reference only.
                games_touched += 1
                logger.info(
                    "live_game_resolution",
                    league=config.league_code,
                    game_id=game.id,
                    external_id=live_game.game_id,
                )
                updated = update_game_from_live_feed(
                    session,
                    game=game,
                    status=live_game.status,
                    home_score=live_game.home_score,
                    away_score=live_game.away_score,
                    external_ids={"nba_game_id": live_game.game_id},
                )
                if updated:
                    logger.info("nba_live_game_updated", game_id=game.id, status=game.status)

                if _should_skip_pbp(session, game.id, config.only_missing, updated_before):
                    logger.info(
                        "pbp_game_skipped",
                        league=config.league_code,
                        game_id=game.id,
                        external_id=live_game.game_id,
                        reason="already_ingested",
                    )
                    continue

                pbp_result = self._ingest_pbp_for_game(
                    session,
                    game,
                    live_game.game_id,
                    self._nba_client.fetch_play_by_play,
                    source="nba_live",
                )
                if pbp_result > 0:
                    pbp_games += 1
                    pbp_events += pbp_result

        return LiveFeedSummary(games_touched=games_touched, pbp_games=pbp_games, pbp_events=pbp_events)

    def _sync_nhl(
        self,
        session: Session,
        config: IngestionConfig,
        updated_before: datetime | None,
    ) -> LiveFeedSummary:
        if not config.start_date or not config.end_date:
            return LiveFeedSummary(games_touched=0, pbp_games=0, pbp_events=0)

        games_touched = 0
        pbp_games = 0
        pbp_events = 0

        for live_game in self._nhl_client.fetch_schedule(config.start_date, config.end_date):
            game_id, created = upsert_game_stub(
                session,
                league_code="NHL",
                game_date=live_game.game_date,
                home_team=live_game.home_team,
                away_team=live_game.away_team,
                status=live_game.status,
                home_score=live_game.home_score,
                away_score=live_game.away_score,
                external_ids={"nhl_game_pk": live_game.game_id},
            )
            games_touched += 1
            logger.info(
                "live_game_resolution",
                league=config.league_code,
                game_id=game_id,
                external_id=live_game.game_id,
            )
            logger.info(
                "nhl_live_game_upserted",
                game_id=game_id,
                created=created,
                status=live_game.status,
            )

            game = session.get(db_models.SportsGame, game_id)
            if not game:
                continue

            if _should_skip_pbp(session, game_id, config.only_missing, updated_before):
                logger.info(
                    "pbp_game_skipped",
                    league=config.league_code,
                    game_id=game_id,
                    external_id=live_game.game_id,
                    reason="already_ingested",
                )
                continue

            pbp_result = self._ingest_pbp_for_game(
                session,
                game,
                live_game.game_id,
                self._nhl_client.fetch_play_by_play,
                source="nhl_api",
            )
            if pbp_result > 0:
                pbp_games += 1
                pbp_events += pbp_result

        return LiveFeedSummary(games_touched=games_touched, pbp_games=pbp_games, pbp_events=pbp_events)

    def _sync_mlb(
        self,
        session: Session,
        config: IngestionConfig,
        updated_before: datetime | None,
    ) -> LiveFeedSummary:
        if not config.start_date or not config.end_date:
            return LiveFeedSummary(games_touched=0, pbp_games=0, pbp_events=0)

        games_touched = 0
        pbp_games = 0
        pbp_events = 0

        for live_game in self._mlb_client.fetch_schedule(config.start_date, config.end_date):
            season_type = MLB_GAME_TYPE_MAP.get(live_game.game_type, "regular") if live_game.game_type else "regular"
            game_id, created = upsert_game_stub(
                session,
                league_code="MLB",
                game_date=live_game.game_date,
                home_team=live_game.home_team,
                away_team=live_game.away_team,
                status=live_game.status,
                home_score=live_game.home_score,
                away_score=live_game.away_score,
                external_ids={"mlb_game_pk": live_game.game_pk},
                season_type=season_type,
            )
            games_touched += 1
            logger.info(
                "live_game_resolution",
                league=config.league_code,
                game_id=game_id,
                external_id=live_game.game_pk,
            )
            logger.info(
                "mlb_live_game_upserted",
                game_id=game_id,
                created=created,
                status=live_game.status,
            )

            game = session.get(db_models.SportsGame, game_id)
            if not game:
                continue

            if _should_skip_pbp(session, game_id, config.only_missing, updated_before):
                logger.info(
                    "pbp_game_skipped",
                    league=config.league_code,
                    game_id=game_id,
                    external_id=live_game.game_pk,
                    reason="already_ingested",
                )
                continue

            pbp_result = self._ingest_pbp_for_game(
                session,
                game,
                live_game.game_pk,
                self._mlb_client.fetch_play_by_play,
                source="mlb_api",
            )
            if pbp_result > 0:
                pbp_games += 1
                pbp_events += pbp_result

        return LiveFeedSummary(games_touched=games_touched, pbp_games=pbp_games, pbp_events=pbp_events)

    def _sync_nfl(
        self,
        session: Session,
        config: IngestionConfig,
        updated_before: datetime | None,
    ) -> LiveFeedSummary:
        if not config.start_date or not config.end_date:
            return LiveFeedSummary(games_touched=0, pbp_games=0, pbp_events=0)

        games_touched = 0
        pbp_games = 0
        pbp_events = 0

        for live_game in self._nfl_client.fetch_schedule(config.start_date, config.end_date):
            # Skip preseason games by default
            if live_game.season_type == "preseason":
                continue

            season_type = live_game.season_type or "regular"
            game_id, created = upsert_game_stub(
                session,
                league_code="NFL",
                game_date=live_game.game_date,
                home_team=live_game.home_team,
                away_team=live_game.away_team,
                status=live_game.status,
                home_score=live_game.home_score,
                away_score=live_game.away_score,
                external_ids={"espn_game_id": live_game.game_id},
                season_type=season_type,
            )
            games_touched += 1
            logger.info(
                "live_game_resolution",
                league=config.league_code,
                game_id=game_id,
                external_id=live_game.game_id,
            )
            logger.info(
                "nfl_live_game_upserted",
                game_id=game_id,
                created=created,
                status=live_game.status,
            )

            game = session.get(db_models.SportsGame, game_id)
            if not game:
                continue

            if _should_skip_pbp(session, game_id, config.only_missing, updated_before):
                logger.info(
                    "pbp_game_skipped",
                    league=config.league_code,
                    game_id=game_id,
                    external_id=live_game.game_id,
                    reason="already_ingested",
                )
                continue

            pbp_result = self._ingest_pbp_for_game(
                session,
                game,
                live_game.game_id,
                self._nfl_client.fetch_play_by_play,
                source="espn_nfl_api",
            )
            if pbp_result > 0:
                pbp_games += 1
                pbp_events += pbp_result

        return LiveFeedSummary(games_touched=games_touched, pbp_games=pbp_games, pbp_events=pbp_events)

    def _ingest_pbp_for_game(
        self,
        session: Session,
        game: db_models.SportsGame,
        source_key: str | int,
        fetcher,
        source: str = "live_feed",
    ) -> int:
        max_index = _max_play_index(session, game.id)
        pbp_payload = fetcher(source_key)
        if not pbp_payload.plays:
            logger.info("pbp_empty", game_id=game.id, source_key=str(source_key))
            return 0

        new_plays = _filter_new_plays(pbp_payload.plays, max_index)
        if not new_plays:
            logger.info("pbp_no_new_events", game_id=game.id, max_index=max_index)
            return 0

        inserted = upsert_plays(session, game.id, new_plays, source=source)
        if inserted:
            update_game_from_live_feed(
                session,
                game=game,
                status="live",
                home_score=game.home_score,
                away_score=game.away_score,
            )
        logger.info(
            "pbp_ingested",
            game_id=game.id,
            inserted=inserted,
            source_key=str(source_key),
        )
        return inserted


def _iter_dates(start: date, end: date) -> list[date]:
    current = start
    dates: list[date] = []
    while current <= end:
        dates.append(current)
        current = current + timedelta(days=1)
    return dates


def _find_game_by_abbr(
    session: Session,
    league_code: str,
    home_abbr: str,
    away_abbr: str,
    day: date,
) -> db_models.SportsGame | None:
    league = session.query(db_models.SportsLeague).filter(db_models.SportsLeague.code == league_code).first()
    if not league:
        return None

    home_team = (
        session.query(db_models.SportsTeam)
        .filter(db_models.SportsTeam.league_id == league.id)
        .filter(db_models.SportsTeam.abbreviation == home_abbr)
        .first()
    )
    away_team = (
        session.query(db_models.SportsTeam)
        .filter(db_models.SportsTeam.league_id == league.id)
        .filter(db_models.SportsTeam.abbreviation == away_abbr)
        .first()
    )
    if not home_team or not away_team:
        logger.warning("live_feed_team_not_found", league=league_code, home=home_abbr, away=away_abbr)
        return None

    day_start = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
    day_end = datetime.combine(day, datetime.max.time(), tzinfo=UTC)
    return (
        session.query(db_models.SportsGame)
        .filter(db_models.SportsGame.league_id == league.id)
        .filter(db_models.SportsGame.home_team_id == home_team.id)
        .filter(db_models.SportsGame.away_team_id == away_team.id)
        .filter(db_models.SportsGame.game_date >= day_start)
        .filter(db_models.SportsGame.game_date <= day_end)
        .first()
    )


def _max_play_index(session: Session, game_id: int) -> int | None:
    stmt = select(func.max(db_models.SportsGamePlay.play_index)).where(db_models.SportsGamePlay.game_id == game_id)
    return session.execute(stmt).scalar()


def _filter_new_plays(plays: list[NormalizedPlay], max_index: int | None) -> list[NormalizedPlay]:
    if max_index is None:
        return plays
    return [play for play in plays if play.play_index > max_index]


def _should_skip_pbp(
    session: Session,
    game_id: int,
    only_missing: bool,
    updated_before: datetime | None,
) -> bool:
    if only_missing:
        stmt = select(func.count(db_models.SportsGamePlay.id)).where(db_models.SportsGamePlay.game_id == game_id)
        return (session.execute(stmt).scalar() or 0) > 0
    if updated_before:
        stmt = select(func.max(db_models.SportsGamePlay.updated_at)).where(db_models.SportsGamePlay.game_id == game_id)
        latest_update = session.execute(stmt).scalar()
        return latest_update is not None and latest_update >= updated_before
    return False
