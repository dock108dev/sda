"""Tests for persistence/plays.py module."""

from __future__ import annotations

import os
import sys
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


from sports_scraper.models import NormalizedPlay
from sports_scraper.persistence.plays import (
    create_raw_pbp_snapshot,
    get_final_scores_from_pbp,
    upsert_plays,
)

PLAYS_PY = REPO_ROOT / "scraper" / "sports_scraper" / "persistence" / "plays.py"


def test_no_optional_pbpsnapshot_hasattr_gate() -> None:
    """PBPSnapshot lives on db_models SSOT; optional-deployment skip path was removed."""
    text = PLAYS_PY.read_text()
    assert "hasattr(db_models, 'PBPSnapshot')" not in text
    assert 'hasattr(db_models, "PBPSnapshot")' not in text


class TestUpsertPlays:
    """Tests for upsert_plays function."""

    def test_handles_empty_plays(self):
        """Handles empty plays list."""
        mock_session = MagicMock()
        result = upsert_plays(mock_session, game_id=1, plays=[])
        # Returns 0 for empty plays
        assert result == 0

    def test_function_signature(self):
        """Function accepts expected parameters."""
        # Just verify the function exists with correct signature
        import inspect
        sig = inspect.signature(upsert_plays)
        params = list(sig.parameters.keys())
        assert "session" in params
        assert "game_id" in params
        assert "plays" in params


class TestCreateRawPbpSnapshot:
    """Tests for create_raw_pbp_snapshot function."""

    def test_returns_none_for_empty_plays(self):
        """Returns None for empty plays list."""
        mock_session = MagicMock()
        result = create_raw_pbp_snapshot(mock_session, game_id=1, plays=[], source="test")
        assert result is None

    def test_function_signature(self):
        """Function accepts expected parameters."""
        import inspect
        sig = inspect.signature(create_raw_pbp_snapshot)
        params = list(sig.parameters.keys())
        assert "session" in params
        assert "game_id" in params
        assert "plays" in params
        assert "source" in params


class TestNormalizedPlayModel:
    """Tests for NormalizedPlay model used by plays module."""

    def test_normalized_play_creation(self):
        """NormalizedPlay can be created with required fields."""
        play = NormalizedPlay(
            play_index=1,
            quarter=1,
            game_clock="12:00",
            play_type="shot",
            description="Made 3-pointer",
        )
        assert play.play_index == 1
        assert play.quarter == 1

    def test_normalized_play_optional_fields(self):
        """NormalizedPlay has optional fields with defaults."""
        play = NormalizedPlay(
            play_index=1,
            quarter=1,
            game_clock="12:00",
            play_type="shot",
            description="Made 3-pointer",
        )
        assert play.team_abbreviation is None
        assert play.player_id is None
        assert play.player_name is None
        assert play.home_score is None
        assert play.away_score is None

    def test_normalized_play_with_all_fields(self):
        """NormalizedPlay can be created with all fields."""
        play = NormalizedPlay(
            play_index=1,
            quarter=1,
            game_clock="12:00",
            play_type="shot",
            team_abbreviation="BOS",
            player_id="12345",
            player_name="Jayson Tatum",
            description="Made 3-pointer",
            home_score=75,
            away_score=70,
            raw_data={"key": "value"},
        )
        assert play.team_abbreviation == "BOS"
        assert play.player_id == "12345"
        assert play.player_name == "Jayson Tatum"
        assert play.home_score == 75
        assert play.away_score == 70


class TestUpsertPlaysWithMocks:
    """Tests for upsert_plays with mocked dependencies."""

    def test_returns_zero_for_empty_plays(self):
        """Returns 0 for empty plays list."""
        mock_session = MagicMock()
        result = upsert_plays(mock_session, game_id=1, plays=[])
        assert result == 0

    def test_queries_game_when_plays_provided(self):
        """Queries for game when plays are provided."""
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = None

        play = NormalizedPlay(
            play_index=1,
            quarter=1,
            game_clock="12:00",
            play_type="shot",
            description="Test play",
        )

        # Should query for game even though it returns None
        result = upsert_plays(mock_session, game_id=1, plays=[play], create_snapshot=False)

        # Returns 0 when game not found
        assert result == 0

    def test_create_snapshot_parameter(self):
        """Respects create_snapshot parameter."""
        import inspect
        sig = inspect.signature(upsert_plays)
        params = sig.parameters
        assert "create_snapshot" in params
        assert params["create_snapshot"].default is True


