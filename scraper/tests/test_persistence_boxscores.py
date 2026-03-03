"""Tests for persistence/boxscores.py module."""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure the scraper package is importable
REPO_ROOT = Path(__file__).resolve().parents[2]
SCRAPER_ROOT = REPO_ROOT / "scraper"
if str(SCRAPER_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRAPER_ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/test_db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ENVIRONMENT", "development")


from sports_scraper.models import (
    NormalizedPlayerBoxscore,
    NormalizedTeamBoxscore,
    TeamIdentity,
)
from sports_scraper.persistence.boxscores import (
    GamePersistResult,
    _build_player_stats,
    _build_team_stats,
    upsert_player_boxscores,
    upsert_team_boxscores,
)


class TestBuildTeamStats:
    """Tests for _build_team_stats function."""

    def test_builds_stats_dict(self):
        """Builds stats dictionary from boxscore."""
        boxscore = NormalizedTeamBoxscore(
            team=TeamIdentity(league_code="NBA", name="Boston Celtics", abbreviation="BOS"),
            is_home=True,
            points=110,
        )
        result = _build_team_stats(boxscore)
        assert isinstance(result, dict)
        assert result.get("points") == 110


class TestBuildPlayerStats:
    """Tests for _build_player_stats function."""

    def test_builds_stats_dict(self):
        """Builds stats dictionary from player boxscore."""
        boxscore = NormalizedPlayerBoxscore(
            player_id="12345",
            player_name="Jayson Tatum",
            team=TeamIdentity(league_code="NBA", name="Boston Celtics", abbreviation="BOS"),
            points=28,
            minutes=36.5,
        )
        result = _build_player_stats(boxscore)
        assert isinstance(result, dict)
        # Only non-None values are included
        assert result.get("points") == 28
        assert result.get("minutes") == 36.5

    def test_returns_empty_dict_for_no_stats(self):
        """Returns empty dict when all stats are None."""
        boxscore = NormalizedPlayerBoxscore(
            player_id="99999",
            player_name="Test Player",
            team=TeamIdentity(league_code="NBA", name="Boston Celtics", abbreviation="BOS"),
        )
        result = _build_player_stats(boxscore)
        assert isinstance(result, dict)


class TestGamePersistResult:
    """Tests for GamePersistResult dataclass."""

    def test_creates_result(self):
        """Creates result with game_id."""
        result = GamePersistResult(game_id=1)
        assert result.game_id == 1


class TestUpsertTeamBoxscores:
    """Tests for upsert_team_boxscores function."""

    def test_handles_empty_list(self):
        """Handles empty boxscore list without error."""
        mock_session = MagicMock()
        # Should not raise
        upsert_team_boxscores(mock_session, game_id=1, payloads=[])


class TestUpsertPlayerBoxscores:
    """Tests for upsert_player_boxscores function."""

    def test_handles_empty_list(self):
        """Handles empty boxscore list without error."""
        mock_session = MagicMock()
        # Should not raise
        result = upsert_player_boxscores(mock_session, game_id=1, payloads=[])
        assert result.inserted == 0
        assert result.rejected == 0
        assert result.errors == 0


class TestValidateNhlPlayerBoxscore:
    """Tests for _validate_nhl_player_boxscore function."""

    def test_non_nhl_always_valid(self):
        """Non-NHL boxscores always pass validation."""
        from sports_scraper.persistence.boxscores import _validate_nhl_player_boxscore

        payload = NormalizedPlayerBoxscore(
            player_id="123",
            player_name="",  # Empty name would fail for NHL
            team=TeamIdentity(league_code="NBA", name="Celtics", abbreviation="BOS"),
        )
        result = _validate_nhl_player_boxscore(payload, game_id=1)
        assert result is None  # Valid

    def test_nhl_missing_player_name_rejected(self):
        """NHL boxscore with missing player name is rejected."""
        from sports_scraper.persistence.boxscores import _validate_nhl_player_boxscore

        payload = NormalizedPlayerBoxscore(
            player_id="123",
            player_name="",
            team=TeamIdentity(league_code="NHL", name="Bruins", abbreviation="BOS"),
            player_role="skater",
        )
        result = _validate_nhl_player_boxscore(payload, game_id=1)
        assert result == "missing_player_name"

    def test_nhl_missing_player_role_rejected(self):
        """NHL boxscore with missing player role is rejected."""
        from sports_scraper.persistence.boxscores import _validate_nhl_player_boxscore

        payload = NormalizedPlayerBoxscore(
            player_id="123",
            player_name="Brad Marchand",
            team=TeamIdentity(league_code="NHL", name="Bruins", abbreviation="BOS"),
            player_role=None,
        )
        result = _validate_nhl_player_boxscore(payload, game_id=1)
        assert result == "missing_player_role"

    def test_nhl_skater_all_stats_null_rejected(self):
        """NHL skater with all stats null is rejected."""
        from sports_scraper.persistence.boxscores import _validate_nhl_player_boxscore

        payload = NormalizedPlayerBoxscore(
            player_id="123",
            player_name="Brad Marchand",
            team=TeamIdentity(league_code="NHL", name="Bruins", abbreviation="BOS"),
            player_role="skater",
            # All stats are None
        )
        result = _validate_nhl_player_boxscore(payload, game_id=1)
        assert result == "all_stats_null"

    def test_nhl_skater_with_stats_valid(self):
        """NHL skater with at least one stat is valid."""
        from sports_scraper.persistence.boxscores import _validate_nhl_player_boxscore

        payload = NormalizedPlayerBoxscore(
            player_id="123",
            player_name="Brad Marchand",
            team=TeamIdentity(league_code="NHL", name="Bruins", abbreviation="BOS"),
            player_role="skater",
            goals=2,
        )
        result = _validate_nhl_player_boxscore(payload, game_id=1)
        assert result is None  # Valid

    def test_nhl_goalie_all_stats_null_rejected(self):
        """NHL goalie with all stats null is rejected."""
        from sports_scraper.persistence.boxscores import _validate_nhl_player_boxscore

        payload = NormalizedPlayerBoxscore(
            player_id="123",
            player_name="Jeremy Swayman",
            team=TeamIdentity(league_code="NHL", name="Bruins", abbreviation="BOS"),
            player_role="goalie",
        )
        result = _validate_nhl_player_boxscore(payload, game_id=1)
        assert result == "all_stats_null"

    def test_nhl_goalie_with_stats_valid(self):
        """NHL goalie with at least one stat is valid."""
        from sports_scraper.persistence.boxscores import _validate_nhl_player_boxscore

        payload = NormalizedPlayerBoxscore(
            player_id="123",
            player_name="Jeremy Swayman",
            team=TeamIdentity(league_code="NHL", name="Bruins", abbreviation="BOS"),
            player_role="goalie",
            saves=30,
        )
        result = _validate_nhl_player_boxscore(payload, game_id=1)
        assert result is None  # Valid

    def test_nhl_unknown_role_rejected(self):
        """NHL boxscore with unknown role is rejected (no stats check passes)."""
        from sports_scraper.persistence.boxscores import _validate_nhl_player_boxscore

        payload = NormalizedPlayerBoxscore(
            player_id="123",
            player_name="Test Player",
            team=TeamIdentity(league_code="NHL", name="Bruins", abbreviation="BOS"),
            player_role="unknown_role",
        )
        result = _validate_nhl_player_boxscore(payload, game_id=1)
        assert result == "all_stats_null"


class TestBuildTeamStatsAdvanced:
    """Advanced tests for _build_team_stats covering all fields."""

    def test_includes_rebounds(self):
        """Includes rebounds when present."""
        boxscore = NormalizedTeamBoxscore(
            team=TeamIdentity(league_code="NBA", name="Celtics", abbreviation="BOS"),
            is_home=True,
            rebounds=45,
        )
        result = _build_team_stats(boxscore)
        assert result.get("rebounds") == 45

    def test_includes_assists(self):
        """Includes assists when present."""
        boxscore = NormalizedTeamBoxscore(
            team=TeamIdentity(league_code="NBA", name="Celtics", abbreviation="BOS"),
            is_home=True,
            assists=25,
        )
        result = _build_team_stats(boxscore)
        assert result.get("assists") == 25

    def test_includes_turnovers(self):
        """Includes turnovers when present."""
        boxscore = NormalizedTeamBoxscore(
            team=TeamIdentity(league_code="NBA", name="Celtics", abbreviation="BOS"),
            is_home=True,
            turnovers=12,
        )
        result = _build_team_stats(boxscore)
        assert result.get("turnovers") == 12

    def test_includes_hockey_stats(self):
        """Includes hockey-specific stats."""
        boxscore = NormalizedTeamBoxscore(
            team=TeamIdentity(league_code="NHL", name="Bruins", abbreviation="BOS"),
            is_home=True,
            shots_on_goal=35,
            penalty_minutes=8,
        )
        result = _build_team_stats(boxscore)
        assert result.get("shots_on_goal") == 35
        assert result.get("penalty_minutes") == 8

    def test_merges_raw_stats(self):
        """Merges raw_stats into result."""
        boxscore = NormalizedTeamBoxscore(
            team=TeamIdentity(league_code="NBA", name="Celtics", abbreviation="BOS"),
            is_home=True,
            points=110,
            raw_stats={"field_goals": 40, "three_pointers": 15},
        )
        result = _build_team_stats(boxscore)
        assert result.get("points") == 110
        assert result.get("field_goals") == 40
        assert result.get("three_pointers") == 15


class TestBuildPlayerStatsAdvanced:
    """Advanced tests for _build_player_stats covering all fields."""

    def test_includes_player_role(self):
        """Includes player_role when present."""
        boxscore = NormalizedPlayerBoxscore(
            player_id="123",
            player_name="Test Player",
            team=TeamIdentity(league_code="NHL", name="Bruins", abbreviation="BOS"),
            player_role="skater",
        )
        result = _build_player_stats(boxscore)
        assert result.get("player_role") == "skater"

    def test_includes_position_and_sweater(self):
        """Includes position and sweater_number when present."""
        boxscore = NormalizedPlayerBoxscore(
            player_id="123",
            player_name="Test Player",
            team=TeamIdentity(league_code="NHL", name="Bruins", abbreviation="BOS"),
            position="C",
            sweater_number=37,
        )
        result = _build_player_stats(boxscore)
        assert result.get("position") == "C"
        assert result.get("sweater_number") == 37

    def test_includes_nhl_skater_stats(self):
        """Includes NHL skater-specific stats."""
        boxscore = NormalizedPlayerBoxscore(
            player_id="123",
            player_name="Test Player",
            team=TeamIdentity(league_code="NHL", name="Bruins", abbreviation="BOS"),
            shots_on_goal=5,
            penalties=1,
            goals=2,
            plus_minus=3,
            hits=4,
            blocked_shots=2,
            shifts=25,
            giveaways=1,
            takeaways=2,
            faceoff_pct=55.5,
        )
        result = _build_player_stats(boxscore)
        assert result.get("shots_on_goal") == 5
        assert result.get("penalties") == 1
        assert result.get("goals") == 2
        assert result.get("plus_minus") == 3
        assert result.get("hits") == 4
        assert result.get("blocked_shots") == 2
        assert result.get("shifts") == 25
        assert result.get("giveaways") == 1
        assert result.get("takeaways") == 2
        assert result.get("faceoff_pct") == 55.5

    def test_includes_nhl_goalie_stats(self):
        """Includes NHL goalie-specific stats."""
        boxscore = NormalizedPlayerBoxscore(
            player_id="123",
            player_name="Test Goalie",
            team=TeamIdentity(league_code="NHL", name="Bruins", abbreviation="BOS"),
            saves=30,
            goals_against=2,
            shots_against=32,
            save_percentage=0.938,
        )
        result = _build_player_stats(boxscore)
        assert result.get("saves") == 30
        assert result.get("goals_against") == 2
        assert result.get("shots_against") == 32
        assert result.get("save_percentage") == 0.938


class TestPlayerBoxscoreStats:
    """Tests for PlayerBoxscoreStats dataclass."""

    def test_total_processed_property(self):
        """total_processed returns sum of all counts."""
        from sports_scraper.persistence.boxscores import PlayerBoxscoreStats

        stats = PlayerBoxscoreStats(inserted=10, rejected=2, errors=1)
        assert stats.total_processed == 13

    def test_default_values(self):
        """Default values are all zero."""
        from sports_scraper.persistence.boxscores import PlayerBoxscoreStats

        stats = PlayerBoxscoreStats()
        assert stats.inserted == 0
        assert stats.rejected == 0
        assert stats.errors == 0
        assert stats.total_processed == 0


class TestGamePersistResultAdvanced:
    """Advanced tests for GamePersistResult."""

    def test_has_player_stats_true_when_inserted(self):
        """has_player_stats returns True when players were inserted."""
        from sports_scraper.persistence.boxscores import PlayerBoxscoreStats

        player_stats = PlayerBoxscoreStats(inserted=5, rejected=0, errors=0)
        result = GamePersistResult(game_id=1, enriched=True, player_stats=player_stats)
        assert result.has_player_stats is True

    def test_has_player_stats_false_when_none(self):
        """has_player_stats returns False when player_stats is None."""
        result = GamePersistResult(game_id=1, enriched=True, player_stats=None)
        assert result.has_player_stats is False

    def test_has_player_stats_false_when_no_inserted(self):
        """has_player_stats returns False when no players inserted."""
        from sports_scraper.persistence.boxscores import PlayerBoxscoreStats

        player_stats = PlayerBoxscoreStats(inserted=0, rejected=5, errors=0)
        result = GamePersistResult(game_id=1, enriched=True, player_stats=player_stats)
        assert result.has_player_stats is False


class TestUpsertTeamBoxscoresWithPayload:
    """Tests for upsert_team_boxscores with actual payloads."""

    @patch("sports_scraper.persistence.boxscores._upsert_team")
    @patch("sports_scraper.persistence.boxscores.get_league_id")
    def test_upserts_team_boxscore(self, mock_get_league_id, mock_upsert_team):
        """Upserts team boxscore with stats."""
        mock_session = MagicMock()
        mock_get_league_id.return_value = 1
        mock_upsert_team.return_value = 10
        mock_session.execute.return_value.rowcount = 1

        payload = NormalizedTeamBoxscore(
            team=TeamIdentity(league_code="NBA", name="Celtics", abbreviation="BOS"),
            is_home=True,
            points=110,
            rebounds=45,
        )

        upsert_team_boxscores(mock_session, game_id=1, payloads=[payload])

        mock_get_league_id.assert_called_once()
        mock_upsert_team.assert_called_once()
        mock_session.execute.assert_called()

    @patch("sports_scraper.persistence.boxscores._upsert_team")
    @patch("sports_scraper.persistence.boxscores.get_league_id")
    def test_updates_last_ingested_at_when_updated(self, mock_get_league_id, mock_upsert_team):
        """Updates game.last_ingested_at when boxscore is updated."""
        mock_session = MagicMock()
        mock_get_league_id.return_value = 1
        mock_upsert_team.return_value = 10
        mock_session.execute.return_value.rowcount = 1

        payload = NormalizedTeamBoxscore(
            team=TeamIdentity(league_code="NBA", name="Celtics", abbreviation="BOS"),
            is_home=True,
            points=110,
        )

        upsert_team_boxscores(mock_session, game_id=1, payloads=[payload])

        # Should call query to update last_ingested_at
        mock_session.query.assert_called()


class TestUpsertPlayerBoxscoresWithPayload:
    """Tests for upsert_player_boxscores with actual payloads."""

    @patch("sports_scraper.persistence.boxscores.upsert_player")
    @patch("sports_scraper.persistence.boxscores._upsert_team")
    @patch("sports_scraper.persistence.boxscores.get_league_id")
    def test_upserts_player_boxscore(self, mock_get_league_id, mock_upsert_team, mock_upsert_player):
        """Upserts player boxscore with stats."""
        mock_session = MagicMock()
        mock_get_league_id.return_value = 1
        mock_upsert_team.return_value = 10
        mock_upsert_player.return_value = 100
        mock_session.execute.return_value.rowcount = 1

        payload = NormalizedPlayerBoxscore(
            player_id="123",
            player_name="Jayson Tatum",
            team=TeamIdentity(league_code="NBA", name="Celtics", abbreviation="BOS"),
            points=28,
            minutes=36.5,
        )

        result = upsert_player_boxscores(mock_session, game_id=1, payloads=[payload])

        assert result.inserted == 1
        assert result.rejected == 0
        assert result.errors == 0
        mock_upsert_player.assert_called_once()

    @patch("sports_scraper.persistence.boxscores._upsert_team")
    @patch("sports_scraper.persistence.boxscores.get_league_id")
    def test_rejects_invalid_nhl_boxscore(self, mock_get_league_id, mock_upsert_team):
        """Rejects invalid NHL boxscore."""
        mock_session = MagicMock()
        mock_get_league_id.return_value = 1
        mock_upsert_team.return_value = 10

        # NHL player with missing player name
        payload = NormalizedPlayerBoxscore(
            player_id="123",
            player_name="",
            team=TeamIdentity(league_code="NHL", name="Bruins", abbreviation="BOS"),
            player_role="skater",
        )

        result = upsert_player_boxscores(mock_session, game_id=1, payloads=[payload])

        assert result.inserted == 0
        assert result.rejected == 1
        assert result.errors == 0

    @patch("sports_scraper.persistence.boxscores._upsert_team")
    @patch("sports_scraper.persistence.boxscores.get_league_id")
    def test_handles_exception_during_insert(self, mock_get_league_id, mock_upsert_team):
        """Handles exception during player boxscore insert."""
        mock_session = MagicMock()
        mock_get_league_id.return_value = 1
        mock_upsert_team.side_effect = Exception("Database error")

        payload = NormalizedPlayerBoxscore(
            player_id="123",
            player_name="Test Player",
            team=TeamIdentity(league_code="NBA", name="Celtics", abbreviation="BOS"),
            points=20,
        )

        result = upsert_player_boxscores(mock_session, game_id=1, payloads=[payload])

        assert result.inserted == 0
        assert result.rejected == 0
        assert result.errors == 1


class TestFindGameForBoxscore:
    """Tests for _find_game_for_boxscore function."""

    def test_finds_game_in_date_range(self):
        """Finds game within date window."""
        from sports_scraper.persistence.boxscores import _find_game_for_boxscore

        mock_session = MagicMock()
        mock_game = MagicMock()
        mock_session.query.return_value.filter.return_value.filter.return_value.filter.return_value.filter.return_value.filter.return_value.order_by.return_value.first.return_value = mock_game

        game_date = datetime(2024, 1, 15, 19, 0, tzinfo=UTC)
        result = _find_game_for_boxscore(
            mock_session,
            league_id=1,
            home_team_id=10,
            away_team_id=20,
            game_date=game_date,
        )

        assert result == mock_game

    def test_returns_none_when_not_found(self):
        """Returns None when game not found."""
        from sports_scraper.persistence.boxscores import _find_game_for_boxscore

        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.filter.return_value.filter.return_value.filter.return_value.filter.return_value.order_by.return_value.first.return_value = None

        game_date = datetime(2024, 1, 15, 19, 0, tzinfo=UTC)
        result = _find_game_for_boxscore(
            mock_session,
            league_id=1,
            home_team_id=10,
            away_team_id=20,
            game_date=game_date,
        )

        assert result is None




class TestUpsertPlayer:
    """Tests for upsert_player function."""

    def test_upserts_player_and_returns_id(self):
        """Upserts player and returns the ID."""
        from sports_scraper.persistence.boxscores import upsert_player

        mock_session = MagicMock()
        mock_player = MagicMock()
        mock_player.id = 100
        mock_session.query.return_value.filter.return_value.first.return_value = mock_player

        result = upsert_player(
            mock_session,
            league_id=1,
            external_id="player_123",
            name="Test Player",
            position="C",
            sweater_number=37,
            team_id=10,
        )

        assert result == 100
        mock_session.execute.assert_called_once()
        mock_session.flush.assert_called_once()

    def test_returns_zero_when_player_not_found(self):
        """Returns 0 when player not found after upsert."""
        from sports_scraper.persistence.boxscores import upsert_player

        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = None

        result = upsert_player(
            mock_session,
            league_id=1,
            external_id="player_123",
            name="Test Player",
        )

        assert result == 0
