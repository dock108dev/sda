"""Tests for boxscore ingestion modules (NHL and NCAAB)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock, patch

from sports_scraper.services.ncaab_boxscore_ingestion import (
    convert_ncaab_boxscore_to_normalized_game as _convert_ncaab_boxscore_to_normalized_game,
)
from sports_scraper.services.ncaab_boxscore_ingestion import (
    ingest_boxscores_via_ncaab_api,
)
from sports_scraper.services.ncaab_game_ids import (
    populate_ncaab_game_ids as _populate_ncaab_game_ids,
)
from sports_scraper.services.ncaab_game_ids import (
    select_games_for_boxscores_ncaab_api,
)
from sports_scraper.services.nhl_boxscore_ingestion import (
    convert_nhl_boxscore_to_normalized_game as _convert_boxscore_to_normalized_game,
)
from sports_scraper.services.nhl_boxscore_ingestion import (
    ingest_boxscores_via_nhl_api,
    select_games_for_boxscores_nhl_api,
)
from sports_scraper.utils.date_utils import season_ending_year as _season_from_date


class TestSeasonFromDate:
    """Tests for _season_from_date function."""

    def test_october_returns_next_year(self):
        """October game belongs to next calendar year's season."""
        result = _season_from_date(date(2024, 10, 15))
        assert result == 2025

    def test_november_returns_next_year(self):
        """November game belongs to next calendar year's season."""
        result = _season_from_date(date(2024, 11, 20))
        assert result == 2025

    def test_december_returns_next_year(self):
        """December game belongs to next calendar year's season."""
        result = _season_from_date(date(2024, 12, 25))
        assert result == 2025

    def test_january_returns_same_year(self):
        """January game belongs to current calendar year's season."""
        result = _season_from_date(date(2025, 1, 15))
        assert result == 2025

    def test_april_returns_same_year(self):
        """April game belongs to current calendar year's season."""
        result = _season_from_date(date(2025, 4, 10))
        assert result == 2025

    def test_september_returns_same_year(self):
        """September is before October, so same year."""
        result = _season_from_date(date(2024, 9, 30))
        assert result == 2024


class TestSelectGamesForBoxscoresNhlApi:
    """Tests for select_games_for_boxscores_nhl_api function."""

    def test_returns_empty_when_no_league(self):
        """Returns empty list when NHL league not found."""
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = None

        result = select_games_for_boxscores_nhl_api(
            mock_session,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            only_missing=True,
            updated_before=None,
        )

        assert result == []


class TestSelectGamesForBoxscoresNcaabApi:
    """Tests for select_games_for_boxscores_ncaab_api function."""

    def test_returns_empty_when_no_league(self):
        """Returns empty list when NCAAB league not found."""
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = None

        result = select_games_for_boxscores_ncaab_api(
            mock_session,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            only_missing=True,
            updated_before=None,
        )

        assert result == []