class TestModuleImports:
    """Tests for plays module imports."""

    def test_has_upsert_plays(self):
        """Module has upsert_plays function."""
        from sports_scraper.persistence import plays
        assert hasattr(plays, 'upsert_plays')

    def test_has_create_raw_pbp_snapshot(self):
        """Module has create_raw_pbp_snapshot function."""
        from sports_scraper.persistence import plays
        assert hasattr(plays, 'create_raw_pbp_snapshot')


class TestUpsertPlaysParameters:
    """Tests for upsert_plays parameter handling."""

    def test_source_parameter_default(self):
        """Source parameter defaults to 'unknown'."""
        import inspect
        sig = inspect.signature(upsert_plays)
        params = sig.parameters
        assert "source" in params
        assert params["source"].default == "unknown"

    def test_scrape_run_id_parameter(self):
        """scrape_run_id parameter exists."""
        import inspect
        sig = inspect.signature(upsert_plays)
        params = sig.parameters
        assert "scrape_run_id" in params


class TestCreateRawPbpSnapshotParameters:
    """Tests for create_raw_pbp_snapshot parameter handling."""

    def test_required_parameters(self):
        """Required parameters are present."""
        import inspect
        sig = inspect.signature(create_raw_pbp_snapshot)
        params = list(sig.parameters.keys())
        assert "session" in params
        assert "game_id" in params
        assert "plays" in params
        assert "source" in params


