"""Tests for services/pbp_ingestion.py module."""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch

from sports_scraper.services.pbp_ingestion import (
    ingest_pbp_via_nba_api,
    ingest_pbp_via_ncaab_api,
    ingest_pbp_via_nhl_api,
    ingest_pbp_via_sportsref,
    populate_nba_game_ids,
    populate_nhl_game_ids,
    select_games_for_pbp_nba_api,
    select_games_for_pbp_ncaab_api,
    select_games_for_pbp_nhl_api,
)
from sports_scraper.services.pbp_nba import _is_current_nba_season


class TestSelectGamesForPbpNbaApi:
    """Tests for select_games_for_pbp_nba_api function."""

    def test_returns_empty_when_no_league(self):
        """Returns empty list when NBA league not found."""
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = None

        result = select_games_for_pbp_nba_api(
            mock_session,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            only_missing=True,
            updated_before=None,
        )

        assert result == []

    def test_returns_games_with_nba_game_id(self):
        """Returns games with valid nba_game_id."""
        mock_session = MagicMock()
        mock_league = MagicMock(id=1)
        mock_session.query.return_value.filter.return_value.first.return_value = mock_league

        # Mock the game query result
        mock_row = MagicMock()
        mock_row.__iter__ = lambda self: iter([100, "0022400123", "final"])
        mock_session.query.return_value.filter.return_value.all.return_value = [mock_row]

        result = select_games_for_pbp_nba_api(
            mock_session,
            start_date=date(2024, 10, 1),
            end_date=date(2024, 10, 31),
            only_missing=False,
            updated_before=None,
        )

        assert len(result) == 1
        assert result[0] == (100, "0022400123")

    def test_filters_with_only_missing(self):
        """Applies only_missing filter when enabled."""
        mock_session = MagicMock()
        mock_league = MagicMock(id=1)
        mock_session.query.return_value.filter.return_value.first.return_value = mock_league

        mock_row = MagicMock()
        mock_row.__iter__ = lambda self: iter([100, "0022400123", "final"])
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = [mock_row]
        mock_session.query.return_value.filter.return_value = mock_query

        _result = select_games_for_pbp_nba_api(
            mock_session,
            start_date=date(2024, 10, 1),
            end_date=date(2024, 10, 31),
            only_missing=True,
            updated_before=None,
        )

        # Verify filter was called for only_missing (result not checked, just filter behavior)
        assert mock_query.filter.called

    def test_filters_with_updated_before(self):
        """Applies updated_before filter when provided."""
        mock_session = MagicMock()
        mock_league = MagicMock(id=1)
        mock_session.query.return_value.filter.return_value.first.return_value = mock_league

        mock_row = MagicMock()
        mock_row.__iter__ = lambda self: iter([100, "0022400123", "final"])
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = [mock_row]
        mock_session.query.return_value.filter.return_value = mock_query

        result = select_games_for_pbp_nba_api(
            mock_session,
            start_date=date(2024, 10, 1),
            end_date=date(2024, 10, 31),
            only_missing=False,
            updated_before=datetime(2024, 10, 15, tzinfo=UTC),
        )

        # Verify filter was applied
        assert mock_query.filter.called