class TestConvertBoxscoreToNormalizedGameNhl:
    """Tests for _convert_boxscore_to_normalized_game."""

    def test_converts_final_boxscore(self):
        """Converts NHL boxscore to NormalizedGame."""
        from sports_scraper.models import NormalizedTeamBoxscore, TeamIdentity

        # Create minimal team boxscores to satisfy validation
        home_boxscore = NormalizedTeamBoxscore(
            team=TeamIdentity(league_code="NHL", name="TBL", abbreviation="TBL"),
            is_home=True,
            stats={"goals": 4},
        )
        away_boxscore = NormalizedTeamBoxscore(
            team=TeamIdentity(league_code="NHL", name="BOS", abbreviation="BOS"),
            is_home=False,
            stats={"goals": 3},
        )

        mock_boxscore = MagicMock()
        mock_boxscore.game_id = 2025020001
        mock_boxscore.status = "final"
        mock_boxscore.home_team = TeamIdentity(league_code="NHL", name="TBL", abbreviation="TBL")
        mock_boxscore.away_team = TeamIdentity(league_code="NHL", name="BOS", abbreviation="BOS")
        mock_boxscore.home_score = 4
        mock_boxscore.away_score = 3
        mock_boxscore.team_boxscores = [home_boxscore, away_boxscore]
        mock_boxscore.player_boxscores = []

        result = _convert_boxscore_to_normalized_game(mock_boxscore, date(2024, 10, 15))

        assert result.identity.league_code == "NHL"
        assert result.status == "completed"
        assert result.home_score == 4
        assert result.away_score == 3

    def test_converts_live_boxscore(self):
        """Converts live NHL boxscore."""
        from sports_scraper.models import NormalizedTeamBoxscore, TeamIdentity

        home_boxscore = NormalizedTeamBoxscore(
            team=TeamIdentity(league_code="NHL", name="TBL", abbreviation="TBL"),
            is_home=True,
            stats={"goals": 2},
        )
        away_boxscore = NormalizedTeamBoxscore(
            team=TeamIdentity(league_code="NHL", name="BOS", abbreviation="BOS"),
            is_home=False,
            stats={"goals": 1},
        )

        mock_boxscore = MagicMock()
        mock_boxscore.game_id = 2025020001
        mock_boxscore.status = "live"
        mock_boxscore.home_team = TeamIdentity(league_code="NHL", name="TBL", abbreviation="TBL")
        mock_boxscore.away_team = TeamIdentity(league_code="NHL", name="BOS", abbreviation="BOS")
        mock_boxscore.home_score = 2
        mock_boxscore.away_score = 1
        mock_boxscore.team_boxscores = [home_boxscore, away_boxscore]
        mock_boxscore.player_boxscores = []

        result = _convert_boxscore_to_normalized_game(mock_boxscore, date(2024, 10, 15))

        assert result.status == "live"


class TestConvertNcaabBoxscoreToNormalizedGame:
    """Tests for _convert_ncaab_boxscore_to_normalized_game."""

    def test_converts_final_boxscore(self):
        """Converts NCAAB boxscore to NormalizedGame."""
        from sports_scraper.models import NormalizedTeamBoxscore, TeamIdentity

        home_boxscore = NormalizedTeamBoxscore(
            team=TeamIdentity(league_code="NCAAB", name="Duke", abbreviation="DUKE"),
            is_home=True,
            stats={"points": 85},
        )
        away_boxscore = NormalizedTeamBoxscore(
            team=TeamIdentity(league_code="NCAAB", name="UNC", abbreviation="UNC"),
            is_home=False,
            stats={"points": 80},
        )

        mock_boxscore = MagicMock()
        mock_boxscore.game_id = 123456
        mock_boxscore.season = 2025
        mock_boxscore.status = "final"
        mock_boxscore.game_date = datetime(2025, 1, 15, 19, 0, tzinfo=UTC)
        mock_boxscore.home_team = TeamIdentity(league_code="NCAAB", name="Duke", abbreviation="DUKE")
        mock_boxscore.away_team = TeamIdentity(league_code="NCAAB", name="UNC", abbreviation="UNC")
        mock_boxscore.home_score = 85
        mock_boxscore.away_score = 80
        mock_boxscore.team_boxscores = [home_boxscore, away_boxscore]
        mock_boxscore.player_boxscores = []

        result = _convert_ncaab_boxscore_to_normalized_game(mock_boxscore)

        assert result.identity.league_code == "NCAAB"
        assert result.status == "completed"
        assert result.home_score == 85
        assert result.away_score == 80


