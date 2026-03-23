"""Tests for services/mlb_boxscore_ingestion.py — targeting ≥80% coverage."""

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

from sports_scraper.models import NormalizedTeamBoxscore, TeamIdentity
from sports_scraper.services.mlb_boxscore_ingestion import (
    convert_mlb_boxscore_to_normalized_game,
    ingest_boxscores_via_mlb_api,
    populate_mlb_game_ids,
    populate_mlb_games_from_schedule,
    select_games_for_boxscores_mlb_api,
)


# ---------------------------------------------------------------------------
# populate_mlb_game_ids
# ---------------------------------------------------------------------------

class TestPopulateMlbGameIds:
    def test_no_league_returns_zero(self):
        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = None

        result = populate_mlb_game_ids(session, start_date=date(2024, 7, 1), end_date=date(2024, 7, 2))
        assert result == 0

    @patch("sports_scraper.live.mlb.MLBLiveFeedClient")
    def test_no_missing_games_returns_zero(self, mock_client_cls):
        session = MagicMock()
        league = MagicMock(id=1)
        session.query.return_value.filter.return_value.first.return_value = league
        # Second query (games_missing_pk) returns empty
        session.query.return_value.filter.return_value.all.return_value = []

        result = populate_mlb_game_ids(session, start_date=date(2024, 7, 1), end_date=date(2024, 7, 2))
        assert result == 0

    @patch("sports_scraper.live.mlb.MLBLiveFeedClient")
    def test_populates_game_ids(self, mock_client_cls):
        session = MagicMock()
        league = MagicMock(id=1)

        # First call: league lookup
        # Second call: games_missing_pk query
        # Third call: teams query
        # Need to chain properly
        league_query = MagicMock()
        league_query.first.return_value = league

        game_date = datetime(2024, 7, 15, 17, 0, tzinfo=UTC)  # noon ET
        missing_game = (100, game_date, 10, 20)
        missing_query = MagicMock()
        missing_query.all.return_value = [missing_game]

        team_home = MagicMock(id=10, abbreviation="BOS")
        team_away = MagicMock(id=20, abbreviation="NYY")
        teams_query = MagicMock()
        teams_query.all.return_value = [team_home, team_away]

        # Chain query calls
        def query_side_effect(model, *args):
            mock_q = MagicMock()
            # Return different things based on call order
            return mock_q

        # Simplify: use a single mock that returns different results
        call_count = {"n": 0}
        original_query = session.query

        def smart_query(*args):
            call_count["n"] += 1
            m = MagicMock()
            if call_count["n"] == 1:
                # League lookup
                m.filter.return_value.first.return_value = league
            elif call_count["n"] == 2:
                # Games missing PK
                m.filter.return_value.all.return_value = [missing_game]
            elif call_count["n"] == 3:
                # Teams lookup
                m.filter.return_value.all.return_value = [team_home, team_away]
            else:
                # Game lookup for update
                game_obj = MagicMock()
                game_obj.external_ids = {}
                m.get.return_value = game_obj
            return m

        session.query.side_effect = smart_query

        # Mock MLB schedule
        mlb_game = MagicMock()
        mlb_game.home_team.abbreviation = "BOS"
        mlb_game.away_team.abbreviation = "NYY"
        mlb_game.game_date = datetime(2024, 7, 15, 23, 10, tzinfo=UTC)
        mlb_game.game_pk = 717001
        mock_client_cls.return_value.fetch_schedule.return_value = [mlb_game]

        result = populate_mlb_game_ids(session, start_date=date(2024, 7, 1), end_date=date(2024, 7, 31))
        assert result == 1

    @patch("sports_scraper.live.mlb.MLBLiveFeedClient")
    def test_skips_game_missing_abbreviation(self, mock_client_cls):
        session = MagicMock()
        league = MagicMock(id=1)

        game_date = datetime(2024, 7, 15, 17, 0, tzinfo=UTC)  # noon ET
        # home_team_id=10 has no abbreviation mapping
        missing_game = (100, game_date, 999, 20)

        call_count = {"n": 0}

        def smart_query(*args):
            call_count["n"] += 1
            m = MagicMock()
            if call_count["n"] == 1:
                m.filter.return_value.first.return_value = league
            elif call_count["n"] == 2:
                m.filter.return_value.all.return_value = [missing_game]
            elif call_count["n"] == 3:
                m.filter.return_value.all.return_value = []  # no teams
            return m

        session.query.side_effect = smart_query
        mock_client_cls.return_value.fetch_schedule.return_value = []

        result = populate_mlb_game_ids(session, start_date=date(2024, 7, 1), end_date=date(2024, 7, 31))
        assert result == 0


