"""Tests for services/nfl_boxscore_ingestion.py — targeting >= 80% coverage."""

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

from sports_scraper.models import TeamIdentity

_MOD = "sports_scraper.services.nfl_boxscore_ingestion"


def _team(abbr: str, name: str = "Team") -> TeamIdentity:
    return TeamIdentity(league_code="NFL", name=name, abbreviation=abbr)


# ---------------------------------------------------------------------------
# populate_nfl_games_from_schedule
# ---------------------------------------------------------------------------

class TestPopulateNflGamesFromSchedule:
    @patch("sports_scraper.persistence.games.upsert_game_stub")
    @patch("sports_scraper.live.nfl.NFLLiveFeedClient")
    def test_creates_game_stubs(self, mock_client_cls, mock_upsert):
        from sports_scraper.services.nfl_boxscore_ingestion import populate_nfl_games_from_schedule

        game = MagicMock()
        game.season_type = "regular"
        game.game_date = datetime(2024, 11, 10, tzinfo=UTC)
        game.home_team = "KC"
        game.away_team = "DEN"
        game.status = "final"
        game.home_score = 27
        game.away_score = 19
        game.game_id = "401671234"

        mock_client_cls.return_value.fetch_schedule.return_value = [game]
        mock_upsert.return_value = (1, True)

        session = MagicMock()
        result = populate_nfl_games_from_schedule(
            session, start_date=date(2024, 11, 10), end_date=date(2024, 11, 11),
        )

        assert result == 1
        mock_upsert.assert_called_once()
        session.commit.assert_called_once()

    @patch("sports_scraper.persistence.games.upsert_game_stub")
    @patch("sports_scraper.live.nfl.NFLLiveFeedClient")
    def test_skips_preseason_games(self, mock_client_cls, mock_upsert):
        from sports_scraper.services.nfl_boxscore_ingestion import populate_nfl_games_from_schedule

        game = MagicMock()
        game.season_type = "preseason"
        mock_client_cls.return_value.fetch_schedule.return_value = [game]

        session = MagicMock()
        result = populate_nfl_games_from_schedule(
            session, start_date=date(2024, 8, 10), end_date=date(2024, 8, 11),
        )

        assert result == 0
        mock_upsert.assert_not_called()

    @patch("sports_scraper.persistence.games.upsert_game_stub", side_effect=Exception("DB error"))
    @patch("sports_scraper.live.nfl.NFLLiveFeedClient")
    def test_continues_on_upsert_error(self, mock_client_cls, mock_upsert):
        from sports_scraper.services.nfl_boxscore_ingestion import populate_nfl_games_from_schedule

        game = MagicMock()
        game.season_type = "regular"
        game.game_id = "401671234"
        mock_client_cls.return_value.fetch_schedule.return_value = [game]

        session = MagicMock()
        result = populate_nfl_games_from_schedule(
            session, start_date=date(2024, 11, 10), end_date=date(2024, 11, 11),
        )

        assert result == 0

    @patch("sports_scraper.persistence.games.upsert_game_stub")
    @patch("sports_scraper.live.nfl.NFLLiveFeedClient")
    def test_not_created_not_counted(self, mock_client_cls, mock_upsert):
        from sports_scraper.services.nfl_boxscore_ingestion import populate_nfl_games_from_schedule

        game = MagicMock()
        game.season_type = "regular"
        game.game_id = "401671234"
        mock_client_cls.return_value.fetch_schedule.return_value = [game]
        mock_upsert.return_value = (1, False)  # existing, not created

        session = MagicMock()
        result = populate_nfl_games_from_schedule(
            session, start_date=date(2024, 11, 10), end_date=date(2024, 11, 11),
        )

        assert result == 0
        session.commit.assert_not_called()


# ---------------------------------------------------------------------------
# populate_nfl_game_ids
# ---------------------------------------------------------------------------