class TestIngestPbpViaNbaApi:
    """Tests for ingest_pbp_via_nba_api."""

    @patch("sports_scraper.services.pbp_nba.populate_nba_game_ids")
    @patch("sports_scraper.services.pbp_nba.select_games_for_pbp_nba_api")
    def test_returns_zero_when_no_games(self, mock_select, mock_populate):
        """Returns (0, 0) when no games selected."""
        mock_session = MagicMock()
        mock_select.return_value = []

        result = ingest_pbp_via_nba_api(
            mock_session,
            run_id=1,
            start_date=date(2024, 10, 1),
            end_date=date(2024, 10, 31),
            only_missing=True,
            updated_before=None,
        )

        assert result == (0, 0)

    @patch("sports_scraper.persistence.plays.upsert_plays")
    @patch("sports_scraper.live.nba.NBALiveFeedClient")
    @patch("sports_scraper.services.pbp_nba.populate_nba_game_ids")
    @patch("sports_scraper.services.pbp_nba.select_games_for_pbp_nba_api")
    def test_successful_ingestion(self, mock_select, mock_populate, mock_client_class, mock_upsert):
        """Successfully ingests PBP with player_name populated."""
        from sports_scraper.models import NormalizedPlay

        mock_session = MagicMock()
        mock_select.return_value = [(1, "0022400123")]

        mock_client = MagicMock()
        mock_payload = MagicMock()
        mock_payload.plays = [
            NormalizedPlay(
                play_index=1,
                quarter=1,
                game_clock="12:00",
                play_type="shot",
                description="Tatum makes 3-pointer",
                player_name="Jayson Tatum",  # NBA API provides player_name
            ),
        ]
        mock_client.fetch_play_by_play.return_value = mock_payload
        mock_client_class.return_value = mock_client

        mock_game = MagicMock()
        mock_game.status = "final"
        mock_game.external_ids = {"nba_game_id": "0022400123"}
        mock_session.query.return_value.get.return_value = mock_game
        mock_upsert.return_value = 1

        result = ingest_pbp_via_nba_api(
            mock_session,
            run_id=1,
            start_date=date(2024, 10, 1),
            end_date=date(2024, 10, 31),
            only_missing=True,
            updated_before=None,
        )

        assert result == (1, 1)
        # Verify player_name was in the play
        assert mock_payload.plays[0].player_name == "Jayson Tatum"

    @patch("sports_scraper.live.nba.NBALiveFeedClient")
    @patch("sports_scraper.services.pbp_nba.populate_nba_game_ids")
    @patch("sports_scraper.services.pbp_nba.select_games_for_pbp_nba_api")
    def test_handles_empty_pbp_response(self, mock_select, mock_populate, mock_client_class):
        """Handles empty PBP response."""
        mock_session = MagicMock()
        mock_select.return_value = [(1, "0022400123")]

        mock_client = MagicMock()
        mock_payload = MagicMock()
        mock_payload.plays = []
        mock_client.fetch_play_by_play.return_value = mock_payload
        mock_client_class.return_value = mock_client

        mock_game = MagicMock()
        mock_game.status = "final"
        mock_game.external_ids = {"nba_game_id": "0022400123"}
        mock_session.query.return_value.get.return_value = mock_game

        result = ingest_pbp_via_nba_api(
            mock_session,
            run_id=1,
            start_date=date(2024, 10, 1),
            end_date=date(2024, 10, 31),
            only_missing=True,
            updated_before=None,
        )

        assert result == (0, 0)

    @patch("sports_scraper.live.nba.NBALiveFeedClient")
    @patch("sports_scraper.services.pbp_nba.populate_nba_game_ids")
    @patch("sports_scraper.services.pbp_nba.select_games_for_pbp_nba_api")
    def test_handles_fetch_exception(self, mock_select, mock_populate, mock_client_class):
        """Handles fetch exception gracefully."""
        mock_session = MagicMock()
        mock_select.return_value = [(1, "0022400123")]

        mock_client = MagicMock()
        mock_client.fetch_play_by_play.side_effect = Exception("NBA API error")
        mock_client_class.return_value = mock_client

        mock_game = MagicMock()
        mock_game.status = "final"
        mock_game.external_ids = {"nba_game_id": "0022400123"}
        mock_session.query.return_value.get.return_value = mock_game

        result = ingest_pbp_via_nba_api(
            mock_session,
            run_id=1,
            start_date=date(2024, 10, 1),
            end_date=date(2024, 10, 31),
            only_missing=True,
            updated_before=None,
        )

        assert result == (0, 0)

    @patch("sports_scraper.persistence.plays.upsert_plays")
    @patch("sports_scraper.live.nba.NBALiveFeedClient")
    @patch("sports_scraper.services.pbp_nba.populate_nba_game_ids")
    @patch("sports_scraper.services.pbp_nba.select_games_for_pbp_nba_api")
    def test_warns_on_insufficient_plays_for_final_game(self, mock_select, mock_populate, mock_client_class, mock_upsert):
        """Warns when final game has too few plays."""
        from sports_scraper.db import db_models
        from sports_scraper.models import NormalizedPlay

        mock_session = MagicMock()
        mock_select.return_value = [(1, "0022400123")]

        mock_client = MagicMock()
        mock_payload = MagicMock()
        # Only 5 plays - below minimum expected
        mock_payload.plays = [
            NormalizedPlay(play_index=i, quarter=1, game_clock="12:00", play_type="shot", description="test")
            for i in range(5)
        ]
        mock_client.fetch_play_by_play.return_value = mock_payload
        mock_client_class.return_value = mock_client

        # Mock game as final
        mock_game = MagicMock()
        mock_game.status = db_models.GameStatus.final.value
        mock_game.external_ids = {"nba_game_id": "0022400123"}
        mock_session.query.return_value.get.return_value = mock_game
        mock_upsert.return_value = 5

        result = ingest_pbp_via_nba_api(
            mock_session,
            run_id=1,
            start_date=date(2024, 10, 1),
            end_date=date(2024, 10, 31),
            only_missing=True,
            updated_before=None,
        )

        # Should still process the game
        assert result == (1, 5)