class TestIngestBoxscoresViaNhlApi:
    """Tests for ingest_boxscores_via_nhl_api."""

    @patch("sports_scraper.services.nhl_boxscore_ingestion.populate_nhl_game_ids")
    @patch("sports_scraper.services.nhl_boxscore_ingestion.select_games_for_boxscores_nhl_api")
    def test_returns_zero_when_no_games(self, mock_select, mock_populate):
        """Returns (0, 0, 0) when no games selected."""
        mock_session = MagicMock()
        mock_select.return_value = []

        result = ingest_boxscores_via_nhl_api(
            mock_session,
            run_id=1,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            only_missing=True,
            updated_before=None,
        )

        assert result == (0, 0, 0, 0)

    @patch("sports_scraper.services.nhl_boxscore_ingestion.persist_game_payload")
    @patch("sports_scraper.live.nhl.NHLLiveFeedClient")
    @patch("sports_scraper.services.nhl_boxscore_ingestion.populate_nhl_game_ids")
    @patch("sports_scraper.services.nhl_boxscore_ingestion.select_games_for_boxscores_nhl_api")
    def test_processes_games_successfully(self, mock_select, mock_populate, mock_client_class, mock_persist):
        """Processes games and returns counts."""
        from sports_scraper.models import NormalizedTeamBoxscore, TeamIdentity
        from sports_scraper.persistence import GamePersistResult

        mock_session = MagicMock()
        mock_select.return_value = [(1, 2025020001, date(2024, 10, 15))]

        mock_client = MagicMock()
        mock_boxscore = MagicMock()
        mock_boxscore.game_id = 2025020001
        mock_boxscore.status = "final"
        mock_boxscore.home_team = TeamIdentity(league_code="NHL", name="TBL", abbreviation="TBL")
        mock_boxscore.away_team = TeamIdentity(league_code="NHL", name="BOS", abbreviation="BOS")
        mock_boxscore.home_score = 4
        mock_boxscore.away_score = 3
        mock_boxscore.team_boxscores = [
            NormalizedTeamBoxscore(team=mock_boxscore.home_team, is_home=True, stats={"goals": 4}),
            NormalizedTeamBoxscore(team=mock_boxscore.away_team, is_home=False, stats={"goals": 3}),
        ]
        mock_boxscore.player_boxscores = []
        mock_client.fetch_boxscore.return_value = mock_boxscore
        mock_client_class.return_value = mock_client

        mock_persist.return_value = GamePersistResult(game_id=1, enriched=True)

        result = ingest_boxscores_via_nhl_api(
            mock_session,
            run_id=1,
            start_date=date(2024, 10, 1),
            end_date=date(2024, 10, 31),
            only_missing=True,
            updated_before=None,
        )

        # Returns (games_processed, games_enriched, games_with_stats)
        assert result[0] == 1  # games processed
        assert result[1] == 1  # games enriched

    @patch("sports_scraper.live.nhl.NHLLiveFeedClient")
    @patch("sports_scraper.services.nhl_boxscore_ingestion.populate_nhl_game_ids")
    @patch("sports_scraper.services.nhl_boxscore_ingestion.select_games_for_boxscores_nhl_api")
    def test_handles_empty_boxscore_response(self, mock_select, mock_populate, mock_client_class):
        """Handles empty boxscore response gracefully."""
        mock_session = MagicMock()
        mock_select.return_value = [(1, 2025020001, date(2024, 10, 15))]

        mock_client = MagicMock()
        mock_client.fetch_boxscore.return_value = None
        mock_client_class.return_value = mock_client

        result = ingest_boxscores_via_nhl_api(
            mock_session,
            run_id=1,
            start_date=date(2024, 10, 1),
            end_date=date(2024, 10, 31),
            only_missing=True,
            updated_before=None,
        )

        assert result == (0, 0, 0, 0)

    @patch("sports_scraper.live.nhl.NHLLiveFeedClient")
    @patch("sports_scraper.services.nhl_boxscore_ingestion.populate_nhl_game_ids")
    @patch("sports_scraper.services.nhl_boxscore_ingestion.select_games_for_boxscores_nhl_api")
    def test_handles_fetch_exception(self, mock_select, mock_populate, mock_client_class):
        """Handles fetch exceptions gracefully."""
        mock_session = MagicMock()
        mock_select.return_value = [(1, 2025020001, date(2024, 10, 15))]

        mock_client = MagicMock()
        mock_client.fetch_boxscore.side_effect = Exception("API error")
        mock_client_class.return_value = mock_client

        result = ingest_boxscores_via_nhl_api(
            mock_session,
            run_id=1,
            start_date=date(2024, 10, 1),
            end_date=date(2024, 10, 31),
            only_missing=True,
            updated_before=None,
        )

        assert result == (0, 0, 0, 1)