# ---------------------------------------------------------------------------
# select_games_for_boxscores_mlb_api
# ---------------------------------------------------------------------------

class TestSelectGamesForBoxscoresMlbApi:
    def test_no_league_returns_empty(self):
        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = None

        result = select_games_for_boxscores_mlb_api(
            session, start_date=date(2024, 7, 1), end_date=date(2024, 7, 2),
            only_missing=False, updated_before=None,
        )
        assert result == []

    def test_returns_valid_games(self):
        session = MagicMock()
        league = MagicMock(id=1)
        session.query.return_value.filter.return_value.first.return_value = league

        game_date = datetime(2024, 7, 15, 17, 0, tzinfo=UTC)  # noon ET
        row = (100, "717001", game_date, "final")
        session.query.return_value.filter.return_value.all.return_value = [row]

        result = select_games_for_boxscores_mlb_api(
            session, start_date=date(2024, 7, 1), end_date=date(2024, 7, 31),
            only_missing=False, updated_before=None,
        )
        assert len(result) == 1
        assert result[0] == (100, 717001, date(2024, 7, 15), "final")

    def test_skips_none_game_pk(self):
        session = MagicMock()
        league = MagicMock(id=1)
        session.query.return_value.filter.return_value.first.return_value = league

        game_date = datetime(2024, 7, 15, tzinfo=UTC)
        row = (100, None, game_date, "final")
        session.query.return_value.filter.return_value.all.return_value = [row]

        result = select_games_for_boxscores_mlb_api(
            session, start_date=date(2024, 7, 1), end_date=date(2024, 7, 31),
            only_missing=False, updated_before=None,
        )
        assert result == []

    def test_skips_invalid_game_pk(self):
        session = MagicMock()
        league = MagicMock(id=1)
        session.query.return_value.filter.return_value.first.return_value = league

        game_date = datetime(2024, 7, 15, tzinfo=UTC)
        row = (100, "not-a-number", game_date, "final")
        session.query.return_value.filter.return_value.all.return_value = [row]

        result = select_games_for_boxscores_mlb_api(
            session, start_date=date(2024, 7, 1), end_date=date(2024, 7, 31),
            only_missing=False, updated_before=None,
        )
        assert result == []

    def test_skips_game_with_none_date(self):
        session = MagicMock()
        league = MagicMock(id=1)
        session.query.return_value.filter.return_value.first.return_value = league

        row = (100, "717001", None, "final")
        session.query.return_value.filter.return_value.all.return_value = [row]

        result = select_games_for_boxscores_mlb_api(
            session, start_date=date(2024, 7, 1), end_date=date(2024, 7, 31),
            only_missing=False, updated_before=None,
        )
        assert result == []

    def test_only_missing_applies_filter(self):
        session = MagicMock()
        league = MagicMock(id=1)
        session.query.return_value.filter.return_value.first.return_value = league

        # Chain: query → filter(league, dates) → filter(not exists) → all
        mock_q = MagicMock()
        mock_q.all.return_value = []
        session.query.return_value.filter.return_value.filter.return_value = mock_q

        result = select_games_for_boxscores_mlb_api(
            session, start_date=date(2024, 7, 1), end_date=date(2024, 7, 31),
            only_missing=True, updated_before=None,
        )
        assert result == []

    def test_updated_before_applies_filter(self):
        session = MagicMock()
        league = MagicMock(id=1)
        session.query.return_value.filter.return_value.first.return_value = league

        mock_q = MagicMock()
        mock_q.all.return_value = []
        session.query.return_value.filter.return_value.filter.return_value = mock_q

        result = select_games_for_boxscores_mlb_api(
            session, start_date=date(2024, 7, 1), end_date=date(2024, 7, 31),
            only_missing=False, updated_before=datetime(2024, 7, 10, tzinfo=UTC),
        )
        assert result == []