class TestIsCurrentNbaSeason:
    """Tests for _is_current_nba_season guard."""

    @patch("sports_scraper.utils.datetime_utils.today_et", return_value=date(2026, 1, 15))
    def test_current_season_dates(self, _mock_today):
        """Mid-season dates for 2025-26 season should return True."""
        assert _is_current_nba_season(date(2025, 10, 22), date(2026, 4, 13)) is True

    @patch("sports_scraper.utils.datetime_utils.today_et", return_value=date(2026, 1, 15))
    def test_historical_season_dates(self, _mock_today):
        """Dates from 2023-24 season should return False when current is 2025-26."""
        assert _is_current_nba_season(date(2023, 10, 24), date(2024, 4, 14)) is False

    @patch("sports_scraper.utils.datetime_utils.today_et", return_value=date(2026, 1, 15))
    def test_overlap_partial(self, _mock_today):
        """A range ending in the current season should return True."""
        assert _is_current_nba_season(date(2024, 10, 1), date(2025, 12, 1)) is True

    @patch("sports_scraper.utils.datetime_utils.today_et", return_value=date(2026, 1, 15))
    def test_historical_skips_populate(self, _mock_today):
        """populate_nba_game_ids should return 0 for historical seasons."""
        mock_session = MagicMock()
        result = populate_nba_game_ids(
            mock_session, run_id=1,
            start_date=date(2022, 10, 18), end_date=date(2023, 4, 9),
        )
        assert result == 0
        # Should not have queried the DB at all
        mock_session.query.assert_not_called()


class TestPopulateNbaGameIds:
    """Tests for populate_nba_game_ids."""

    def test_returns_zero_when_no_league(self):
        """Returns 0 when NBA league not found."""
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = None

        result = populate_nba_game_ids(
            mock_session,
            run_id=1,
            start_date=date(2024, 10, 1),
            end_date=date(2024, 10, 31),
        )

        assert result == 0

    @patch("sports_scraper.live.nba.NBALiveFeedClient")
    def test_returns_zero_when_no_games_missing(self, mock_client_class):
        """Returns 0 when no games are missing nba_game_id."""
        mock_session = MagicMock()
        mock_league = MagicMock(id=1)

        # Create a mock query object that properly chains
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = mock_league
        mock_query.all.return_value = []

        mock_session.query.return_value = mock_query

        result = populate_nba_game_ids(
            mock_session,
            run_id=1,
            start_date=date(2024, 10, 1),
            end_date=date(2024, 10, 31),
        )

        assert result == 0


class TestSelectGamesForPbpNhlApi:
    """Tests for select_games_for_pbp_nhl_api function."""

    def test_returns_empty_when_no_league(self):
        """Returns empty list when NHL league not found."""
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = None

        result = select_games_for_pbp_nhl_api(
            mock_session,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            only_missing=True,
            updated_before=None,
        )

        assert result == []

    def test_returns_games_with_nhl_game_pk(self):
        """Returns games with valid nhl_game_pk."""
        mock_session = MagicMock()
        mock_league = MagicMock(id=1)
        mock_session.query.return_value.filter.return_value.first.return_value = mock_league

        # Mock the game query result
        mock_row = MagicMock()
        mock_row.__iter__ = lambda self: iter([100, "2025020001", "final"])
        mock_session.query.return_value.filter.return_value.all.return_value = [mock_row]

        result = select_games_for_pbp_nhl_api(
            mock_session,
            start_date=date(2024, 10, 1),
            end_date=date(2024, 10, 31),
            only_missing=False,
            updated_before=None,
        )

        assert len(result) == 1
        assert result[0] == (100, 2025020001)

    def test_handles_invalid_nhl_game_pk(self):
        """Handles invalid nhl_game_pk values gracefully."""
        mock_session = MagicMock()
        mock_league = MagicMock(id=1)
        mock_session.query.return_value.filter.return_value.first.return_value = mock_league

        # Mock row with invalid nhl_game_pk
        mock_row = MagicMock()
        mock_row.__iter__ = lambda self: iter([100, "invalid", "final"])
        mock_session.query.return_value.filter.return_value.all.return_value = [mock_row]

        result = select_games_for_pbp_nhl_api(
            mock_session,
            start_date=date(2024, 10, 1),
            end_date=date(2024, 10, 31),
            only_missing=False,
            updated_before=None,
        )

        # Invalid game_pk should be filtered out
        assert len(result) == 0

    def test_filters_with_only_missing(self):
        """Applies only_missing filter when enabled."""
        mock_session = MagicMock()
        mock_league = MagicMock(id=1)
        mock_session.query.return_value.filter.return_value.first.return_value = mock_league

        mock_row = MagicMock()
        mock_row.__iter__ = lambda self: iter([100, "2025020001", "final"])
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = [mock_row]
        mock_session.query.return_value.filter.return_value = mock_query

        result = select_games_for_pbp_nhl_api(
            mock_session,
            start_date=date(2024, 10, 1),
            end_date=date(2024, 10, 31),
            only_missing=True,
            updated_before=None,
        )

        # Verify filter was called for only_missing
        assert mock_query.filter.called

    def test_filters_with_updated_before(self):
        """Applies updated_before filter when provided."""
        mock_session = MagicMock()
        mock_league = MagicMock(id=1)
        mock_session.query.return_value.filter.return_value.first.return_value = mock_league

        mock_row = MagicMock()
        mock_row.__iter__ = lambda self: iter([100, "2025020001", "final"])
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = [mock_row]
        mock_session.query.return_value.filter.return_value = mock_query

        result = select_games_for_pbp_nhl_api(
            mock_session,
            start_date=date(2024, 10, 1),
            end_date=date(2024, 10, 31),
            only_missing=False,
            updated_before=datetime(2024, 10, 15, tzinfo=UTC),
        )

        # Verify filter was applied
        assert mock_query.filter.called