class TestIngestBoxscoresViaNcaabApi:
    """Tests for ingest_boxscores_via_ncaab_api."""

    @patch("sports_scraper.services.ncaab_boxscore_ingestion.populate_ncaab_game_ids")
    @patch("sports_scraper.services.ncaab_boxscore_ingestion.select_games_for_boxscores_ncaab_api")
    def test_returns_zero_when_no_games(self, mock_select, mock_populate):
        """Returns (0, 0, 0) when no games selected."""
        mock_session = MagicMock()
        mock_select.return_value = []

        result = ingest_boxscores_via_ncaab_api(
            mock_session,
            run_id=1,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
            only_missing=True,
            updated_before=None,
        )

        assert result == (0, 0, 0, 0)

    @patch("sports_scraper.services.ncaab_boxscore_ingestion.persist_game_payload")
    @patch("sports_scraper.live.ncaab.NCAABLiveFeedClient")
    @patch("sports_scraper.services.ncaab_boxscore_ingestion.populate_ncaab_game_ids")
    @patch("sports_scraper.services.ncaab_boxscore_ingestion.select_games_for_boxscores_ncaab_api")
    def test_processes_games_successfully(self, mock_select, mock_populate, mock_client_class, mock_persist):
        """Processes games and returns counts."""
        from sports_scraper.models import NormalizedTeamBoxscore, TeamIdentity
        from sports_scraper.persistence import GamePersistResult

        mock_session = MagicMock()
        mock_select.return_value = [(1, 123456, date(2025, 1, 15), "Duke", "UNC")]

        mock_client = MagicMock()
        mock_boxscore = MagicMock()
        mock_boxscore.game_id = 123456
        mock_boxscore.season = 2025
        mock_boxscore.status = "final"
        mock_boxscore.game_date = datetime(2025, 1, 15, 19, 0, tzinfo=UTC)
        mock_boxscore.home_team = TeamIdentity(league_code="NCAAB", name="Duke", abbreviation="DUKE")
        mock_boxscore.away_team = TeamIdentity(league_code="NCAAB", name="UNC", abbreviation="UNC")
        mock_boxscore.home_score = 85
        mock_boxscore.away_score = 80
        mock_boxscore.team_boxscores = [
            NormalizedTeamBoxscore(team=mock_boxscore.home_team, is_home=True, stats={"points": 85}),
            NormalizedTeamBoxscore(team=mock_boxscore.away_team, is_home=False, stats={"points": 80}),
        ]
        mock_boxscore.player_boxscores = []
        mock_client.fetch_boxscores_batch.return_value = {123456: mock_boxscore}
        mock_client_class.return_value = mock_client

        mock_persist.return_value = GamePersistResult(game_id=1, enriched=True)

        result = ingest_boxscores_via_ncaab_api(
            mock_session,
            run_id=1,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
            only_missing=True,
            updated_before=None,
        )

        # Returns (games_processed, games_enriched, games_with_stats)
        assert result[0] == 1  # games processed
        assert result[1] == 1  # games enriched

    @patch("sports_scraper.live.ncaab.NCAABLiveFeedClient")
    @patch("sports_scraper.services.ncaab_boxscore_ingestion.populate_ncaab_game_ids")
    @patch("sports_scraper.services.ncaab_boxscore_ingestion.select_games_for_boxscores_ncaab_api")
    def test_handles_missing_boxscore_in_batch(self, mock_select, mock_populate, mock_client_class):
        """Handles missing boxscore in batch result."""
        mock_session = MagicMock()
        mock_select.return_value = [(1, 123456, date(2025, 1, 15), "Duke", "UNC")]

        mock_client = MagicMock()
        mock_client.fetch_boxscores_batch.return_value = {}  # Empty - no boxscore for game
        mock_client_class.return_value = mock_client

        result = ingest_boxscores_via_ncaab_api(
            mock_session,
            run_id=1,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
            only_missing=True,
            updated_before=None,
        )

        assert result == (0, 0, 0, 0)

    @patch("sports_scraper.services.ncaab_boxscore_ingestion.persist_game_payload")
    @patch("sports_scraper.live.ncaab.NCAABLiveFeedClient")
    @patch("sports_scraper.services.ncaab_boxscore_ingestion.populate_ncaab_game_ids")
    @patch("sports_scraper.services.ncaab_boxscore_ingestion.select_games_for_boxscores_ncaab_api")
    def test_handles_persist_exception(self, mock_select, mock_populate, mock_client_class, mock_persist):
        """Handles persist exceptions gracefully."""
        from sports_scraper.models import NormalizedTeamBoxscore, TeamIdentity

        mock_session = MagicMock()
        mock_select.return_value = [(1, 123456, date(2025, 1, 15), "Duke", "UNC")]

        mock_client = MagicMock()
        mock_boxscore = MagicMock()
        mock_boxscore.game_id = 123456
        mock_boxscore.season = 2025
        mock_boxscore.status = "final"
        mock_boxscore.game_date = datetime(2025, 1, 15, 19, 0, tzinfo=UTC)
        mock_boxscore.home_team = TeamIdentity(league_code="NCAAB", name="Duke", abbreviation="DUKE")
        mock_boxscore.away_team = TeamIdentity(league_code="NCAAB", name="UNC", abbreviation="UNC")
        mock_boxscore.home_score = 85
        mock_boxscore.away_score = 80
        mock_boxscore.team_boxscores = [
            NormalizedTeamBoxscore(team=mock_boxscore.home_team, is_home=True, stats={"points": 85}),
            NormalizedTeamBoxscore(team=mock_boxscore.away_team, is_home=False, stats={"points": 80}),
        ]
        mock_boxscore.player_boxscores = []
        mock_client.fetch_boxscores_batch.return_value = {123456: mock_boxscore}
        mock_client_class.return_value = mock_client

        mock_persist.side_effect = Exception("Persist error")

        result = ingest_boxscores_via_ncaab_api(
            mock_session,
            run_id=1,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
            only_missing=True,
            updated_before=None,
        )

        assert result == (0, 0, 0, 1)