# ---------------------------------------------------------------------------
# ingest_boxscores_via_mlb_api
# ---------------------------------------------------------------------------

class TestIngestBoxscoresViaMlbApi:
    @patch("sports_scraper.services.mlb_boxscore_ingestion.select_games_for_boxscores_mlb_api", return_value=[])
    @patch("sports_scraper.services.mlb_boxscore_ingestion.populate_mlb_game_ids")
    def test_no_games_returns_zeros(self, mock_populate, mock_select):
        session = MagicMock()
        result = ingest_boxscores_via_mlb_api(
            session, run_id=1, start_date=date(2024, 7, 1), end_date=date(2024, 7, 2),
            only_missing=False, updated_before=None,
        )
        assert result == (0, 0, 0, 0)

    @patch("sports_scraper.live.mlb.MLBLiveFeedClient")
    @patch("sports_scraper.services.mlb_boxscore_ingestion.persist_game_payload")
    @patch("sports_scraper.services.mlb_boxscore_ingestion.convert_mlb_boxscore_to_normalized_game")
    @patch("sports_scraper.services.mlb_boxscore_ingestion.select_games_for_boxscores_mlb_api")
    @patch("sports_scraper.services.mlb_boxscore_ingestion.populate_mlb_game_ids")
    def test_processes_games(self, mock_populate, mock_select, mock_convert, mock_persist, mock_client_cls):
        mock_select.return_value = [(100, 717001, date(2024, 7, 15), "final")]

        mock_boxscore = MagicMock()
        mock_client_cls.return_value.fetch_boxscore.return_value = mock_boxscore

        mock_normalized = MagicMock()
        mock_convert.return_value = mock_normalized

        mock_result = MagicMock()
        mock_result.game_id = 100
        mock_result.enriched = True
        mock_result.has_player_stats = True
        mock_result.player_stats.inserted = 5
        mock_persist.return_value = mock_result

        session = MagicMock()
        result = ingest_boxscores_via_mlb_api(
            session, run_id=1, start_date=date(2024, 7, 1), end_date=date(2024, 7, 31),
            only_missing=False, updated_before=None,
        )

        assert result == (1, 1, 1, 0)

    @patch("sports_scraper.live.mlb.MLBLiveFeedClient")
    @patch("sports_scraper.services.mlb_boxscore_ingestion.select_games_for_boxscores_mlb_api")
    @patch("sports_scraper.services.mlb_boxscore_ingestion.populate_mlb_game_ids")
    def test_skips_empty_boxscore(self, mock_populate, mock_select, mock_client_cls):
        mock_select.return_value = [(100, 717001, date(2024, 7, 15), "final")]
        mock_client_cls.return_value.fetch_boxscore.return_value = None

        session = MagicMock()
        result = ingest_boxscores_via_mlb_api(
            session, run_id=1, start_date=date(2024, 7, 1), end_date=date(2024, 7, 31),
            only_missing=False, updated_before=None,
        )
        assert result == (0, 0, 0, 0)

    @patch("sports_scraper.live.mlb.MLBLiveFeedClient")
    @patch("sports_scraper.services.mlb_boxscore_ingestion.select_games_for_boxscores_mlb_api")
    @patch("sports_scraper.services.mlb_boxscore_ingestion.populate_mlb_game_ids")
    def test_handles_fetch_exception(self, mock_populate, mock_select, mock_client_cls):
        mock_select.return_value = [(100, 717001, date(2024, 7, 15), "final")]
        mock_client_cls.return_value.fetch_boxscore.side_effect = Exception("timeout")

        session = MagicMock()
        result = ingest_boxscores_via_mlb_api(
            session, run_id=1, start_date=date(2024, 7, 1), end_date=date(2024, 7, 31),
            only_missing=False, updated_before=None,
        )
        assert result == (0, 0, 0, 1)

    @patch("sports_scraper.live.mlb.MLBLiveFeedClient")
    @patch("sports_scraper.services.mlb_boxscore_ingestion.persist_game_payload")
    @patch("sports_scraper.services.mlb_boxscore_ingestion.convert_mlb_boxscore_to_normalized_game")
    @patch("sports_scraper.services.mlb_boxscore_ingestion.select_games_for_boxscores_mlb_api")
    @patch("sports_scraper.services.mlb_boxscore_ingestion.populate_mlb_game_ids")
    def test_game_id_none_not_counted(self, mock_populate, mock_select, mock_convert, mock_persist, mock_client_cls):
        mock_select.return_value = [(100, 717001, date(2024, 7, 15), "final")]
        mock_client_cls.return_value.fetch_boxscore.return_value = MagicMock()
        mock_convert.return_value = MagicMock()

        mock_result = MagicMock()
        mock_result.game_id = None
        mock_persist.return_value = mock_result

        session = MagicMock()
        result = ingest_boxscores_via_mlb_api(
            session, run_id=1, start_date=date(2024, 7, 1), end_date=date(2024, 7, 31),
            only_missing=False, updated_before=None,
        )
        assert result == (0, 0, 0, 0)