class TestSelectGamesForPbpNcaabApi:
    """Tests for select_games_for_pbp_ncaab_api function."""

    def test_returns_empty_when_no_league(self):
        """Returns empty list when NCAAB league not found."""
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = None

        result = select_games_for_pbp_ncaab_api(
            mock_session,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            only_missing=True,
            updated_before=None,
        )

        assert result == []

    def test_returns_games_with_cbb_game_id(self):
        """Returns games with valid cbb_game_id."""
        mock_session = MagicMock()
        mock_league = MagicMock(id=9)
        mock_session.query.return_value.filter.return_value.first.return_value = mock_league

        # Mock the game query result
        mock_row = MagicMock()
        mock_row.__iter__ = lambda self: iter([100, "123456", "final"])
        mock_session.query.return_value.filter.return_value.all.return_value = [mock_row]

        result = select_games_for_pbp_ncaab_api(
            mock_session,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
            only_missing=False,
            updated_before=None,
        )

        assert len(result) == 1
        assert result[0] == (100, 123456, "final")

    def test_handles_invalid_cbb_game_id(self):
        """Handles invalid cbb_game_id values gracefully."""
        mock_session = MagicMock()
        mock_league = MagicMock(id=9)
        mock_session.query.return_value.filter.return_value.first.return_value = mock_league

        # Mock row with invalid cbb_game_id
        mock_row = MagicMock()
        mock_row.__iter__ = lambda self: iter([100, "invalid", "final"])
        mock_session.query.return_value.filter.return_value.all.return_value = [mock_row]

        result = select_games_for_pbp_ncaab_api(
            mock_session,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
            only_missing=False,
            updated_before=None,
        )

        # Invalid cbb_game_id should be filtered out
        assert len(result) == 0

    def test_filters_with_only_missing(self):
        """Applies only_missing filter when enabled."""
        mock_session = MagicMock()
        mock_league = MagicMock(id=9)
        mock_session.query.return_value.filter.return_value.first.return_value = mock_league

        mock_row = MagicMock()
        mock_row.__iter__ = lambda self: iter([100, "123456", "final"])
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = [mock_row]
        mock_session.query.return_value.filter.return_value = mock_query

        result = select_games_for_pbp_ncaab_api(
            mock_session,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
            only_missing=True,
            updated_before=None,
        )

        # Verify filter was called for only_missing
        assert mock_query.filter.called

    def test_filters_with_updated_before(self):
        """Applies updated_before filter when provided."""
        mock_session = MagicMock()
        mock_league = MagicMock(id=9)
        mock_session.query.return_value.filter.return_value.first.return_value = mock_league

        mock_row = MagicMock()
        mock_row.__iter__ = lambda self: iter([100, "123456", "final"])
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = [mock_row]
        mock_session.query.return_value.filter.return_value = mock_query

        result = select_games_for_pbp_ncaab_api(
            mock_session,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
            only_missing=False,
            updated_before=datetime(2025, 1, 15, tzinfo=UTC),
        )

        # Verify filter was applied
        assert mock_query.filter.called


class TestIngestPbpViaSportsref:
    """Tests for ingest_pbp_via_sportsref."""

    def test_returns_zero_when_no_scraper(self):
        """Returns (0, 0) when no scraper available."""
        mock_session = MagicMock()

        result = ingest_pbp_via_sportsref(
            mock_session,
            run_id=1,
            league_code="NBA",
            scraper=None,  # No scraper
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            only_missing=True,
            updated_before=None,
        )

        assert result == (0, 0)

    @patch("sports_scraper.services.pbp_ingestion.upsert_plays")
    @patch("sports_scraper.services.pbp_ingestion.select_games_for_pbp_sportsref")
    def test_returns_zero_when_no_games(self, mock_select, mock_upsert):
        """Returns (0, 0) when no games selected."""
        mock_session = MagicMock()
        mock_scraper = MagicMock()
        mock_select.return_value = []

        result = ingest_pbp_via_sportsref(
            mock_session,
            run_id=1,
            league_code="NBA",
            scraper=mock_scraper,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            only_missing=True,
            updated_before=None,
        )

        assert result == (0, 0)

    @patch("sports_scraper.services.pbp_ingestion.upsert_plays")
    @patch("sports_scraper.services.pbp_ingestion.select_games_for_pbp_sportsref")
    def test_handles_not_implemented(self, mock_select, mock_upsert):
        """Returns (0, 0) when scraper raises NotImplementedError."""
        mock_session = MagicMock()
        mock_scraper = MagicMock()
        mock_scraper.fetch_play_by_play.side_effect = NotImplementedError()
        mock_select.return_value = [(1, "BOS202401150", date(2024, 1, 15))]

        result = ingest_pbp_via_sportsref(
            mock_session,
            run_id=1,
            league_code="NBA",
            scraper=mock_scraper,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            only_missing=True,
            updated_before=None,
        )

        assert result == (0, 0)

    @patch("sports_scraper.services.pbp_ingestion.upsert_plays")
    @patch("sports_scraper.services.pbp_ingestion.select_games_for_pbp_sportsref")
    def test_handles_fetch_exception(self, mock_select, mock_upsert):
        """Continues when fetch raises exception."""
        mock_session = MagicMock()
        mock_scraper = MagicMock()
        mock_scraper.fetch_play_by_play.side_effect = Exception("Fetch error")
        mock_select.return_value = [(1, "BOS202401150", date(2024, 1, 15))]

        result = ingest_pbp_via_sportsref(
            mock_session,
            run_id=1,
            league_code="NBA",
            scraper=mock_scraper,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            only_missing=True,
            updated_before=None,
        )

        assert result == (0, 0)

    @patch("sports_scraper.services.pbp_ingestion.upsert_plays")
    @patch("sports_scraper.services.pbp_ingestion.select_games_for_pbp_sportsref")
    def test_successful_ingestion(self, mock_select, mock_upsert):
        """Successfully ingests PBP."""
        from sports_scraper.models import NormalizedPlay

        mock_session = MagicMock()
        mock_scraper = MagicMock()

        mock_payload = MagicMock()
        mock_payload.plays = [
            NormalizedPlay(play_index=1, quarter=1, game_clock="12:00", play_type="shot", description="test"),
        ]
        mock_scraper.fetch_play_by_play.return_value = mock_payload

        mock_select.return_value = [(1, "BOS202401150", date(2024, 1, 15))]
        mock_upsert.return_value = 1

        result = ingest_pbp_via_sportsref(
            mock_session,
            run_id=1,
            league_code="NBA",
            scraper=mock_scraper,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            only_missing=True,
            updated_before=None,
        )

        assert result == (1, 1)


