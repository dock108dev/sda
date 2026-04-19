"""Tests for persistence/games.py module."""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure the scraper package is importable
REPO_ROOT = Path(__file__).resolve().parents[2]
SCRAPER_ROOT = REPO_ROOT / "scraper"
if str(SCRAPER_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRAPER_ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/test_db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ENVIRONMENT", "development")


from sports_scraper.models import TeamIdentity
from sports_scraper.persistence.games import (
    _has_real_time,
    _normalize_status,
    merge_external_ids,
    resolve_status_transition,
)


@pytest.fixture(autouse=True)
def _mock_game_redis_cache(monkeypatch):
    """Disable Redis game match cache for all tests in this module."""
    monkeypatch.setattr("sports_scraper.persistence.games._cache_get", lambda key: None)
    monkeypatch.setattr("sports_scraper.persistence.games._cache_set", lambda key, game_id: None)
    monkeypatch.setattr("sports_scraper.persistence.games._cache_delete", lambda key: None)


class TestNormalizeStatus:
    """Tests for _normalize_status function."""

    def test_normalizes_final(self):
        """Normalizes 'final' status."""
        result = _normalize_status("final")
        assert result == "final"

    def test_normalizes_completed(self):
        """Normalizes 'completed' to 'final'."""
        result = _normalize_status("completed")
        assert result == "final"

    def test_normalizes_scheduled(self):
        """Normalizes 'scheduled' status."""
        result = _normalize_status("scheduled")
        assert result == "scheduled"

    def test_normalizes_none(self):
        """Normalizes None to 'scheduled'."""
        result = _normalize_status(None)
        assert result == "scheduled"

    def test_normalizes_empty_string(self):
        """Normalizes empty string to 'scheduled'."""
        result = _normalize_status("")
        assert result == "scheduled"

    def test_normalizes_live(self):
        """Normalizes 'live' status."""
        result = _normalize_status("live")
        assert result == "live"

    def test_normalizes_in_progress(self):
        """Normalizes 'in_progress' falls through to 'scheduled' (not explicitly handled)."""
        result = _normalize_status("in_progress")
        # Note: Only "live" is explicitly handled, not "in_progress"
        assert result == "scheduled"


class TestResolveStatusTransition:
    """Tests for resolve_status_transition function."""

    def test_keeps_final_status(self):
        """Keeps final status when already final."""
        result = resolve_status_transition("final", "scheduled")
        assert result == "final"

    def test_upgrades_to_final(self):
        """Upgrades status to final."""
        result = resolve_status_transition("scheduled", "final")
        assert result == "final"

    def test_upgrades_scheduled_to_live(self):
        """Upgrades scheduled to live."""
        result = resolve_status_transition("scheduled", "live")
        assert result == "live"

    def test_handles_none_current(self):
        """Handles None current status."""
        result = resolve_status_transition(None, "final")
        assert result == "final"

    def test_handles_none_incoming(self):
        """Handles None incoming status."""
        result = resolve_status_transition("scheduled", None)
        assert result == "scheduled"

    def test_live_can_go_to_final(self):
        """Live status can transition to final."""
        result = resolve_status_transition("live", "final")
        assert result == "final"

    def test_final_cannot_go_back(self):
        """Final status cannot transition backwards."""
        result = resolve_status_transition("final", "live")
        assert result == "final"


class TestMergeExternalIds:
    """Tests for merge_external_ids function."""

    def test_merges_new_ids(self):
        """Merges new external IDs."""
        existing = {"nhl_game_pk": "123"}
        new_ids = {"cbb_game_id": "456"}

        result = merge_external_ids(existing, new_ids)

        assert result["nhl_game_pk"] == "123"
        assert result["cbb_game_id"] == "456"

    def test_handles_none_existing(self):
        """Handles None existing IDs."""
        result = merge_external_ids(None, {"cbb_game_id": "456"})

        assert result["cbb_game_id"] == "456"

    def test_handles_none_new(self):
        """Handles None new IDs."""
        existing = {"nhl_game_pk": "123"}
        result = merge_external_ids(existing, None)

        assert result["nhl_game_pk"] == "123"

    def test_handles_both_none(self):
        """Handles both None."""
        result = merge_external_ids(None, None)

        assert result == {} or result is None

    def test_handles_empty_existing(self):
        """Handles empty existing dict."""
        existing = {}
        new_ids = {"cbb_game_id": "456"}

        result = merge_external_ids(existing, new_ids)

        assert result["cbb_game_id"] == "456"

    def test_handles_empty_new(self):
        """Handles empty new dict."""
        existing = {"nhl_game_pk": "123"}
        new_ids = {}

        result = merge_external_ids(existing, new_ids)

        assert result["nhl_game_pk"] == "123"

    def test_overwrites_existing_with_new(self):
        """New values overwrite existing values."""
        existing = {"odds_api_event_id": "old_value"}
        new_ids = {"odds_api_event_id": "new_value"}

        result = merge_external_ids(existing, new_ids)

        assert result["odds_api_event_id"] == "new_value"

    def test_skips_none_values_in_new(self):
        """Skips None values in new dict."""
        existing = {"nhl_game_pk": "123"}
        new_ids = {"cbb_game_id": "456", "empty_key": None}

        result = merge_external_ids(existing, new_ids)

        assert result["nhl_game_pk"] == "123"
        assert result["cbb_game_id"] == "456"
        assert "empty_key" not in result


class TestNormalizeStatusPostponedCanceled:
    """Tests for postponed/canceled handling in _normalize_status."""

    def test_normalizes_postponed(self):
        """Normalizes 'postponed' → 'postponed'."""
        assert _normalize_status("postponed") == "postponed"

    def test_normalizes_canceled(self):
        """Normalizes 'canceled' → 'cancelled' (canonical double-L)."""
        assert _normalize_status("canceled") == "cancelled"

    def test_normalizes_uppercase_postponed(self):
        """Case insensitive: 'POSTPONED' → 'postponed'."""
        assert _normalize_status("POSTPONED") == "postponed"

    def test_normalizes_uppercase_canceled(self):
        """Case insensitive: 'CANCELED' → 'cancelled' (canonical double-L)."""
        assert _normalize_status("CANCELED") == "cancelled"


class TestResolveStatusTransitionPostponedCanceled:
    """Tests for postponed/canceled pass-through in resolve_status_transition."""

    def test_postponed_passes_through(self):
        """Scheduled → postponed is accepted."""
        assert resolve_status_transition("scheduled", "postponed") == "postponed"

    def test_canceled_passes_through(self):
        """Scheduled → canceled is accepted (normalizes to canonical 'cancelled')."""
        assert resolve_status_transition("scheduled", "canceled") == "cancelled"


class TestNormalizeStatusCaseInsensitive:
    """Tests for case insensitivity of _normalize_status."""

    def test_normalizes_uppercase_final(self):
        """Normalizes 'FINAL' status."""
        result = _normalize_status("FINAL")
        assert result == "final"

    def test_normalizes_mixed_case_completed(self):
        """Normalizes 'Completed' to 'final'."""
        result = _normalize_status("Completed")
        assert result == "final"

    def test_normalizes_uppercase_live(self):
        """Normalizes 'LIVE' status."""
        result = _normalize_status("LIVE")
        assert result == "live"

    def test_normalizes_uppercase_scheduled(self):
        """Normalizes 'SCHEDULED' status."""
        result = _normalize_status("SCHEDULED")
        assert result == "scheduled"


class TestResolveStatusTransitionAdvanced:
    """Advanced tests for resolve_status_transition function."""

    def test_scheduled_to_scheduled_stays_scheduled(self):
        """Scheduled to scheduled stays scheduled."""
        result = resolve_status_transition("scheduled", "scheduled")
        assert result == "scheduled"

    def test_live_to_live_stays_live(self):
        """Live to live stays live."""
        result = resolve_status_transition("live", "live")
        assert result == "live"

    def test_final_to_final_stays_final(self):
        """Final to final stays final."""
        result = resolve_status_transition("final", "final")
        assert result == "final"

    def test_live_cannot_go_back_to_scheduled(self):
        """Live cannot regress to scheduled."""
        result = resolve_status_transition("live", "scheduled")
        assert result == "live"

    def test_none_to_none_is_scheduled(self):
        """None to None defaults to scheduled."""
        result = resolve_status_transition(None, None)
        assert result == "scheduled"


class TestModuleImports:
    """Tests for games module imports."""

    def test_has_normalize_status(self):
        """Module has _normalize_status function."""
        from sports_scraper.persistence import games
        assert hasattr(games, '_normalize_status')

    def test_has_resolve_status_transition(self):
        """Module has resolve_status_transition function."""
        from sports_scraper.persistence import games
        assert hasattr(games, 'resolve_status_transition')

    def test_has_merge_external_ids(self):
        """Module has merge_external_ids function."""
        from sports_scraper.persistence import games
        assert hasattr(games, 'merge_external_ids')

    def test_has_upsert_game_stub(self):
        """Module has upsert_game_stub function."""
        from sports_scraper.persistence import games
        assert hasattr(games, 'upsert_game_stub')

    def test_has_upsert_game(self):
        """Module has upsert_game function."""
        from sports_scraper.persistence import games
        assert hasattr(games, 'upsert_game')

    def test_has_update_game_from_live_feed(self):
        """Module has update_game_from_live_feed function."""
        from sports_scraper.persistence import games
        assert hasattr(games, 'update_game_from_live_feed')


class TestUpsertGameStub:
    """Tests for upsert_game_stub function."""

    @patch("sports_scraper.persistence.games._upsert_team")
    @patch("sports_scraper.persistence.games.get_league_id")
    def test_creates_new_game(self, mock_get_league_id, mock_upsert_team):
        """Creates a new game when none exists."""
        from sports_scraper.persistence.games import upsert_game_stub

        mock_session = MagicMock()
        mock_get_league_id.return_value = 1
        mock_upsert_team.side_effect = [10, 20]

        # Make all query chains return None for .first() at any depth
        query_mock = MagicMock()
        query_mock.filter.return_value = query_mock
        query_mock.first.return_value = None
        mock_session.query.return_value = query_mock
        mock_session.get.return_value = None

        home_team = TeamIdentity(league_code="NBA", name="Lakers", abbreviation="LAL")
        away_team = TeamIdentity(league_code="NBA", name="Celtics", abbreviation="BOS")

        game_id, created = upsert_game_stub(
            mock_session,
            league_code="NBA",
            game_date=datetime(2024, 1, 15, 19, 0, tzinfo=UTC),
            home_team=home_team,
            away_team=away_team,
            status="scheduled",
        )

        assert created is True
        mock_session.add.assert_called_once()
        mock_session.flush.assert_called()

    @patch("sports_scraper.persistence.games._upsert_team")
    @patch("sports_scraper.persistence.games.get_league_id")
    def test_updates_existing_game(self, mock_get_league_id, mock_upsert_team):
        """Updates an existing game when found by team IDs + date."""
        from sports_scraper.persistence.games import upsert_game_stub

        mock_session = MagicMock()
        mock_get_league_id.return_value = 1
        mock_upsert_team.side_effect = [10, 20]

        existing_game = MagicMock()
        existing_game.id = 42
        existing_game.status = "scheduled"
        existing_game.home_score = None
        existing_game.away_score = None
        existing_game.venue = None
        existing_game.external_ids = {}
        existing_game.game_date = datetime(2024, 1, 15, 19, 0, tzinfo=UTC)
        existing_game.season_type = "regular"

        # Make all query chains return existing_game for .first()
        query_mock = MagicMock()
        query_mock.filter.return_value = query_mock
        query_mock.first.return_value = existing_game
        mock_session.query.return_value = query_mock
        mock_session.get.return_value = None

        home_team = TeamIdentity(league_code="NBA", name="Lakers", abbreviation="LAL")
        away_team = TeamIdentity(league_code="NBA", name="Celtics", abbreviation="BOS")

        game_id, created = upsert_game_stub(
            mock_session,
            league_code="NBA",
            game_date=datetime(2024, 1, 15, 19, 0, tzinfo=UTC),
            home_team=home_team,
            away_team=away_team,
            status="live",
            home_score=55,
            away_score=48,
        )

        assert game_id == 42
        assert created is False
        assert existing_game.home_score == 55
        assert existing_game.away_score == 48

    @patch("sports_scraper.persistence.games._upsert_team")
    @patch("sports_scraper.persistence.games.get_league_id")
    def test_updates_venue(self, mock_get_league_id, mock_upsert_team):
        """Updates venue when changed."""
        from sports_scraper.persistence.games import upsert_game_stub

        mock_session = MagicMock()
        mock_get_league_id.return_value = 1
        mock_upsert_team.side_effect = [10, 20]

        existing_game = MagicMock()
        existing_game.id = 42
        existing_game.status = "scheduled"
        existing_game.home_score = None
        existing_game.away_score = None
        existing_game.venue = None
        existing_game.external_ids = {}
        existing_game.game_date = datetime(2024, 1, 15, 19, 0, tzinfo=UTC)
        query_mock = MagicMock()
        query_mock.filter.return_value = query_mock
        query_mock.first.return_value = existing_game
        mock_session.query.return_value = query_mock
        mock_session.get.return_value = None

        home_team = TeamIdentity(league_code="NBA", name="Lakers", abbreviation="LAL")
        away_team = TeamIdentity(league_code="NBA", name="Celtics", abbreviation="BOS")

        game_id, created = upsert_game_stub(
            mock_session,
            league_code="NBA",
            game_date=datetime(2024, 1, 15, 19, 0, tzinfo=UTC),
            home_team=home_team,
            away_team=away_team,
            status="scheduled",
            venue="Staples Center",
        )

        assert existing_game.venue == "Staples Center"

    @patch("sports_scraper.persistence.games._upsert_team")
    @patch("sports_scraper.persistence.games.get_league_id")
    def test_merges_external_ids(self, mock_get_league_id, mock_upsert_team):
        """Merges external_ids with existing."""
        from sports_scraper.persistence.games import upsert_game_stub

        mock_session = MagicMock()
        mock_get_league_id.return_value = 1
        mock_upsert_team.side_effect = [10, 20]

        existing_game = MagicMock()
        existing_game.id = 42
        existing_game.status = "scheduled"
        existing_game.home_score = None
        existing_game.away_score = None
        existing_game.venue = None
        existing_game.external_ids = {"existing": "123"}
        existing_game.game_date = datetime(2024, 1, 15, 19, 0, tzinfo=UTC)
        query_mock = MagicMock()
        query_mock.filter.return_value = query_mock
        query_mock.first.return_value = existing_game
        mock_session.query.return_value = query_mock
        mock_session.get.return_value = None

        home_team = TeamIdentity(league_code="NBA", name="Lakers", abbreviation="LAL")
        away_team = TeamIdentity(league_code="NBA", name="Celtics", abbreviation="BOS")

        upsert_game_stub(
            mock_session,
            league_code="NBA",
            game_date=datetime(2024, 1, 15, 19, 0, tzinfo=UTC),
            home_team=home_team,
            away_team=away_team,
            status="scheduled",
            external_ids={"new": "456"},
        )

        assert existing_game.external_ids == {"existing": "123", "new": "456"}


class TestUpdateGameFromLiveFeed:
    """Tests for update_game_from_live_feed function."""

    def test_updates_score(self):
        """Updates home and away scores."""
        from sports_scraper.persistence.games import update_game_from_live_feed

        mock_session = MagicMock()
        mock_game = MagicMock()
        mock_game.status = "live"
        mock_game.home_score = 50
        mock_game.away_score = 48
        mock_game.venue = None
        mock_game.external_ids = {}

        result = update_game_from_live_feed(
            mock_session,
            game=mock_game,
            status="live",
            home_score=55,
            away_score=52,
        )

        assert result is True
        assert mock_game.home_score == 55
        assert mock_game.away_score == 52

    def test_updates_venue(self):
        """Updates venue."""
        from sports_scraper.persistence.games import update_game_from_live_feed

        mock_session = MagicMock()
        mock_game = MagicMock()
        mock_game.status = "scheduled"
        mock_game.home_score = None
        mock_game.away_score = None
        mock_game.venue = None
        mock_game.external_ids = {}

        result = update_game_from_live_feed(
            mock_session,
            game=mock_game,
            status="scheduled",
            home_score=None,
            away_score=None,
            venue="Madison Square Garden",
        )

        assert result is True
        assert mock_game.venue == "Madison Square Garden"

    def test_merges_external_ids(self):
        """Merges external IDs."""
        from sports_scraper.persistence.games import update_game_from_live_feed

        mock_session = MagicMock()
        mock_game = MagicMock()
        mock_game.status = "scheduled"
        mock_game.home_score = None
        mock_game.away_score = None
        mock_game.venue = None
        mock_game.external_ids = {"existing": "123"}

        result = update_game_from_live_feed(
            mock_session,
            game=mock_game,
            status="scheduled",
            home_score=None,
            away_score=None,
            external_ids={"new": "456"},
        )

        assert result is True
        assert mock_game.external_ids == {"existing": "123", "new": "456"}

    def test_no_update_when_unchanged(self):
        """Returns False when nothing changed."""
        from sports_scraper.persistence.games import update_game_from_live_feed

        mock_session = MagicMock()
        mock_game = MagicMock()
        mock_game.status = "scheduled"
        mock_game.home_score = None
        mock_game.away_score = None
        mock_game.venue = None
        mock_game.external_ids = {}

        result = update_game_from_live_feed(
            mock_session,
            game=mock_game,
            status="scheduled",
            home_score=None,
            away_score=None,
        )

        assert result is False
        mock_session.flush.assert_not_called()


class TestUpsertGame:
    """Tests for upsert_game function (delegates to find_or_create_game)."""

    @patch("sports_scraper.persistence.games._upsert_team")
    @patch("sports_scraper.persistence.games.get_league_id")
    def test_upserts_game(self, mock_get_league_id, mock_upsert_team):
        """Creates a game via find_or_create_game when none exists."""
        from sports_scraper.models import GameIdentification, NormalizedGame, NormalizedTeamBoxscore
        from sports_scraper.persistence.games import upsert_game

        mock_session = MagicMock()
        mock_get_league_id.return_value = 1
        mock_upsert_team.side_effect = [10, 20]

        # All query chains return None (no existing game)
        query_mock = MagicMock()
        query_mock.filter.return_value = query_mock
        query_mock.first.return_value = None
        mock_session.query.return_value = query_mock
        mock_session.get.return_value = None

        home_team = TeamIdentity(league_code="NBA", name="Lakers", abbreviation="LAL")
        away_team = TeamIdentity(league_code="NBA", name="Celtics", abbreviation="BOS")
        identity = GameIdentification(
            league_code="NBA",
            season=2024,
            season_type="regular",
            game_date=datetime(2024, 1, 15, 5, 0, tzinfo=UTC),  # midnight ET
            home_team=home_team,
            away_team=away_team,
            source_game_key="nba_123",
        )
        team_boxscores = [
            NormalizedTeamBoxscore(team=home_team, is_home=True, points=110),
            NormalizedTeamBoxscore(team=away_team, is_home=False, points=105),
        ]
        normalized = NormalizedGame(
            identity=identity,
            home_score=110,
            away_score=105,
            status="final",
            venue="Staples Center",
            team_boxscores=team_boxscores,
        )

        game_id, created = upsert_game(mock_session, normalized)

        assert created is True
        mock_session.add.assert_called_once()

    @patch("sports_scraper.persistence.games._upsert_team")
    @patch("sports_scraper.persistence.games.get_league_id")
    def test_matches_existing_game(self, mock_get_league_id, mock_upsert_team):
        """Finds existing game and enriches it with boxscore data."""
        from sports_scraper.models import GameIdentification, NormalizedGame, NormalizedTeamBoxscore
        from sports_scraper.persistence.games import upsert_game

        mock_session = MagicMock()
        mock_get_league_id.return_value = 1
        mock_upsert_team.side_effect = [10, 20]

        existing_game = MagicMock()
        existing_game.id = 42
        existing_game.status = "scheduled"
        existing_game.home_score = None
        existing_game.away_score = None
        existing_game.venue = None
        existing_game.external_ids = {}
        existing_game.game_date = datetime(2024, 1, 15, 23, 0, tzinfo=UTC)
        existing_game.season_type = "regular"
        existing_game.source_game_key = None
        existing_game.scrape_version = 1

        query_mock = MagicMock()
        query_mock.filter.return_value = query_mock
        query_mock.first.return_value = existing_game
        mock_session.query.return_value = query_mock
        mock_session.get.return_value = existing_game

        home_team = TeamIdentity(league_code="NBA", name="Lakers", abbreviation="LAL")
        away_team = TeamIdentity(league_code="NBA", name="Celtics", abbreviation="BOS")
        identity = GameIdentification(
            league_code="NBA",
            season=2024,
            season_type="regular",
            game_date=datetime(2024, 1, 15, 5, 0, tzinfo=UTC),
            home_team=home_team,
            away_team=away_team,
            source_game_key="202401150LAL",
        )
        team_boxscores = [
            NormalizedTeamBoxscore(team=home_team, is_home=True, points=110),
            NormalizedTeamBoxscore(team=away_team, is_home=False, points=105),
        ]
        normalized = NormalizedGame(
            identity=identity,
            home_score=110,
            away_score=105,
            status="final",
            team_boxscores=team_boxscores,
        )

        game_id, created = upsert_game(mock_session, normalized)

        assert game_id == 42
        assert created is False
        # source_game_key should be set on the existing game
        assert existing_game.source_game_key == "202401150LAL"


class TestHasRealTime:
    """Tests for _has_real_time: detect placeholder vs real game times."""

    def test_bare_date_is_not_real(self):
        from datetime import date
        assert _has_real_time(date(2026, 4, 7)) is False

    def test_midnight_et_is_not_real(self):
        """Midnight ET placeholder (from _to_datetime on bare date)."""
        from sports_scraper.utils.datetime_utils import start_of_et_day_utc
        from datetime import date
        midnight = start_of_et_day_utc(date(2026, 4, 7))
        assert _has_real_time(midnight) is False

    def test_noon_et_is_not_real(self):
        """Noon ET placeholder (from NHL _et_noon_utc fallback)."""
        from sports_scraper.utils.datetime_utils import start_of_et_day_utc
        from datetime import date, timedelta
        noon = start_of_et_day_utc(date(2026, 4, 7)) + timedelta(hours=12)
        assert _has_real_time(noon) is False

    def test_real_game_time_is_real(self):
        """7 PM ET (23:00 UTC) is a real game time."""
        assert _has_real_time(datetime(2026, 4, 7, 23, 0, tzinfo=UTC)) is True

    def test_another_real_time(self):
        """1:30 AM UTC (9:30 PM ET) is a real game time."""
        assert _has_real_time(datetime(2026, 4, 8, 1, 30, tzinfo=UTC)) is True