class TestPopulateNflGameIds:
    @patch("sports_scraper.live.nfl.NFLLiveFeedClient")
    def test_no_league_returns_zero(self, mock_client_cls):
        from sports_scraper.services.nfl_boxscore_ingestion import populate_nfl_game_ids

        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = None

        result = populate_nfl_game_ids(
            session, start_date=date(2024, 11, 10), end_date=date(2024, 11, 11),
        )
        assert result == 0

    @patch("sports_scraper.live.nfl.NFLLiveFeedClient")
    def test_no_games_needing_ids(self, mock_client_cls):
        from sports_scraper.services.nfl_boxscore_ingestion import populate_nfl_game_ids

        league = MagicMock(id=1)
        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = league
        session.query.return_value.filter.return_value.all.return_value = []

        result = populate_nfl_game_ids(
            session, start_date=date(2024, 11, 10), end_date=date(2024, 11, 11),
        )
        assert result == 0

    @patch("sports_scraper.live.nfl.NFLLiveFeedClient")
    def test_matches_by_team_abbreviation(self, mock_client_cls):
        from sports_scraper.services.nfl_boxscore_ingestion import populate_nfl_game_ids

        league = MagicMock(id=1)

        # Game in DB missing espn_game_id
        game_date = datetime(2024, 11, 10, 20, 0, tzinfo=UTC)
        db_game = MagicMock()
        db_game.external_ids = {}

        session = MagicMock()
        # League query
        session.query.return_value.filter.return_value.first.return_value = league
        # games_missing query
        session.query.return_value.filter.return_value.all.side_effect = [
            [(100, game_date, 10, 20)],  # games_missing
            [MagicMock(id=10, abbreviation="KC", league_id=1),
             MagicMock(id=20, abbreviation="DEN", league_id=1)],  # team query
        ]
        session.get.return_value = db_game

        # ESPN schedule game — must include game_date for date+team matching
        schedule_game = MagicMock()
        schedule_game.home_team.abbreviation.upper.return_value = "KC"
        schedule_game.away_team.abbreviation.upper.return_value = "DEN"
        schedule_game.game_id = "401671234"
        schedule_game.game_date = datetime(2024, 11, 10, 18, 0, tzinfo=UTC)
        mock_client_cls.return_value.fetch_schedule.return_value = [schedule_game]

        result = populate_nfl_game_ids(
            session, start_date=date(2024, 11, 10), end_date=date(2024, 11, 11),
        )

        assert result == 1
        session.flush.assert_called_once()


# ---------------------------------------------------------------------------
# select_games_for_boxscores_nfl_api
# ---------------------------------------------------------------------------

class TestSelectGamesForBoxscoresNflApi:
    def test_no_league_returns_empty(self):
        from sports_scraper.services.nfl_boxscore_ingestion import select_games_for_boxscores_nfl_api

        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = None

        result = select_games_for_boxscores_nfl_api(
            session, start_date=date(2024, 11, 10), end_date=date(2024, 11, 11),
            only_missing=False, updated_before=None,
        )
        assert result == []

    def test_returns_valid_games(self):
        from sports_scraper.services.nfl_boxscore_ingestion import select_games_for_boxscores_nfl_api

        session = MagicMock()
        league = MagicMock(id=1)
        session.query.return_value.filter.return_value.first.return_value = league

        game_date = datetime(2024, 11, 10, 20, 0, tzinfo=UTC)
        row = (100, "401671234", game_date, "final")
        session.query.return_value.filter.return_value.all.return_value = [row]

        result = select_games_for_boxscores_nfl_api(
            session, start_date=date(2024, 11, 10), end_date=date(2024, 11, 11),
            only_missing=False, updated_before=None,
        )

        assert len(result) == 1
        assert result[0] == (100, 401671234, game_date, "final")

    def test_skips_none_espn_game_id(self):
        from sports_scraper.services.nfl_boxscore_ingestion import select_games_for_boxscores_nfl_api

        session = MagicMock()
        league = MagicMock(id=1)
        session.query.return_value.filter.return_value.first.return_value = league

        row = (100, None, datetime(2024, 11, 10, tzinfo=UTC), "final")
        session.query.return_value.filter.return_value.all.return_value = [row]

        result = select_games_for_boxscores_nfl_api(
            session, start_date=date(2024, 11, 10), end_date=date(2024, 11, 11),
            only_missing=False, updated_before=None,
        )
        assert result == []

    def test_skips_invalid_espn_game_id(self):
        from sports_scraper.services.nfl_boxscore_ingestion import select_games_for_boxscores_nfl_api

        session = MagicMock()
        league = MagicMock(id=1)
        session.query.return_value.filter.return_value.first.return_value = league

        row = (100, "not-a-number", datetime(2024, 11, 10, tzinfo=UTC), "final")
        session.query.return_value.filter.return_value.all.return_value = [row]

        result = select_games_for_boxscores_nfl_api(
            session, start_date=date(2024, 11, 10), end_date=date(2024, 11, 11),
            only_missing=False, updated_before=None,
        )
        assert result == []

    def test_only_missing_applies_filter(self):
        from sports_scraper.services.nfl_boxscore_ingestion import select_games_for_boxscores_nfl_api

        session = MagicMock()
        league = MagicMock(id=1)
        session.query.return_value.filter.return_value.first.return_value = league
        session.query.return_value.filter.return_value.filter.return_value.all.return_value = []

        result = select_games_for_boxscores_nfl_api(
            session, start_date=date(2024, 11, 10), end_date=date(2024, 11, 11),
            only_missing=True, updated_before=None,
        )
        assert result == []

    def test_status_defaults_to_final(self):
        from sports_scraper.services.nfl_boxscore_ingestion import select_games_for_boxscores_nfl_api

        session = MagicMock()
        league = MagicMock(id=1)
        session.query.return_value.filter.return_value.first.return_value = league

        game_date = datetime(2024, 11, 10, 20, 0, tzinfo=UTC)
        row = (100, "401671234", game_date, None)  # status is None
        session.query.return_value.filter.return_value.all.return_value = [row]

        result = select_games_for_boxscores_nfl_api(
            session, start_date=date(2024, 11, 10), end_date=date(2024, 11, 11),
            only_missing=False, updated_before=None,
        )

        assert result[0][3] == "final"