class TestIngestPbpViaNhlApi:
    """Tests for ingest_pbp_via_nhl_api."""

    @patch("sports_scraper.services.pbp_nhl.populate_nhl_game_ids")
    @patch("sports_scraper.services.pbp_nhl.select_games_for_pbp_nhl_api")
    def test_returns_zero_when_no_games(self, mock_select, mock_populate):
        """Returns (0, 0) when no games selected."""
        mock_session = MagicMock()
        mock_select.return_value = []

        result = ingest_pbp_via_nhl_api(
            mock_session,
            run_id=1,
            start_date=date(2024, 10, 1),
            end_date=date(2024, 10, 31),
            only_missing=True,
            updated_before=None,
        )

        assert result == (0, 0)

    @patch("sports_scraper.persistence.plays.upsert_plays")
    @patch("sports_scraper.live.nhl.NHLLiveFeedClient")
    @patch("sports_scraper.services.pbp_nhl.populate_nhl_game_ids")
    @patch("sports_scraper.services.pbp_nhl.select_games_for_pbp_nhl_api")
    def test_successful_ingestion(self, mock_select, mock_populate, mock_client_class, mock_upsert):
        """Successfully ingests PBP."""
        from sports_scraper.models import NormalizedPlay

        mock_session = MagicMock()
        mock_select.return_value = [(1, 2025020001)]

        mock_client = MagicMock()
        mock_payload = MagicMock()
        mock_payload.plays = [
            NormalizedPlay(play_index=1, quarter=1, game_clock="12:00", play_type="shot", description="test"),
        ]
        mock_client.fetch_play_by_play.return_value = mock_payload
        mock_client_class.return_value = mock_client

        mock_game = MagicMock()
        mock_game.status = "final"
        mock_game.external_ids = {"nhl_game_pk": "2025020001"}
        mock_session.query.return_value.get.return_value = mock_game
        mock_upsert.return_value = 1

        result = ingest_pbp_via_nhl_api(
            mock_session,
            run_id=1,
            start_date=date(2024, 10, 1),
            end_date=date(2024, 10, 31),
            only_missing=True,
            updated_before=None,
        )

        assert result == (1, 1)

    @patch("sports_scraper.live.nhl.NHLLiveFeedClient")
    @patch("sports_scraper.services.pbp_nhl.populate_nhl_game_ids")
    @patch("sports_scraper.services.pbp_nhl.select_games_for_pbp_nhl_api")
    def test_handles_empty_pbp_response(self, mock_select, mock_populate, mock_client_class):
        """Handles empty PBP response."""
        mock_session = MagicMock()
        mock_select.return_value = [(1, 2025020001)]

        mock_client = MagicMock()
        mock_payload = MagicMock()
        mock_payload.plays = []
        mock_client.fetch_play_by_play.return_value = mock_payload
        mock_client_class.return_value = mock_client

        mock_game = MagicMock()
        mock_game.status = "final"
        mock_game.external_ids = {"nhl_game_pk": "2025020001"}
        mock_session.query.return_value.get.return_value = mock_game

        result = ingest_pbp_via_nhl_api(
            mock_session,
            run_id=1,
            start_date=date(2024, 10, 1),
            end_date=date(2024, 10, 31),
            only_missing=True,
            updated_before=None,
        )

        assert result == (0, 0)

    @patch("sports_scraper.live.nhl.NHLLiveFeedClient")
    @patch("sports_scraper.services.pbp_nhl.populate_nhl_game_ids")
    @patch("sports_scraper.services.pbp_nhl.select_games_for_pbp_nhl_api")
    def test_handles_fetch_exception(self, mock_select, mock_populate, mock_client_class):
        """Handles fetch exception."""
        mock_session = MagicMock()
        mock_select.return_value = [(1, 2025020001)]

        mock_client = MagicMock()
        mock_client.fetch_play_by_play.side_effect = Exception("Fetch error")
        mock_client_class.return_value = mock_client

        mock_game = MagicMock()
        mock_game.status = "final"
        mock_game.external_ids = {"nhl_game_pk": "2025020001"}
        mock_session.query.return_value.get.return_value = mock_game

        result = ingest_pbp_via_nhl_api(
            mock_session,
            run_id=1,
            start_date=date(2024, 10, 1),
            end_date=date(2024, 10, 31),
            only_missing=True,
            updated_before=None,
        )

        assert result == (0, 0)

    @patch("sports_scraper.persistence.plays.upsert_plays")
    @patch("sports_scraper.live.nhl.NHLLiveFeedClient")
    @patch("sports_scraper.services.pbp_nhl.populate_nhl_game_ids")
    @patch("sports_scraper.services.pbp_nhl.select_games_for_pbp_nhl_api")
    def test_warns_on_insufficient_plays_for_final_game(self, mock_select, mock_populate, mock_client_class, mock_upsert):
        """Warns when final game has too few plays."""
        from sports_scraper.db import db_models
        from sports_scraper.models import NormalizedPlay

        mock_session = MagicMock()
        mock_select.return_value = [(1, 2025020001)]

        mock_client = MagicMock()
        mock_payload = MagicMock()
        # Only 5 plays - below minimum expected
        mock_payload.plays = [
            NormalizedPlay(play_index=i, quarter=1, game_clock="12:00", play_type="shot", description="test")
            for i in range(5)
        ]
        mock_client.fetch_play_by_play.return_value = mock_payload
        mock_client_class.return_value = mock_client

        # Mock game as final
        mock_game = MagicMock()
        mock_game.status = db_models.GameStatus.final.value
        mock_game.external_ids = {"nhl_game_pk": "2025020001"}
        mock_session.query.return_value.get.return_value = mock_game
        mock_upsert.return_value = 5

        result = ingest_pbp_via_nhl_api(
            mock_session,
            run_id=1,
            start_date=date(2024, 10, 1),
            end_date=date(2024, 10, 31),
            only_missing=True,
            updated_before=None,
        )

        # Should still process the game
        assert result == (1, 5)