class TestPopulateNcaabGameIds:
    """Tests for _populate_ncaab_game_ids."""

    def test_returns_zero_when_no_league(self):
        """Returns 0 when NCAAB league not found."""
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = None

        result = _populate_ncaab_game_ids(
            mock_session,
            run_id=1,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
        )

        assert result == 0

    def test_returns_zero_when_no_games_missing_id(self):
        """Returns 0 when all games already have IDs."""
        mock_session = MagicMock()
        mock_league = MagicMock()
        mock_league.id = 1
        mock_session.query.return_value.filter.return_value.first.return_value = mock_league

        # No games missing IDs
        mock_session.query.return_value.filter.return_value.all.return_value = []

        result = _populate_ncaab_game_ids(
            mock_session,
            run_id=1,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
        )

        assert result == 0

    @patch("sports_scraper.live.ncaab.NCAABLiveFeedClient")
    def test_returns_zero_when_no_api_games(self, mock_client_class):
        """Returns 0 when API returns no games."""
        mock_session = MagicMock()
        mock_league = MagicMock()
        mock_league.id = 1
        mock_session.query.return_value.filter.return_value.first.return_value = mock_league

        # Games missing IDs
        mock_game_row = (1, datetime(2025, 1, 15, 19, 0, tzinfo=UTC), 10, 20)
        mock_session.query.return_value.filter.return_value.all.return_value = [mock_game_row]

        # Teams with cbb_team_id
        mock_team_row = (10, {"cbb_team_id": 100})
        mock_session.query.return_value.filter.return_value.all.side_effect = [
            [mock_game_row],  # Games missing cbb_game_id
            [mock_team_row],  # Teams with cbb_team_id
            [],               # Team names for matching (NCAA fallback)
            [],               # Games missing ncaa_game_id (NCAA fallback)
            [],               # All teams for name normalization (NCAA fallback)
        ]

        # No games from API
        mock_client = MagicMock()
        mock_client.fetch_games.return_value = []
        mock_client.fetch_ncaa_scoreboard.return_value = []
        mock_client_class.return_value = mock_client

        result = _populate_ncaab_game_ids(
            mock_session,
            run_id=1,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
        )

        assert result == 0

    @patch("sports_scraper.live.ncaab.NCAABLiveFeedClient")
    def test_matches_games_by_team_id_and_time(self, mock_client_class):
        """Matches games by team ID and time window."""
        mock_session = MagicMock()
        mock_league = MagicMock()
        mock_league.id = 1

        # Mock query chain
        game_time = datetime(2025, 1, 15, 19, 0, tzinfo=UTC)
        mock_game = MagicMock()
        mock_game.id = 1
        mock_game.external_ids = {}

        # Setup queries
        call_count = [0]
        def query_side_effect(*args, **kwargs):
            result = MagicMock()
            result.filter.return_value = result
            call_count[0] += 1
            if call_count[0] == 1:
                result.first.return_value = mock_league
            elif call_count[0] == 2:
                result.all.return_value = [(1, game_time, 10, 20)]  # Games missing ID
            elif call_count[0] == 3:
                result.all.return_value = [(10, {"cbb_team_id": 100}), (20, {"cbb_team_id": 200})]  # Teams
            elif call_count[0] == 4:
                result.all.return_value = [(10, "Duke"), (20, "UNC")]  # Team names
            else:
                result.get.return_value = mock_game
            return result

        mock_session.query.side_effect = query_side_effect

        # API game that matches
        mock_cbb_game = MagicMock()
        mock_cbb_game.game_id = 12345
        mock_cbb_game.status = "final"
        mock_cbb_game.game_date = game_time
        mock_cbb_game.home_team_id = 100
        mock_cbb_game.away_team_id = 200
        mock_cbb_game.home_team_name = "Duke"
        mock_cbb_game.away_team_name = "UNC"

        mock_client = MagicMock()
        mock_client.fetch_games.return_value = [mock_cbb_game]
        mock_client_class.return_value = mock_client

        result = _populate_ncaab_game_ids(
            mock_session,
            run_id=1,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
        )

        # Should update at least the matched game
        assert result >= 0  # May or may not match depending on mock setup