class TestUpsertPlaysIntegration:
    """Integration tests for upsert_plays function."""

    def test_returns_zero_for_game_not_found(self):
        """Returns 0 when game is not found."""
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = None

        play = NormalizedPlay(
            play_index=1,
            quarter=1,
            game_clock="12:00",
            play_type="shot",
            description="Test play",
        )

        # Game not found should return 0
        result = upsert_plays(mock_session, game_id=999, plays=[play], create_snapshot=False)
        assert result == 0

    def test_builds_team_map_from_game(self):
        """Builds team mapping correctly from game."""
        mock_session = MagicMock()

        # Create mock teams
        mock_home_team = MagicMock()
        mock_home_team.id = 10
        mock_home_team.abbreviation = "BOS"
        mock_home_team.name = "Boston Celtics"

        mock_away_team = MagicMock()
        mock_away_team.id = 20
        mock_away_team.abbreviation = "LAL"
        mock_away_team.name = "Los Angeles Lakers"

        # Create mock game
        mock_game = MagicMock()
        mock_game.id = 1
        mock_game.league_id = 1
        mock_game.home_team = mock_home_team
        mock_game.away_team = mock_away_team
        mock_game.status = "in_progress"
        mock_game.end_time = None

        mock_session.query.return_value.filter.return_value.first.return_value = mock_game
        mock_session.query.return_value.filter.return_value.all.return_value = []

        plays = [
            NormalizedPlay(
                play_index=1,
                quarter=1,
                game_clock="12:00",
                play_type="shot",
                team_abbreviation="BOS",
                description="Shot by home team",
            ),
        ]

        result = upsert_plays(mock_session, game_id=1, plays=plays, create_snapshot=False)
        assert result == 1
        mock_session.execute.assert_called()

    def test_maps_team_by_name_when_no_abbreviation(self):
        """Maps team by name when no abbreviation."""
        mock_session = MagicMock()

        mock_home_team = MagicMock()
        mock_home_team.id = 10
        mock_home_team.abbreviation = None
        mock_home_team.name = "Duke"

        mock_away_team = MagicMock()
        mock_away_team.id = 20
        mock_away_team.abbreviation = None
        mock_away_team.name = "UNC"

        mock_game = MagicMock()
        mock_game.id = 1
        mock_game.league_id = 9
        mock_game.home_team = mock_home_team
        mock_game.away_team = mock_away_team
        mock_game.status = "in_progress"
        mock_game.end_time = None

        mock_session.query.return_value.filter.return_value.first.return_value = mock_game
        mock_session.query.return_value.filter.return_value.all.return_value = []

        plays = [
            NormalizedPlay(
                play_index=1,
                quarter=1,
                game_clock="12:00",
                play_type="shot",
                team_abbreviation="DUKE",  # Should match by name.upper()
                description="Shot",
            ),
        ]

        result = upsert_plays(mock_session, game_id=1, plays=plays, create_snapshot=False)
        assert result == 1

    def test_resolves_player_from_player_map(self):
        """Resolves player_ref_id from player map."""
        mock_session = MagicMock()

        mock_home_team = MagicMock()
        mock_home_team.id = 10
        mock_home_team.abbreviation = "BOS"
        mock_home_team.name = "Celtics"

        mock_away_team = MagicMock()
        mock_away_team.id = 20
        mock_away_team.abbreviation = "LAL"
        mock_away_team.name = "Lakers"

        mock_game = MagicMock()
        mock_game.id = 1
        mock_game.league_id = 1
        mock_game.home_team = mock_home_team
        mock_game.away_team = mock_away_team
        mock_game.status = "in_progress"
        mock_game.end_time = None

        # Mock player
        mock_player = MagicMock()
        mock_player.external_id = "player_123"
        mock_player.id = 100

        mock_session.query.return_value.filter.return_value.first.return_value = mock_game
        mock_session.query.return_value.filter.return_value.all.return_value = [mock_player]

        plays = [
            NormalizedPlay(
                play_index=1,
                quarter=1,
                game_clock="12:00",
                play_type="shot",
                team_abbreviation="BOS",
                player_id="player_123",
                description="Shot",
            ),
        ]

        result = upsert_plays(mock_session, game_id=1, plays=plays, create_snapshot=False)
        assert result == 1

    def test_updates_game_timestamps(self):
        """Updates game timestamps when plays processed."""
        mock_session = MagicMock()

        mock_home_team = MagicMock()
        mock_home_team.id = 10
        mock_home_team.abbreviation = "BOS"
        mock_home_team.name = "Celtics"

        mock_away_team = MagicMock()
        mock_away_team.id = 20
        mock_away_team.abbreviation = "LAL"
        mock_away_team.name = "Lakers"

        mock_game = MagicMock()
        mock_game.id = 1
        mock_game.league_id = 1
        mock_game.home_team = mock_home_team
        mock_game.away_team = mock_away_team
        mock_game.status = "in_progress"
        mock_game.end_time = None
        mock_game.last_pbp_at = None

        mock_session.query.return_value.filter.return_value.first.return_value = mock_game
        mock_session.query.return_value.filter.return_value.all.return_value = []

        plays = [
            NormalizedPlay(
                play_index=1,
                quarter=1,
                game_clock="12:00",
                play_type="shot",
                description="Shot",
            ),
        ]

        upsert_plays(mock_session, game_id=1, plays=plays, create_snapshot=False)

        # last_pbp_at should be updated
        assert mock_game.last_pbp_at is not None
        mock_session.flush.assert_called()

    @patch("sports_scraper.persistence.plays.create_raw_pbp_snapshot")
    def test_creates_snapshot_when_requested(self, mock_create_snapshot):
        """Creates raw pbp snapshot when requested."""
        mock_session = MagicMock()

        mock_home_team = MagicMock()
        mock_home_team.id = 10
        mock_home_team.abbreviation = "BOS"
        mock_home_team.name = "Celtics"

        mock_away_team = MagicMock()
        mock_away_team.id = 20
        mock_away_team.abbreviation = "LAL"
        mock_away_team.name = "Lakers"

        mock_game = MagicMock()
        mock_game.id = 1
        mock_game.league_id = 1
        mock_game.home_team = mock_home_team
        mock_game.away_team = mock_away_team
        mock_game.status = "in_progress"
        mock_game.end_time = None

        mock_session.query.return_value.filter.return_value.first.return_value = mock_game
        mock_session.query.return_value.filter.return_value.all.return_value = []

        plays = [
            NormalizedPlay(
                play_index=1,
                quarter=1,
                game_clock="12:00",
                play_type="shot",
                description="Shot",
            ),
        ]

        upsert_plays(mock_session, game_id=1, plays=plays, source="nba_live", create_snapshot=True)

        mock_create_snapshot.assert_called_once()


