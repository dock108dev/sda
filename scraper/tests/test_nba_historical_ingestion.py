"""Tests for NBA historical ingestion service."""

from __future__ import annotations

import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRAPER_ROOT = REPO_ROOT / "scraper"
if str(SCRAPER_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRAPER_ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/test_db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ENVIRONMENT", "development")

from sports_scraper.models import (
    GameIdentification,
    NormalizedGame,
    NormalizedPlay,
    NormalizedPlayByPlay,
    NormalizedPlayerBoxscore,
    NormalizedTeamBoxscore,
    TeamIdentity,
)

_MOD = "sports_scraper.services.nba_historical_ingestion"


def _make_team(name: str, abbr: str) -> TeamIdentity:
    return TeamIdentity(league_code="NBA", name=name, abbreviation=abbr)


def _make_game(game_key: str = "202410220BOS") -> NormalizedGame:
    return NormalizedGame(
        identity=GameIdentification(
            league_code="NBA",
            season=2025,
            game_date=datetime(2024, 10, 22, tzinfo=UTC),
            home_team=_make_team("Boston Celtics", "BOS"),
            away_team=_make_team("New York Knicks", "NYK"),
            source_game_key=game_key,
        ),
        status="completed",
        home_score=132,
        away_score=109,
        team_boxscores=[
            NormalizedTeamBoxscore(
                team=_make_team("New York Knicks", "NYK"),
                is_home=False, points=109,
            ),
            NormalizedTeamBoxscore(
                team=_make_team("Boston Celtics", "BOS"),
                is_home=True, points=132,
            ),
        ],
        player_boxscores=[
            NormalizedPlayerBoxscore(
                player_id="tatumja01", player_name="Jayson Tatum",
                team=_make_team("Boston Celtics", "BOS"),
                points=37, rebounds=10, assists=5,
            ),
        ],
    )


class TestIngestNbaHistoricalBoxscores:
    @patch(f"{_MOD}.NBABasketballReferenceScraper")
    @patch(f"{_MOD}.upsert_player_boxscores")
    @patch(f"{_MOD}.upsert_team_boxscores")
    @patch(f"{_MOD}.upsert_game", return_value=(1, True))
    def test_basic_ingestion(self, mock_upsert_game, mock_team_box, mock_player_box, mock_scraper_cls):
        from sports_scraper.services.nba_historical_ingestion import ingest_nba_historical_boxscores

        mock_scraper = MagicMock()
        mock_scraper_cls.return_value = mock_scraper
        mock_scraper.iter_dates.return_value = [date(2024, 10, 22)]
        mock_scraper.fetch_games_for_date.return_value = [_make_game()]

        session = MagicMock()
        league = MagicMock()
        league.code = "NBA"
        session.query.return_value.filter.return_value.first.return_value = league

        processed, enriched, with_stats = ingest_nba_historical_boxscores(
            session, start_date=date(2024, 10, 22), end_date=date(2024, 10, 22),
        )

        assert processed == 1
        assert enriched == 1
        assert with_stats == 1
        mock_upsert_game.assert_called_once()
        mock_team_box.assert_called_once()
        mock_player_box.assert_called_once()
        session.commit.assert_called()

    @patch(f"{_MOD}.NBABasketballReferenceScraper")
    @patch(f"{_MOD}.upsert_player_boxscores")
    @patch(f"{_MOD}.upsert_team_boxscores")
    @patch(f"{_MOD}.upsert_game", return_value=(1, False))
    def test_only_missing_skips_existing(self, mock_upsert_game, mock_team_box, mock_player_box, mock_scraper_cls):
        from sports_scraper.services.nba_historical_ingestion import ingest_nba_historical_boxscores

        mock_scraper = MagicMock()
        mock_scraper_cls.return_value = mock_scraper
        mock_scraper.iter_dates.return_value = [date(2024, 10, 22)]
        mock_scraper.fetch_games_for_date.return_value = [_make_game()]

        session = MagicMock()
        league = MagicMock()
        league.code = "NBA"
        session.query.return_value.filter.return_value.first.return_value = league
        # Mock existing boxscores
        mock_existing = MagicMock()
        session.query.return_value.filter.return_value.first.side_effect = [
            league,  # league query
            mock_existing,  # has_team_box
            mock_existing,  # has_player_box
        ]

        processed, enriched, with_stats = ingest_nba_historical_boxscores(
            session, start_date=date(2024, 10, 22), end_date=date(2024, 10, 22),
            only_missing=True,
        )

        assert processed == 0
        mock_team_box.assert_not_called()
        mock_player_box.assert_not_called()

    @patch(f"{_MOD}.NBABasketballReferenceScraper")
    def test_league_not_found(self, mock_scraper_cls):
        from sports_scraper.services.nba_historical_ingestion import ingest_nba_historical_boxscores

        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = None

        processed, enriched, with_stats = ingest_nba_historical_boxscores(
            session, start_date=date(2024, 10, 22), end_date=date(2024, 10, 22),
        )
        assert processed == 0

    @patch(f"{_MOD}.NBABasketballReferenceScraper")
    @patch(f"{_MOD}.upsert_game", side_effect=Exception("DB error"))
    def test_per_game_rollback(self, mock_upsert_game, mock_scraper_cls):
        from sports_scraper.services.nba_historical_ingestion import ingest_nba_historical_boxscores

        mock_scraper = MagicMock()
        mock_scraper_cls.return_value = mock_scraper
        mock_scraper.iter_dates.return_value = [date(2024, 10, 22)]
        mock_scraper.fetch_games_for_date.return_value = [_make_game()]

        session = MagicMock()
        league = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = league

        processed, _, _ = ingest_nba_historical_boxscores(
            session, start_date=date(2024, 10, 22), end_date=date(2024, 10, 22),
        )
        assert processed == 0
        session.rollback.assert_called()


class TestIngestNbaHistoricalPbp:
    @patch(f"{_MOD}.NBABasketballReferenceScraper")
    @patch(f"{_MOD}.upsert_plays", return_value=5)
    def test_basic_pbp_ingestion(self, mock_upsert_plays, mock_scraper_cls):
        from sports_scraper.services.nba_historical_ingestion import ingest_nba_historical_pbp

        mock_scraper = MagicMock()
        mock_scraper_cls.return_value = mock_scraper
        pbp = NormalizedPlayByPlay(
            source_game_key="202410220BOS",
            plays=[
                NormalizedPlay(
                    play_index=10001, quarter=1, game_clock="12:00",
                    description="Jump ball",
                ),
            ],
        )
        mock_scraper.fetch_play_by_play.return_value = pbp

        session = MagicMock()
        league = MagicMock()
        league.id = 1
        session.query.return_value.filter.return_value.first.return_value = league

        # Mock game query
        game_rows = [(100, "202410220BOS", datetime(2024, 10, 22, tzinfo=UTC))]
        session.query.return_value.filter.return_value.all.return_value = game_rows

        # No existing plays (only_missing)
        session.query.return_value.filter.return_value.first.side_effect = [
            league,  # league query
            None,  # has_plays check
        ]

        count = ingest_nba_historical_pbp(
            session, start_date=date(2024, 10, 22), end_date=date(2024, 10, 22),
        )

        assert count == 1
        mock_upsert_plays.assert_called_once()
        session.commit.assert_called()

    @patch(f"{_MOD}.NBABasketballReferenceScraper")
    def test_no_games_found(self, mock_scraper_cls):
        from sports_scraper.services.nba_historical_ingestion import ingest_nba_historical_pbp

        session = MagicMock()
        league = MagicMock()
        league.id = 1
        session.query.return_value.filter.return_value.first.return_value = league
        session.query.return_value.filter.return_value.all.return_value = []

        count = ingest_nba_historical_pbp(
            session, start_date=date(2024, 10, 22), end_date=date(2024, 10, 22),
        )
        assert count == 0

    @patch(f"{_MOD}.NBABasketballReferenceScraper")
    def test_league_not_found_returns_zero(self, mock_scraper_cls):
        from sports_scraper.services.nba_historical_ingestion import ingest_nba_historical_pbp

        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = None

        count = ingest_nba_historical_pbp(
            session, start_date=date(2024, 10, 22), end_date=date(2024, 10, 22),
        )
        assert count == 0

    @patch(f"{_MOD}.NBABasketballReferenceScraper")
    @patch(f"{_MOD}.upsert_plays")
    def test_pbp_fetch_exception_rolls_back(self, mock_upsert_plays, mock_scraper_cls):
        """Covers lines 190-200: exception path during PBP fetch."""
        from sports_scraper.services.nba_historical_ingestion import ingest_nba_historical_pbp

        mock_scraper = MagicMock()
        mock_scraper_cls.return_value = mock_scraper
        mock_scraper.fetch_play_by_play.side_effect = Exception("scrape error")

        session = MagicMock()
        league = MagicMock()
        league.id = 1
        session.query.return_value.filter.return_value.first.return_value = league

        game_rows = [(100, "202410220BOS", datetime(2024, 10, 22, tzinfo=UTC))]
        session.query.return_value.filter.return_value.all.return_value = game_rows

        # No existing plays (only_missing check)
        session.query.return_value.filter.return_value.first.side_effect = [
            league,  # league query
            None,    # has_plays check returns None (no existing plays)
        ]

        count = ingest_nba_historical_pbp(
            session, start_date=date(2024, 10, 22), end_date=date(2024, 10, 22),
        )

        assert count == 0
        session.rollback.assert_called()

    @patch(f"{_MOD}.NBABasketballReferenceScraper")
    def test_pbp_not_implemented_skips(self, mock_scraper_cls):
        """Covers line 190: NotImplementedError path."""
        from sports_scraper.services.nba_historical_ingestion import ingest_nba_historical_pbp

        mock_scraper = MagicMock()
        mock_scraper_cls.return_value = mock_scraper
        mock_scraper.fetch_play_by_play.side_effect = NotImplementedError

        session = MagicMock()
        league = MagicMock()
        league.id = 1
        session.query.return_value.filter.return_value.first.return_value = league

        game_rows = [(100, "202410220BOS", datetime(2024, 10, 22, tzinfo=UTC))]
        session.query.return_value.filter.return_value.all.return_value = game_rows

        session.query.return_value.filter.return_value.first.side_effect = [
            league,
            None,  # has_plays
        ]

        count = ingest_nba_historical_pbp(
            session, start_date=date(2024, 10, 22), end_date=date(2024, 10, 22),
        )

        assert count == 0
        session.rollback.assert_not_called()

    @patch(f"{_MOD}.NBABasketballReferenceScraper")
    @patch(f"{_MOD}.upsert_plays", return_value=5)
    def test_pbp_skips_existing_plays(self, mock_upsert_plays, mock_scraper_cls):
        """Covers line 173: skips game that already has plays when only_missing=True."""
        from sports_scraper.services.nba_historical_ingestion import ingest_nba_historical_pbp

        mock_scraper = MagicMock()
        mock_scraper_cls.return_value = mock_scraper

        session = MagicMock()
        league = MagicMock()
        league.id = 1
        session.query.return_value.filter.return_value.first.return_value = league

        game_rows = [(100, "202410220BOS", datetime(2024, 10, 22, tzinfo=UTC))]
        session.query.return_value.filter.return_value.all.return_value = game_rows

        # has_plays returns existing play
        existing_play = MagicMock()
        session.query.return_value.filter.return_value.first.side_effect = [
            league,
            existing_play,  # has_plays check returns truthy
        ]

        count = ingest_nba_historical_pbp(
            session, start_date=date(2024, 10, 22), end_date=date(2024, 10, 22),
            only_missing=True,
        )

        assert count == 0
        mock_upsert_plays.assert_not_called()


class TestIngestNbaHistoricalBoxscoresDateFailure:
    @patch(f"{_MOD}.NBABasketballReferenceScraper")
    def test_date_fetch_exception_continues(self, mock_scraper_cls):
        """Covers lines 54-56: exception when fetching games for a date."""
        from sports_scraper.services.nba_historical_ingestion import ingest_nba_historical_boxscores

        mock_scraper = MagicMock()
        mock_scraper_cls.return_value = mock_scraper
        mock_scraper.iter_dates.return_value = [date(2024, 10, 22), date(2024, 10, 23)]
        mock_scraper.fetch_games_for_date.side_effect = Exception("network error")

        session = MagicMock()
        league = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = league

        processed, enriched, with_stats = ingest_nba_historical_boxscores(
            session, start_date=date(2024, 10, 22), end_date=date(2024, 10, 23),
        )

        assert processed == 0
        assert enriched == 0
        assert with_stats == 0