class TestIngestPbpViaNcaabApi:
    """Tests for ingest_pbp_via_ncaab_api."""

    @patch("sports_scraper.services.ncaab_boxscore_ingestion.populate_ncaab_game_ids")
    @patch("sports_scraper.services.pbp_ncaab.select_games_for_pbp_ncaab_api")
    def test_returns_zero_when_no_games(self, mock_select, mock_populate):
        """Returns (0, 0) when no games selected."""
        mock_session = MagicMock()
        mock_select.return_value = []

        result = ingest_pbp_via_ncaab_api(
            mock_session,
            run_id=1,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
            only_missing=True,
            updated_before=None,
        )

        assert result == (0, 0)

    @patch("sports_scraper.persistence.plays.upsert_plays")
    @patch("sports_scraper.live.ncaab.NCAABLiveFeedClient")
    @patch("sports_scraper.services.ncaab_boxscore_ingestion.populate_ncaab_game_ids")
    @patch("sports_scraper.services.pbp_ncaab.select_games_for_pbp_ncaab_api")
    def test_successful_ingestion(self, mock_select, mock_populate, mock_client_class, mock_upsert):
        """Successfully ingests PBP."""
        from sports_scraper.models import NormalizedPlay

        mock_session = MagicMock()
        mock_select.return_value = [(1, 123456, "final")]

        mock_client = MagicMock()
        mock_payload = MagicMock()
        mock_payload.plays = [
            NormalizedPlay(play_index=1, quarter=1, game_clock="20:00", play_type="shot", description="test"),
        ]
        mock_client.fetch_play_by_play.return_value = mock_payload
        mock_client_class.return_value = mock_client

        mock_game = MagicMock()
        mock_game.status = "final"
        mock_game.external_ids = {"cbb_game_id": "123456"}
        mock_session.query.return_value.get.return_value = mock_game
        mock_upsert.return_value = 1

        result = ingest_pbp_via_ncaab_api(
            mock_session,
            run_id=1,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
            only_missing=True,
            updated_before=None,
        )

        assert result == (1, 1)

    @patch("sports_scraper.live.ncaab.NCAABLiveFeedClient")
    @patch("sports_scraper.services.ncaab_boxscore_ingestion.populate_ncaab_game_ids")
    @patch("sports_scraper.services.pbp_ncaab.select_games_for_pbp_ncaab_api")
    def test_handles_empty_pbp_response(self, mock_select, mock_populate, mock_client_class):
        """Handles empty PBP response."""
        mock_session = MagicMock()
        mock_select.return_value = [(1, 123456, "final")]

        mock_client = MagicMock()
        mock_payload = MagicMock()
        mock_payload.plays = []
        mock_client.fetch_play_by_play.return_value = mock_payload
        mock_client_class.return_value = mock_client

        mock_game = MagicMock()
        mock_game.status = "final"
        mock_game.external_ids = {"cbb_game_id": "123456"}
        mock_session.query.return_value.get.return_value = mock_game

        result = ingest_pbp_via_ncaab_api(
            mock_session,
            run_id=1,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
            only_missing=True,
            updated_before=None,
        )

        assert result == (0, 0)

    @patch("sports_scraper.live.ncaab.NCAABLiveFeedClient")
    @patch("sports_scraper.services.ncaab_boxscore_ingestion.populate_ncaab_game_ids")
    @patch("sports_scraper.services.pbp_ncaab.select_games_for_pbp_ncaab_api")
    def test_handles_fetch_exception(self, mock_select, mock_populate, mock_client_class):
        """Handles fetch exception gracefully."""
        mock_session = MagicMock()
        mock_select.return_value = [(1, 123456, "final")]

        mock_client = MagicMock()
        mock_client.fetch_play_by_play.side_effect = Exception("CBB API error")
        mock_client_class.return_value = mock_client

        mock_game = MagicMock()
        mock_game.status = "final"
        mock_game.external_ids = {"cbb_game_id": "123456"}
        mock_session.query.return_value.get.return_value = mock_game

        result = ingest_pbp_via_ncaab_api(
            mock_session,
            run_id=1,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
            only_missing=True,
            updated_before=None,
        )

        assert result == (0, 0)

    @patch("sports_scraper.persistence.plays.upsert_plays")
    @patch("sports_scraper.live.ncaab.NCAABLiveFeedClient")
    @patch("sports_scraper.services.ncaab_boxscore_ingestion.populate_ncaab_game_ids")
    @patch("sports_scraper.services.pbp_ncaab.select_games_for_pbp_ncaab_api")
    def test_warns_on_insufficient_plays_for_final_game(self, mock_select, mock_populate, mock_client_class, mock_upsert):
        """Warns when final game has too few plays."""
        from sports_scraper.db import db_models
        from sports_scraper.models import NormalizedPlay

        mock_session = MagicMock()
        mock_select.return_value = [(1, 123456, "final")]

        mock_client = MagicMock()
        mock_payload = MagicMock()
        # Only 10 plays - below minimum expected for NCAAB
        mock_payload.plays = [
            NormalizedPlay(play_index=i, quarter=1, game_clock="20:00", play_type="shot", description="test")
            for i in range(10)
        ]
        mock_client.fetch_play_by_play.return_value = mock_payload
        mock_client_class.return_value = mock_client

        # Mock game as final
        mock_game = MagicMock()
        mock_game.status = db_models.GameStatus.final.value
        mock_game.external_ids = {"cbb_game_id": "123456"}
        mock_session.query.return_value.get.return_value = mock_game
        mock_upsert.return_value = 10

        result = ingest_pbp_via_ncaab_api(
            mock_session,
            run_id=1,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
            only_missing=True,
            updated_before=None,
        )

        # Should still process the game
        assert result == (1, 10)