# ---------------------------------------------------------------------------
# convert_mlb_boxscore_to_normalized_game
# ---------------------------------------------------------------------------

class TestConvertMlbBoxscore:
    def test_final_status_mapped(self):
        home_team = TeamIdentity(league_code="MLB", name="Boston Red Sox", abbreviation="BOS")
        away_team = TeamIdentity(league_code="MLB", name="New York Yankees", abbreviation="NYY")
        tb = NormalizedTeamBoxscore(team=home_team, is_home=True)

        boxscore = MagicMock()
        boxscore.home_team = home_team
        boxscore.away_team = away_team
        boxscore.game_pk = 717001
        boxscore.status = "final"
        boxscore.home_score = 5
        boxscore.away_score = 3
        boxscore.team_boxscores = [tb]
        boxscore.player_boxscores = []

        result = convert_mlb_boxscore_to_normalized_game(boxscore, date(2024, 7, 15))

        assert result.status == "completed"
        assert result.home_score == 5
        assert result.away_score == 3
        assert result.identity.league_code == "MLB"
        assert result.identity.source_game_key == "717001"

    def test_non_final_status_preserved(self):
        home_team = TeamIdentity(league_code="MLB", name="Boston Red Sox", abbreviation="BOS")
        away_team = TeamIdentity(league_code="MLB", name="New York Yankees", abbreviation="NYY")
        tb = NormalizedTeamBoxscore(team=home_team, is_home=True)

        boxscore = MagicMock()
        boxscore.home_team = home_team
        boxscore.away_team = away_team
        boxscore.game_pk = 717002
        boxscore.status = "live"
        boxscore.home_score = 2
        boxscore.away_score = 1
        boxscore.team_boxscores = [tb]
        boxscore.player_boxscores = []

        result = convert_mlb_boxscore_to_normalized_game(boxscore, date(2024, 7, 15))

        assert result.status == "live"


# ---------------------------------------------------------------------------
# populate_mlb_games_from_schedule
# ---------------------------------------------------------------------------