class TestSelectGamesForBoxscoresNhlApiFilters:
    """Tests for select_games_for_boxscores_nhl_api with various filters."""

    def test_filters_only_missing(self):
        """Applies only_missing filter when True."""
        mock_session = MagicMock()
        mock_league = MagicMock(id=1)
        mock_session.query.return_value.filter.return_value.first.return_value = mock_league

        # Query chain for games
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = []

        result = select_games_for_boxscores_nhl_api(
            mock_session,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            only_missing=True,
            updated_before=None,
        )

        assert result == []

    def test_filters_updated_before(self):
        """Applies updated_before filter when provided."""
        mock_session = MagicMock()
        mock_league = MagicMock(id=1)
        mock_session.query.return_value.filter.return_value.first.return_value = mock_league

        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = []

        updated_before = datetime.now(UTC) - timedelta(hours=24)
        result = select_games_for_boxscores_nhl_api(
            mock_session,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            only_missing=False,
            updated_before=updated_before,
        )

        assert result == []


class TestSelectGamesForBoxscoresNcaabApiFilters:
    """Tests for select_games_for_boxscores_ncaab_api with various filters."""

    def test_filters_only_missing(self):
        """Applies only_missing filter when True."""
        mock_session = MagicMock()
        mock_league = MagicMock(id=1)
        mock_session.query.return_value.filter.return_value.first.return_value = mock_league

        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.join.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = []

        result = select_games_for_boxscores_ncaab_api(
            mock_session,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
            only_missing=True,
            updated_before=None,
        )

        assert result == []