class TestPopulateNhlGameIds:
    """Tests for populate_nhl_game_ids."""

    def test_returns_zero_when_no_league(self):
        """Returns 0 when NHL league not found."""
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = None

        result = populate_nhl_game_ids(
            mock_session,
            run_id=1,
            start_date=date(2024, 10, 1),
            end_date=date(2024, 10, 31),
        )

        assert result == 0

    @patch("sports_scraper.live.nhl.NHLLiveFeedClient")
    def test_returns_zero_when_no_games_missing(self, mock_client_class):
        """Returns 0 when no games are missing nhl_game_pk."""
        mock_session = MagicMock()
        mock_league = MagicMock(id=1)

        # Create a mock query object that properly chains
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = mock_league
        mock_query.all.return_value = []

        mock_session.query.return_value = mock_query

        result = populate_nhl_game_ids(
            mock_session,
            run_id=1,
            start_date=date(2024, 10, 1),
            end_date=date(2024, 10, 31),
        )

        assert result == 0

    @patch("sports_scraper.live.nhl.NHLLiveFeedClient")
    def test_populates_nhl_game_ids_with_matching_games(self, mock_client_class):
        """Populates nhl_game_pk for games when there's a match."""
        mock_session = MagicMock()
        mock_league = MagicMock(id=1)

        # Mock game row: (game_id, game_date, home_team_id, away_team_id)
        mock_game_row = (100, datetime(2024, 10, 15, 19, 0, tzinfo=UTC), 10, 20)

        # Mock teams
        mock_team1 = MagicMock(id=10, abbreviation="BOS")
        mock_team2 = MagicMock(id=20, abbreviation="NYR")

        # Mock game object for update
        mock_game = MagicMock()
        mock_game.external_ids = {}

        query_call_count = [0]
        def mock_query_side_effect(*args):
            query_call_count[0] += 1
            mock_query = MagicMock()
            mock_query.filter.return_value = mock_query

            if query_call_count[0] == 1:
                # League query
                mock_query.first.return_value = mock_league
            elif query_call_count[0] == 2:
                # Games missing pk query
                mock_query.all.return_value = [mock_game_row]
            elif query_call_count[0] == 3:
                # Teams query
                mock_query.all.return_value = [mock_team1, mock_team2]
            else:
                # Get game by ID
                mock_query.get.return_value = mock_game
            return mock_query

        mock_session.query.side_effect = mock_query_side_effect

        # Mock NHL client
        mock_client = MagicMock()
        mock_nhl_game = MagicMock()
        mock_nhl_game.home_team = MagicMock(abbreviation="BOS")
        mock_nhl_game.away_team = MagicMock(abbreviation="NYR")
        mock_nhl_game.game_date = datetime(2024, 10, 15, 19, 0, tzinfo=UTC)
        mock_nhl_game.game_id = 2024020100
        mock_client.fetch_schedule.return_value = [mock_nhl_game]
        mock_client_class.return_value = mock_client

        result = populate_nhl_game_ids(
            mock_session,
            run_id=1,
            start_date=date(2024, 10, 1),
            end_date=date(2024, 10, 31),
        )

        # Should have updated the game
        assert result == 1
        mock_session.flush.assert_called()

    @patch("sports_scraper.live.nhl.NHLLiveFeedClient")
    def test_skips_games_when_no_match_found(self, mock_client_class):
        """Skips games when no matching NHL schedule entry found."""
        mock_session = MagicMock()
        mock_league = MagicMock(id=1)

        # Mock game row with team IDs that won't match
        mock_game_row = (100, datetime(2024, 10, 15, 19, 0, tzinfo=UTC), 10, 20)

        # Mock teams
        mock_team1 = MagicMock(id=10, abbreviation="BOS")
        mock_team2 = MagicMock(id=20, abbreviation="NYR")

        query_call_count = [0]
        def mock_query_side_effect(*args):
            query_call_count[0] += 1
            mock_query = MagicMock()
            mock_query.filter.return_value = mock_query

            if query_call_count[0] == 1:
                mock_query.first.return_value = mock_league
            elif query_call_count[0] == 2:
                mock_query.all.return_value = [mock_game_row]
            elif query_call_count[0] == 3:
                mock_query.all.return_value = [mock_team1, mock_team2]
            return mock_query

        mock_session.query.side_effect = mock_query_side_effect

        # Mock NHL client with different teams (no match)
        mock_client = MagicMock()
        mock_nhl_game = MagicMock()
        mock_nhl_game.home_team = MagicMock(abbreviation="LAK")  # Different team
        mock_nhl_game.away_team = MagicMock(abbreviation="CHI")  # Different team
        mock_nhl_game.game_date = datetime(2024, 10, 15, 19, 0, tzinfo=UTC)
        mock_nhl_game.game_id = 2024020100
        mock_client.fetch_schedule.return_value = [mock_nhl_game]
        mock_client_class.return_value = mock_client

        result = populate_nhl_game_ids(
            mock_session,
            run_id=1,
            start_date=date(2024, 10, 1),
            end_date=date(2024, 10, 31),
        )

        # No games should be updated (no match found)
        assert result == 0