# ---------------------------------------------------------------------------
# ingest_boxscores_via_nfl_api
# ---------------------------------------------------------------------------

class TestIngestBoxscoresViaNflApi:
    @patch(f"{_MOD}.select_games_for_boxscores_nfl_api", return_value=[])
    @patch(f"{_MOD}.populate_nfl_game_ids")
    @patch(f"{_MOD}.populate_nfl_games_from_schedule")
    def test_no_games_returns_zeros(self, mock_pop_sched, mock_pop_ids, mock_select):
        from sports_scraper.services.nfl_boxscore_ingestion import ingest_boxscores_via_nfl_api

        session = MagicMock()
        result = ingest_boxscores_via_nfl_api(
            session, run_id=1, start_date=date(2024, 11, 10), end_date=date(2024, 11, 11),
            only_missing=False, updated_before=None,
        )
        assert result == (0, 0, 0, 0)

    @patch(f"{_MOD}.persist_game_payload")
    @patch("sports_scraper.live.nfl.NFLLiveFeedClient")
    @patch(f"{_MOD}.select_games_for_boxscores_nfl_api")
    @patch(f"{_MOD}.populate_nfl_game_ids")
    @patch(f"{_MOD}.populate_nfl_games_from_schedule")
    def test_processes_game_successfully(
        self, mock_pop_sched, mock_pop_ids, mock_select, mock_client_cls, mock_persist,
    ):
        from sports_scraper.services.nfl_boxscore_ingestion import ingest_boxscores_via_nfl_api

        game_date = datetime(2024, 11, 10, 20, 0, tzinfo=UTC)
        mock_select.return_value = [(100, 401671234, game_date, "final")]

        # Build a boxscore with team and player data using real TeamIdentity
        kc = _team("KC", "Kansas City Chiefs")
        den = _team("DEN", "Denver Broncos")

        boxscore = MagicMock()
        boxscore.home_team = kc
        boxscore.away_team = den
        boxscore.home_score = 27
        boxscore.away_score = 19
        boxscore.status = "final"

        tb = MagicMock(team=kc, is_home=True, points=27, raw_stats={})
        boxscore.team_boxscores = [tb]

        pb = MagicMock(
            player_id="mahompa01", player_name="Patrick Mahomes",
            team=kc, player_role="starter", position="QB",
            raw_stats={"passing_yards": 300},
        )
        boxscore.player_boxscores = [pb]
        mock_client_cls.return_value.fetch_boxscore.return_value = boxscore

        persist_result = MagicMock()
        persist_result.game_id = 100
        persist_result.enriched = True
        persist_result.has_player_stats = True
        mock_persist.return_value = persist_result

        session = MagicMock()
        result = ingest_boxscores_via_nfl_api(
            session, run_id=1, start_date=date(2024, 11, 10), end_date=date(2024, 11, 11),
            only_missing=False, updated_before=None,
        )

        assert result == (1, 1, 1, 0)
        mock_persist.assert_called_once()
        session.commit.assert_called()

    @patch("sports_scraper.live.nfl.NFLLiveFeedClient")
    @patch(f"{_MOD}.select_games_for_boxscores_nfl_api")
    @patch(f"{_MOD}.populate_nfl_game_ids")
    @patch(f"{_MOD}.populate_nfl_games_from_schedule")
    def test_skips_empty_boxscore(self, mock_pop_sched, mock_pop_ids, mock_select, mock_client_cls):
        from sports_scraper.services.nfl_boxscore_ingestion import ingest_boxscores_via_nfl_api

        game_date = datetime(2024, 11, 10, 20, 0, tzinfo=UTC)
        mock_select.return_value = [(100, 401671234, game_date, "final")]
        mock_client_cls.return_value.fetch_boxscore.return_value = None

        session = MagicMock()
        result = ingest_boxscores_via_nfl_api(
            session, run_id=1, start_date=date(2024, 11, 10), end_date=date(2024, 11, 11),
            only_missing=False, updated_before=None,
        )
        assert result == (0, 0, 0, 0)

    @patch("sports_scraper.live.nfl.NFLLiveFeedClient")
    @patch(f"{_MOD}.select_games_for_boxscores_nfl_api")
    @patch(f"{_MOD}.populate_nfl_game_ids")
    @patch(f"{_MOD}.populate_nfl_games_from_schedule")
    def test_handles_fetch_exception(self, mock_pop_sched, mock_pop_ids, mock_select, mock_client_cls):
        from sports_scraper.services.nfl_boxscore_ingestion import ingest_boxscores_via_nfl_api

        game_date = datetime(2024, 11, 10, 20, 0, tzinfo=UTC)
        mock_select.return_value = [(100, 401671234, game_date, "final")]
        mock_client_cls.return_value.fetch_boxscore.side_effect = Exception("timeout")

        session = MagicMock()
        result = ingest_boxscores_via_nfl_api(
            session, run_id=1, start_date=date(2024, 11, 10), end_date=date(2024, 11, 11),
            only_missing=False, updated_before=None,
        )

        assert result == (0, 0, 0, 1)
        session.rollback.assert_called()

    @patch(f"{_MOD}.persist_game_payload")
    @patch("sports_scraper.live.nfl.NFLLiveFeedClient")
    @patch(f"{_MOD}.select_games_for_boxscores_nfl_api")
    @patch(f"{_MOD}.populate_nfl_game_ids")
    @patch(f"{_MOD}.populate_nfl_games_from_schedule")
    def test_not_enriched_not_counted(
        self, mock_pop_sched, mock_pop_ids, mock_select, mock_client_cls, mock_persist,
    ):
        from sports_scraper.services.nfl_boxscore_ingestion import ingest_boxscores_via_nfl_api

        game_date = datetime(2024, 11, 10, 20, 0, tzinfo=UTC)
        mock_select.return_value = [(100, 401671234, game_date, "final")]

        kc = _team("KC", "Kansas City Chiefs")
        den = _team("DEN", "Denver Broncos")

        boxscore = MagicMock()
        boxscore.home_team = kc
        boxscore.away_team = den
        boxscore.home_score = 27
        boxscore.away_score = 19
        boxscore.status = "final"
        tb = MagicMock(team=kc, is_home=True, points=27, raw_stats={})
        boxscore.team_boxscores = [tb]
        boxscore.player_boxscores = []
        mock_client_cls.return_value.fetch_boxscore.return_value = boxscore

        persist_result = MagicMock()
        persist_result.game_id = 100
        persist_result.enriched = False
        persist_result.has_player_stats = False
        mock_persist.return_value = persist_result

        session = MagicMock()
        result = ingest_boxscores_via_nfl_api(
            session, run_id=1, start_date=date(2024, 11, 10), end_date=date(2024, 11, 11),
            only_missing=False, updated_before=None,
        )

        assert result == (1, 0, 0, 0)

    @patch(f"{_MOD}.persist_game_payload")
    @patch("sports_scraper.live.nfl.NFLLiveFeedClient")
    @patch(f"{_MOD}.select_games_for_boxscores_nfl_api")
    @patch(f"{_MOD}.populate_nfl_game_ids")
    @patch(f"{_MOD}.populate_nfl_games_from_schedule")
    def test_persist_returns_none_game_id(
        self, mock_pop_sched, mock_pop_ids, mock_select, mock_client_cls, mock_persist,
    ):
        from sports_scraper.services.nfl_boxscore_ingestion import ingest_boxscores_via_nfl_api

        game_date = datetime(2024, 11, 10, 20, 0, tzinfo=UTC)
        mock_select.return_value = [(100, 401671234, game_date, "final")]

        kc = _team("KC", "Kansas City Chiefs")
        den = _team("DEN", "Denver Broncos")

        boxscore = MagicMock()
        boxscore.home_team = kc
        boxscore.away_team = den
        boxscore.home_score = 27
        boxscore.away_score = 19
        boxscore.status = "final"
        tb = MagicMock(team=kc, is_home=True, points=27, raw_stats={})
        boxscore.team_boxscores = [tb]
        boxscore.player_boxscores = []
        mock_client_cls.return_value.fetch_boxscore.return_value = boxscore

        persist_result = MagicMock()
        persist_result.game_id = None
        mock_persist.return_value = persist_result

        session = MagicMock()
        result = ingest_boxscores_via_nfl_api(
            session, run_id=1, start_date=date(2024, 11, 10), end_date=date(2024, 11, 11),
            only_missing=False, updated_before=None,
        )

        assert result == (0, 0, 0, 0)