class TestPopulateMlbGamesFromSchedule:
    @patch("sports_scraper.live.mlb.MLBLiveFeedClient")
    def test_no_games_returns_zero(self, mock_client_cls):
        mock_client_cls.return_value.fetch_schedule.return_value = []
        session = MagicMock()

        result = populate_mlb_games_from_schedule(
            session, run_id=1, start_date=date(2024, 7, 1), end_date=date(2024, 7, 2),
        )
        assert result == 0

    @patch("sports_scraper.persistence.games.upsert_game_stub")
    @patch("sports_scraper.live.mlb.MLBLiveFeedClient")
    def test_creates_stubs_for_schedule_games(self, mock_client_cls, mock_upsert):
        home = TeamIdentity(league_code="MLB", name="Boston Red Sox", abbreviation="BOS")
        away = TeamIdentity(league_code="MLB", name="New York Yankees", abbreviation="NYY")

        game1 = MagicMock()
        game1.game_pk = 717001
        game1.game_date = datetime(2024, 7, 15, 23, 10, tzinfo=UTC)
        game1.home_team = home
        game1.away_team = away
        game1.status = "Final"
        game1.home_score = 5
        game1.away_score = 3
        game1.venue = "Fenway Park"

        game2 = MagicMock()
        game2.game_pk = 717002
        game2.game_date = datetime(2024, 7, 16, 0, 5, tzinfo=UTC)  # late game, still July 15 ET
        game2.home_team = away
        game2.away_team = home
        game2.status = "Final"
        game2.home_score = 2
        game2.away_score = 1
        game2.venue = "Yankee Stadium"

        mock_client_cls.return_value.fetch_schedule.return_value = [game1, game2]
        mock_upsert.return_value = (100, True)  # game_id, was_created

        session = MagicMock()
        result = populate_mlb_games_from_schedule(
            session, run_id=1, start_date=date(2024, 7, 15), end_date=date(2024, 7, 16),
        )

        assert result == 2
        assert mock_upsert.call_count == 2

        # Verify external_ids contain mlb_game_pk
        first_call = mock_upsert.call_args_list[0]
        assert first_call.kwargs["external_ids"] == {"mlb_game_pk": "717001"}
        assert first_call.kwargs["league_code"] == "MLB"

    @patch("sports_scraper.persistence.games.upsert_game_stub")
    @patch("sports_scraper.live.mlb.MLBLiveFeedClient")
    def test_counts_only_new_games(self, mock_client_cls, mock_upsert):
        game1 = MagicMock()
        game1.game_pk = 717001
        game1.game_date = datetime(2024, 7, 15, 23, 10, tzinfo=UTC)
        game1.status = "Final"
        game1.home_score = 5
        game1.away_score = 3
        game1.venue = None

        mock_client_cls.return_value.fetch_schedule.return_value = [game1]
        mock_upsert.return_value = (100, False)  # already existed

        session = MagicMock()
        result = populate_mlb_games_from_schedule(
            session, run_id=1, start_date=date(2024, 7, 15), end_date=date(2024, 7, 15),
        )

        assert result == 0  # no new games created

    @patch("sports_scraper.persistence.games.upsert_game_stub")
    @patch("sports_scraper.live.mlb.MLBLiveFeedClient")
    def test_handles_upsert_exception(self, mock_client_cls, mock_upsert):
        game1 = MagicMock()
        game1.game_pk = 717001
        game1.game_date = datetime(2024, 7, 15, 23, 10, tzinfo=UTC)
        game1.status = "Final"
        game1.home_score = 5
        game1.away_score = 3
        game1.venue = None

        mock_client_cls.return_value.fetch_schedule.return_value = [game1]
        mock_upsert.side_effect = Exception("db error")

        session = MagicMock()
        result = populate_mlb_games_from_schedule(
            session, run_id=1, start_date=date(2024, 7, 15), end_date=date(2024, 7, 15),
        )

        assert result == 0  # gracefully handled