class TestCreateRawPbpSnapshotWithPlays:
    """Tests for create_raw_pbp_snapshot with actual plays."""

    @patch("sports_scraper.persistence.plays.db_models")
    def test_creates_snapshot_with_plays(self, mock_db_models):
        """Creates snapshot when plays are provided."""
        mock_session = MagicMock()
        mock_snapshot = MagicMock()
        mock_snapshot.id = 42
        mock_db_models.PBPSnapshot.return_value = mock_snapshot

        plays = [
            NormalizedPlay(
                play_index=1,
                quarter=1,
                game_clock="12:00",
                play_type="shot",
                team_abbreviation="BOS",
                player_name="Jayson Tatum",
                description="Made 3-pointer",
                home_score=3,
                away_score=0,
            ),
            NormalizedPlay(
                play_index=2,
                quarter=1,
                game_clock="11:30",
                play_type="rebound",
                team_abbreviation="LAL",
                description="Defensive rebound",
            ),
        ]

        result = create_raw_pbp_snapshot(mock_session, game_id=1, plays=plays, source="nba_live")

        assert result == 42
        mock_session.add.assert_called_once()
        mock_session.flush.assert_called_once()

    @patch("sports_scraper.persistence.plays.db_models")
    def test_computes_resolution_stats(self, mock_db_models):
        """Computes resolution stats correctly."""
        mock_session = MagicMock()
        mock_snapshot = MagicMock()
        mock_snapshot.id = 42

        # Capture the PBPSnapshot constructor call
        captured_calls = []
        def capture_snapshot(**kwargs):
            captured_calls.append(kwargs)
            return mock_snapshot
        mock_db_models.PBPSnapshot.side_effect = capture_snapshot

        plays = [
            NormalizedPlay(
                play_index=1,
                quarter=1,
                game_clock="12:00",
                play_type="shot",
                team_abbreviation="BOS",
                player_name="Player 1",
                description="Shot",
                home_score=2,
                away_score=0,
            ),
            NormalizedPlay(
                play_index=2,
                quarter=1,
                game_clock="",  # Missing clock
                play_type="foul",
                team_abbreviation=None,  # No team
                player_name=None,  # No player
                description="Foul",
            ),
        ]

        create_raw_pbp_snapshot(mock_session, game_id=1, plays=plays, source="test")

        assert len(captured_calls) == 1
        stats = captured_calls[0]["resolution_stats"]
        assert stats["total_plays"] == 2
        assert stats["teams_with_abbreviation"] == 1
        assert stats["teams_without_abbreviation"] == 1
        assert stats["players_with_name"] == 1
        assert stats["players_without_name"] == 1
        assert stats["plays_with_score"] == 1
        assert stats["plays_without_score"] == 1
        assert stats["clock_missing"] == 1

    @patch("sports_scraper.persistence.plays.db_models")
    def test_handles_exception_during_snapshot(self, mock_db_models):
        """Returns None when exception occurs during snapshot creation."""
        mock_session = MagicMock()
        mock_db_models.PBPSnapshot.side_effect = Exception("Database error")

        plays = [
            NormalizedPlay(
                play_index=1,
                quarter=1,
                game_clock="12:00",
                play_type="shot",
                description="Shot",
            ),
        ]

        result = create_raw_pbp_snapshot(mock_session, game_id=1, plays=plays, source="test")

        assert result is None


class TestGetFinalScoresFromPbp:
    """Tests for get_final_scores_from_pbp function."""

    @patch("sports_scraper.persistence.plays.db_models")
    def test_returns_scores_from_last_play(self, mock_db_models):
        """Returns (home, away) from the last play with scores."""
        mock_session = MagicMock()
        mock_row = MagicMock()
        mock_row.home_score = 64
        mock_row.away_score = 73
        (
            mock_session.query.return_value
            .filter.return_value
            .filter.return_value
            .order_by.return_value
            .first.return_value
        ) = mock_row

        result = get_final_scores_from_pbp(mock_session, game_id=1)
        assert result == (64, 73)

    @patch("sports_scraper.persistence.plays.db_models")
    def test_returns_none_when_no_plays(self, mock_db_models):
        """Returns None when no plays exist."""
        mock_session = MagicMock()
        (
            mock_session.query.return_value
            .filter.return_value
            .filter.return_value
            .order_by.return_value
            .first.return_value
        ) = None

        result = get_final_scores_from_pbp(mock_session, game_id=1)
        assert result is None

    @patch("sports_scraper.persistence.plays.db_models")
    def test_returns_none_when_home_score_is_none(self, mock_db_models):
        """Returns None when last play has None home_score."""
        mock_session = MagicMock()
        mock_row = MagicMock()
        mock_row.home_score = None
        mock_row.away_score = None
        (
            mock_session.query.return_value
            .filter.return_value
            .filter.return_value
            .order_by.return_value
            .first.return_value
        ) = mock_row

        result = get_final_scores_from_pbp(mock_session, game_id=1)
        assert result is None


