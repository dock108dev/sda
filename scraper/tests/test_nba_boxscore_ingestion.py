"""Tests for services/nba_boxscore_ingestion.py — targeting ≥80% coverage."""

from __future__ import annotations

import os
import sys
from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRAPER_ROOT = REPO_ROOT / "scraper"
if str(SCRAPER_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRAPER_ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/test_db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ENVIRONMENT", "development")

from sports_scraper.services.nba_boxscore_ingestion import (
    _enrich_game_from_boxscore,
    _team_identity_from_db,
    ingest_boxscores_via_nba_api,
    select_games_for_boxscores_nba_api,
)


# ---------------------------------------------------------------------------
# select_games_for_boxscores_nba_api
# ---------------------------------------------------------------------------

class TestSelectGamesForBoxscoresNbaApi:
    def test_no_league_returns_empty(self):
        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = None

        result = select_games_for_boxscores_nba_api(
            session, start_date=date(2024, 1, 1), end_date=date(2024, 1, 2),
            only_missing=False, updated_before=None,
        )
        assert result == []

    def test_returns_valid_games(self):
        session = MagicMock()
        league = MagicMock(id=1)
        session.query.return_value.filter.return_value.first.return_value = league

        game_date = datetime(2024, 1, 15, 17, 0, tzinfo=UTC)  # noon ET
        row = (100, "0022400123", game_date)
        session.query.return_value.filter.return_value.all.return_value = [row]

        result = select_games_for_boxscores_nba_api(
            session, start_date=date(2024, 1, 1), end_date=date(2024, 1, 31),
            only_missing=False, updated_before=None,
        )
        assert len(result) == 1
        assert result[0] == (100, "0022400123", date(2024, 1, 15))

    def test_skips_none_nba_game_id(self):
        session = MagicMock()
        league = MagicMock(id=1)
        session.query.return_value.filter.return_value.first.return_value = league

        game_date = datetime(2024, 1, 15, tzinfo=UTC)
        row = (100, None, game_date)
        session.query.return_value.filter.return_value.all.return_value = [row]

        result = select_games_for_boxscores_nba_api(
            session, start_date=date(2024, 1, 1), end_date=date(2024, 1, 31),
            only_missing=False, updated_before=None,
        )
        assert result == []

    def test_skips_none_game_date(self):
        session = MagicMock()
        league = MagicMock(id=1)
        session.query.return_value.filter.return_value.first.return_value = league

        row = (100, "0022400123", None)
        session.query.return_value.filter.return_value.all.return_value = [row]

        result = select_games_for_boxscores_nba_api(
            session, start_date=date(2024, 1, 1), end_date=date(2024, 1, 31),
            only_missing=False, updated_before=None,
        )
        assert result == []

    def test_only_missing_applies_filter(self):
        session = MagicMock()
        league = MagicMock(id=1)
        session.query.return_value.filter.return_value.first.return_value = league
        session.query.return_value.filter.return_value.filter.return_value.all.return_value = []

        result = select_games_for_boxscores_nba_api(
            session, start_date=date(2024, 1, 1), end_date=date(2024, 1, 31),
            only_missing=True, updated_before=None,
        )
        assert result == []

    def test_updated_before_applies_filter(self):
        session = MagicMock()
        league = MagicMock(id=1)
        session.query.return_value.filter.return_value.first.return_value = league
        session.query.return_value.filter.return_value.filter.return_value.all.return_value = []

        result = select_games_for_boxscores_nba_api(
            session, start_date=date(2024, 1, 1), end_date=date(2024, 1, 31),
            only_missing=False, updated_before=datetime(2024, 1, 10, tzinfo=UTC),
        )
        assert result == []


# ---------------------------------------------------------------------------
# _team_identity_from_db
# ---------------------------------------------------------------------------

class TestTeamIdentityFromDb:
    def test_returns_identity_from_team(self):
        session = MagicMock()
        team = MagicMock(abbreviation="BOS", league_id=1)
        team.name = "Boston Celtics"  # `name` is special on MagicMock
        league = MagicMock(code="NBA")

        # first call → team, second call → league
        session.get.side_effect = [team, league]
        result = _team_identity_from_db(session, 10)

        assert result.abbreviation == "BOS"
        assert result.league_code == "NBA"

    def test_handles_missing_team(self):
        session = MagicMock()
        session.get.return_value = None

        result = _team_identity_from_db(session, 999)

        assert result.abbreviation == "UNK"
        assert result.name == "Unknown"


# ---------------------------------------------------------------------------
# _enrich_game_from_boxscore
# ---------------------------------------------------------------------------

class TestEnrichGameFromBoxscore:
    @patch("sports_scraper.services.nba_boxscore_ingestion._normalize_status", return_value="final")
    @patch("sports_scraper.services.nba_boxscore_ingestion.resolve_status_transition")
    def test_updates_scores(self, mock_resolve, mock_normalize):
        session = MagicMock()
        game = MagicMock()
        game.home_score = 90
        game.away_score = 85
        game.source_game_key = None
        game.status = "scheduled"
        mock_resolve.return_value = "final"

        boxscore = MagicMock()
        boxscore.home_score = 110
        boxscore.away_score = 100
        boxscore.game_id = "0022400123"
        boxscore.status = "final"

        result = _enrich_game_from_boxscore(session, game, boxscore)

        assert result is True
        assert game.home_score == 110
        assert game.away_score == 100
        assert game.source_game_key == "0022400123"
        session.flush.assert_called_once()

    @patch("sports_scraper.services.nba_boxscore_ingestion._normalize_status", return_value="final")
    @patch("sports_scraper.services.nba_boxscore_ingestion.resolve_status_transition")
    def test_no_update_when_same_scores(self, mock_resolve, mock_normalize):
        session = MagicMock()
        game = MagicMock()
        game.home_score = 110
        game.away_score = 100
        game.source_game_key = "0022400123"
        game.status = "final"
        mock_resolve.return_value = "final"

        boxscore = MagicMock()
        boxscore.home_score = 110
        boxscore.away_score = 100
        boxscore.game_id = "0022400123"
        boxscore.status = "final"

        result = _enrich_game_from_boxscore(session, game, boxscore)

        assert result is False
        session.flush.assert_not_called()

    @patch("sports_scraper.services.nba_boxscore_ingestion._normalize_status", return_value="final")
    @patch("sports_scraper.services.nba_boxscore_ingestion.resolve_status_transition")
    def test_status_transition_triggers_update(self, mock_resolve, mock_normalize):
        session = MagicMock()
        game = MagicMock()
        game.home_score = 110
        game.away_score = 100
        game.source_game_key = "0022400123"
        game.status = "scheduled"
        mock_resolve.return_value = "final"

        boxscore = MagicMock()
        boxscore.home_score = 110
        boxscore.away_score = 100
        boxscore.game_id = "0022400123"
        boxscore.status = "final"

        result = _enrich_game_from_boxscore(session, game, boxscore)

        assert result is True
        assert game.status == "final"

    @patch("sports_scraper.services.nba_boxscore_ingestion._normalize_status", return_value="final")
    @patch("sports_scraper.services.nba_boxscore_ingestion.resolve_status_transition")
    def test_none_scores_not_updated(self, mock_resolve, mock_normalize):
        session = MagicMock()
        game = MagicMock()
        game.home_score = 110
        game.away_score = 100
        game.source_game_key = "existing"
        game.status = "final"
        mock_resolve.return_value = "final"

        boxscore = MagicMock()
        boxscore.home_score = None
        boxscore.away_score = None
        boxscore.game_id = "0022400123"
        boxscore.status = "final"

        result = _enrich_game_from_boxscore(session, game, boxscore)
        assert result is False


# ---------------------------------------------------------------------------
# ingest_boxscores_via_nba_api
# ---------------------------------------------------------------------------

class TestIngestBoxscoresViaNbaApi:
    @patch("sports_scraper.services.nba_boxscore_ingestion.select_games_for_boxscores_nba_api", return_value=[])
    @patch("sports_scraper.services.nba_boxscore_ingestion.populate_nba_game_ids")
    def test_no_games_returns_zeros(self, mock_populate, mock_select):
        session = MagicMock()
        result = ingest_boxscores_via_nba_api(
            session, run_id=1, start_date=date(2024, 1, 1), end_date=date(2024, 1, 2),
            only_missing=False, updated_before=None,
        )
        assert result == (0, 0, 0, 0)

    @patch("sports_scraper.live.nba.NBALiveFeedClient")
    @patch("sports_scraper.services.nba_boxscore_ingestion.upsert_player_boxscores")
    @patch("sports_scraper.services.nba_boxscore_ingestion.upsert_team_boxscores")
    @patch("sports_scraper.services.nba_boxscore_ingestion._enrich_game_from_boxscore", return_value=True)
    @patch("sports_scraper.services.nba_boxscore_ingestion._team_identity_from_db")
    @patch("sports_scraper.services.nba_boxscore_ingestion.select_games_for_boxscores_nba_api")
    @patch("sports_scraper.services.nba_boxscore_ingestion.populate_nba_game_ids")
    def test_processes_games_with_player_stats(
        self, mock_populate, mock_select, mock_team_id, mock_enrich,
        mock_upsert_team, mock_upsert_player, mock_client_cls,
    ):
        mock_select.return_value = [(100, "0022400123", date(2024, 1, 15))]

        boxscore = MagicMock()
        boxscore.home_team.abbreviation = "BOS"
        tb1 = MagicMock(is_home=True)
        tb2 = MagicMock(is_home=False)
        boxscore.team_boxscores = [tb1, tb2]
        pb1 = MagicMock()
        pb1.team.abbreviation = "BOS"
        pb2 = MagicMock()
        pb2.team.abbreviation = "NYK"
        boxscore.player_boxscores = [pb1, pb2]
        mock_client_cls.return_value.fetch_boxscore.return_value = boxscore

        game = MagicMock(id=100, home_team_id=10, away_team_id=20)
        session = MagicMock()
        session.get.return_value = game

        home_identity = MagicMock(abbreviation="BOS")
        away_identity = MagicMock(abbreviation="NYK")
        mock_team_id.side_effect = [home_identity, away_identity]

        player_stats = MagicMock(inserted=5)
        mock_upsert_player.return_value = player_stats

        result = ingest_boxscores_via_nba_api(
            session, run_id=1, start_date=date(2024, 1, 1), end_date=date(2024, 1, 31),
            only_missing=False, updated_before=None,
        )

        assert result == (1, 1, 1, 0)
        mock_upsert_team.assert_called_once()
        mock_upsert_player.assert_called_once()

    @patch("sports_scraper.live.nba.NBALiveFeedClient")
    @patch("sports_scraper.services.nba_boxscore_ingestion.select_games_for_boxscores_nba_api")
    @patch("sports_scraper.services.nba_boxscore_ingestion.populate_nba_game_ids")
    def test_skips_empty_boxscore(self, mock_populate, mock_select, mock_client_cls):
        mock_select.return_value = [(100, "0022400123", date(2024, 1, 15))]
        mock_client_cls.return_value.fetch_boxscore.return_value = None

        session = MagicMock()
        result = ingest_boxscores_via_nba_api(
            session, run_id=1, start_date=date(2024, 1, 1), end_date=date(2024, 1, 31),
            only_missing=False, updated_before=None,
        )
        assert result == (0, 0, 0, 0)

    @patch("sports_scraper.live.nba.NBALiveFeedClient")
    @patch("sports_scraper.services.nba_boxscore_ingestion.select_games_for_boxscores_nba_api")
    @patch("sports_scraper.services.nba_boxscore_ingestion.populate_nba_game_ids")
    def test_skips_missing_game_in_db(self, mock_populate, mock_select, mock_client_cls):
        mock_select.return_value = [(100, "0022400123", date(2024, 1, 15))]
        mock_client_cls.return_value.fetch_boxscore.return_value = MagicMock()

        session = MagicMock()
        session.get.return_value = None  # game not found

        result = ingest_boxscores_via_nba_api(
            session, run_id=1, start_date=date(2024, 1, 1), end_date=date(2024, 1, 31),
            only_missing=False, updated_before=None,
        )
        assert result == (0, 0, 0, 0)

    @patch("sports_scraper.live.nba.NBALiveFeedClient")
    @patch("sports_scraper.services.nba_boxscore_ingestion.select_games_for_boxscores_nba_api")
    @patch("sports_scraper.services.nba_boxscore_ingestion.populate_nba_game_ids")
    def test_handles_fetch_exception(self, mock_populate, mock_select, mock_client_cls):
        mock_select.return_value = [(100, "0022400123", date(2024, 1, 15))]
        mock_client_cls.return_value.fetch_boxscore.side_effect = Exception("timeout")

        session = MagicMock()
        result = ingest_boxscores_via_nba_api(
            session, run_id=1, start_date=date(2024, 1, 1), end_date=date(2024, 1, 31),
            only_missing=False, updated_before=None,
        )
        assert result == (0, 0, 0, 1)

    @patch("sports_scraper.live.nba.NBALiveFeedClient")
    @patch("sports_scraper.services.nba_boxscore_ingestion.upsert_team_boxscores")
    @patch("sports_scraper.services.nba_boxscore_ingestion._enrich_game_from_boxscore", return_value=False)
    @patch("sports_scraper.services.nba_boxscore_ingestion._team_identity_from_db")
    @patch("sports_scraper.services.nba_boxscore_ingestion.select_games_for_boxscores_nba_api")
    @patch("sports_scraper.services.nba_boxscore_ingestion.populate_nba_game_ids")
    def test_no_player_stats(
        self, mock_populate, mock_select, mock_team_id, mock_enrich,
        mock_upsert_team, mock_client_cls,
    ):
        mock_select.return_value = [(100, "0022400123", date(2024, 1, 15))]

        boxscore = MagicMock()
        boxscore.home_team.abbreviation = "BOS"
        boxscore.team_boxscores = [MagicMock(is_home=True)]
        boxscore.player_boxscores = []  # no player boxscores
        mock_client_cls.return_value.fetch_boxscore.return_value = boxscore

        game = MagicMock(id=100, home_team_id=10, away_team_id=20)
        session = MagicMock()
        session.get.return_value = game
        mock_team_id.return_value = MagicMock()

        result = ingest_boxscores_via_nba_api(
            session, run_id=1, start_date=date(2024, 1, 1), end_date=date(2024, 1, 31),
            only_missing=False, updated_before=None,
        )

        assert result == (1, 0, 0, 0)