class TestModuleImports:
    """Tests for module imports."""

    def test_has_nba_ingestion_function(self):
        """Module has NBA ingestion function."""
        from sports_scraper.services import pbp_ingestion
        assert hasattr(pbp_ingestion, 'ingest_pbp_via_nba_api')

    def test_has_nhl_ingestion_function(self):
        """Module has NHL ingestion function."""
        from sports_scraper.services import pbp_ingestion
        assert hasattr(pbp_ingestion, 'ingest_pbp_via_nhl_api')

    def test_has_ncaab_ingestion_function(self):
        """Module has NCAAB ingestion function."""
        from sports_scraper.services import pbp_ingestion
        assert hasattr(pbp_ingestion, 'ingest_pbp_via_ncaab_api')

    def test_has_nba_populate_function(self):
        """Module has NBA populate function."""
        from sports_scraper.services import pbp_ingestion
        assert hasattr(pbp_ingestion, 'populate_nba_game_ids')

    def test_has_nhl_populate_function(self):
        """Module has NHL populate function."""
        from sports_scraper.services import pbp_ingestion
        assert hasattr(pbp_ingestion, 'populate_nhl_game_ids')

    def test_has_sportsref_function(self):
        """Module has sportsref function."""
        from sports_scraper.services import pbp_ingestion
        assert hasattr(pbp_ingestion, 'ingest_pbp_via_sportsref')