class TestScoreReconciliation:
    """Tests for PBP score reconciliation in upsert_plays."""

    @patch("sports_scraper.persistence.plays.get_final_scores_from_pbp")
    def test_reconciles_when_scores_differ(self, mock_get_scores):
        """Updates game scores when PBP scores differ from game scores."""
        mock_session = MagicMock()
        mock_get_scores.return_value = (64, 73)

        mock_home_team = MagicMock()
        mock_home_team.id = 10
        mock_home_team.abbreviation = "KENN"
        mock_home_team.name = "Kennesaw St"

        mock_away_team = MagicMock()
        mock_away_team.id = 20
        mock_away_team.abbreviation = "GONZ"
        mock_away_team.name = "Gonzaga"

        mock_game = MagicMock()
        mock_game.id = 1
        mock_game.league_id = 9
        mock_game.home_team = mock_home_team
        mock_game.away_team = mock_away_team
        mock_game.home_score = 56
        mock_game.away_score = 65
        mock_game.status = "in_progress"
        mock_game.end_time = None

        mock_session.query.return_value.filter.return_value.first.return_value = mock_game
        mock_session.query.return_value.filter.return_value.all.return_value = []

        plays = [
            NormalizedPlay(
                play_index=1, quarter=1, game_clock="12:00",
                play_type="shot", description="Shot",
                home_score=64, away_score=73,
            ),
        ]

        upsert_plays(mock_session, game_id=1, plays=plays, create_snapshot=False)

        assert mock_game.home_score == 64
        assert mock_game.away_score == 73

    @patch("sports_scraper.persistence.plays.get_final_scores_from_pbp")
    def test_no_update_when_scores_match(self, mock_get_scores):
        """Does not update game scores when PBP matches."""
        mock_session = MagicMock()
        mock_get_scores.return_value = (64, 73)

        mock_home_team = MagicMock()
        mock_home_team.id = 10
        mock_home_team.abbreviation = "BOS"
        mock_home_team.name = "Celtics"

        mock_away_team = MagicMock()
        mock_away_team.id = 20
        mock_away_team.abbreviation = "LAL"
        mock_away_team.name = "Lakers"

        mock_game = MagicMock()
        mock_game.id = 1
        mock_game.league_id = 1
        mock_game.home_team = mock_home_team
        mock_game.away_team = mock_away_team
        mock_game.home_score = 64
        mock_game.away_score = 73
        mock_game.status = "in_progress"
        mock_game.end_time = None

        mock_session.query.return_value.filter.return_value.first.return_value = mock_game
        mock_session.query.return_value.filter.return_value.all.return_value = []

        plays = [
            NormalizedPlay(
                play_index=1, quarter=1, game_clock="12:00",
                play_type="shot", description="Shot",
            ),
        ]

        upsert_plays(mock_session, game_id=1, plays=plays, create_snapshot=False)

        # flush called once (for plays), not twice (no reconciliation needed)
        assert mock_session.flush.call_count == 1

    @patch("sports_scraper.persistence.plays.get_final_scores_from_pbp")
    def test_no_update_when_no_pbp_scores(self, mock_get_scores):
        """Does not update when PBP has no scores."""
        mock_session = MagicMock()
        mock_get_scores.return_value = None

        mock_home_team = MagicMock()
        mock_home_team.id = 10
        mock_home_team.abbreviation = "BOS"
        mock_home_team.name = "Celtics"

        mock_away_team = MagicMock()
        mock_away_team.id = 20
        mock_away_team.abbreviation = "LAL"
        mock_away_team.name = "Lakers"

        mock_game = MagicMock()
        mock_game.id = 1
        mock_game.league_id = 1
        mock_game.home_team = mock_home_team
        mock_game.away_team = mock_away_team
        mock_game.home_score = 56
        mock_game.away_score = 65
        mock_game.status = "in_progress"
        mock_game.end_time = None

        mock_session.query.return_value.filter.return_value.first.return_value = mock_game
        mock_session.query.return_value.filter.return_value.all.return_value = []

        plays = [
            NormalizedPlay(
                play_index=1, quarter=1, game_clock="12:00",
                play_type="shot", description="Shot",
            ),
        ]

        upsert_plays(mock_session, game_id=1, plays=plays, create_snapshot=False)

        # Scores unchanged
        assert mock_game.home_score == 56
        assert mock_game.away_score == 65


