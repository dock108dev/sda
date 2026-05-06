"""Comprehensive tests for live feed helper modules."""

from __future__ import annotations

import os
import sys
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta
from pathlib import Path

import pytest

# Ensure the scraper package is importable
REPO_ROOT = Path(__file__).resolve().parents[2]
SCRAPER_ROOT = REPO_ROOT / "scraper"
if str(SCRAPER_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRAPER_ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/test_db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ENVIRONMENT", "development")


# ============================================================================
# Tests for live/ncaab_helpers.py
# ============================================================================

from sports_scraper.live.ncaab_helpers import (
    build_team_identity,
    extract_points,
    parse_minutes,
)


class TestBuildTeamIdentity:
    """Tests for build_team_identity function."""

    def test_build_team_identity_basic(self):
        result = build_team_identity("Duke", 1234)
        assert result.league_code == "NCAAB"
        assert result.name == "Duke Blue Devils"
        assert result.short_name == "Duke Blue Devils"
        assert result.abbreviation == "DUKE"
        assert result.external_ref == "1234"

    def test_build_team_identity_long_name(self):
        result = build_team_identity("North Carolina Tar Heels", 5678)
        assert result.name == "North Carolina Tar Heels"
        assert result.abbreviation == "UNC"
        assert result.external_ref == "5678"

    def test_build_team_identity_normalizes_short_name(self):
        result = build_team_identity("Kentucky", 9999)
        assert result.name == "Kentucky Wildcats"
        assert result.abbreviation == "UK"


class TestExtractPoints:
    """Tests for extract_points function."""

    def test_extract_points_from_int(self):
        assert extract_points(89) == 89
        assert extract_points(0) == 0

    def test_extract_points_from_dict(self):
        value = {"total": 89, "byPeriod": [45, 44], "offTurnovers": 17}
        assert extract_points(value) == 89

    def test_extract_points_from_dict_without_total(self):
        value = {"byPeriod": [45, 44]}
        assert extract_points(value) == 0

    def test_extract_points_from_none(self):
        assert extract_points(None) == 0

    def test_extract_points_from_string_int(self):
        # parse_int can handle string ints
        assert extract_points({"total": "72"}) == 72


class TestParseMinutes:
    """Tests for parse_minutes function."""

    def test_parse_minutes_from_mmss(self):
        result = parse_minutes("32:45")
        assert result == pytest.approx(32.75, rel=0.01)

    def test_parse_minutes_from_int(self):
        assert parse_minutes(32) == 32.0

    def test_parse_minutes_from_float(self):
        assert parse_minutes(32.5) == 32.5

    def test_parse_minutes_from_string_number(self):
        assert parse_minutes("32") == 32.0

    def test_parse_minutes_from_none(self):
        assert parse_minutes(None) is None

    def test_parse_minutes_invalid_string(self):
        assert parse_minutes("invalid") is None

    def test_parse_minutes_edge_case_zero(self):
        result = parse_minutes("0:00")
        assert result == 0.0


# ============================================================================
# Tests for live/nhl_helpers.py
# ============================================================================

from sports_scraper.live.nhl_helpers import (
    build_team_identity_from_api,
    map_nhl_game_state,
    one_day,
    parse_datetime,
    parse_save_shots,
    parse_toi_to_minutes,
)


class TestParseTOIToMinutes:
    """Tests for parse_toi_to_minutes function."""

    def test_parse_toi_basic(self):
        result = parse_toi_to_minutes("12:34")
        expected = 12 + 34/60
        assert result == pytest.approx(expected, rel=0.01)

    def test_parse_toi_zero_seconds(self):
        result = parse_toi_to_minutes("15:00")
        assert result == 15.0

    def test_parse_toi_empty_string(self):
        assert parse_toi_to_minutes("") is None

    def test_parse_toi_none(self):
        assert parse_toi_to_minutes(None) is None

    def test_parse_toi_invalid_format(self):
        assert parse_toi_to_minutes("invalid") is None

    def test_parse_toi_single_digit_minutes(self):
        result = parse_toi_to_minutes("5:30")
        assert result == pytest.approx(5.5, rel=0.01)


class TestParseSaveShots:
    """Tests for parse_save_shots function."""

    def test_parse_save_shots_basic(self):
        saves, shots = parse_save_shots("25/27")
        assert saves == 25
        assert shots == 27

    def test_parse_save_shots_empty(self):
        saves, shots = parse_save_shots("")
        assert saves is None
        assert shots is None

    def test_parse_save_shots_none(self):
        saves, shots = parse_save_shots(None)
        assert saves is None
        assert shots is None

    def test_parse_save_shots_invalid(self):
        saves, shots = parse_save_shots("invalid")
        assert saves is None
        assert shots is None

    def test_parse_save_shots_perfect_game(self):
        saves, shots = parse_save_shots("30/30")
        assert saves == 30
        assert shots == 30


class TestBuildTeamIdentityFromAPI:
    """Tests for build_team_identity_from_api function."""

    def test_build_team_identity_full_data(self):
        team_data = {
            "abbrev": "TBL",
            "commonName": {"default": "Lightning"},
            "placeName": {"default": "Tampa Bay"},
        }
        result = build_team_identity_from_api(team_data)
        assert result.league_code == "NHL"
        assert "Lightning" in result.name or "Tampa Bay" in result.name
        assert result.external_ref == "TBL"

    def test_build_team_identity_minimal_data(self):
        team_data = {"abbrev": "BOS"}
        result = build_team_identity_from_api(team_data)
        assert result.league_code == "NHL"
        assert result.external_ref == "BOS"

    def test_build_team_identity_empty_data(self):
        team_data = {}
        result = build_team_identity_from_api(team_data)
        assert result.league_code == "NHL"
        assert result.external_ref == ""


class TestMapNHLGameState:
    """Tests for map_nhl_game_state function."""

    def test_final_states(self):
        assert map_nhl_game_state("OFF") == "final"
        assert map_nhl_game_state("FINAL") == "final"

    def test_live_states(self):
        assert map_nhl_game_state("LIVE") == "live"
        assert map_nhl_game_state("CRIT") == "live"

    def test_scheduled_states(self):
        assert map_nhl_game_state("FUT") == "scheduled"
        assert map_nhl_game_state("PRE") == "scheduled"

    def test_unknown_defaults_to_scheduled(self):
        assert map_nhl_game_state("UNKNOWN") == "scheduled"
        assert map_nhl_game_state("") == "scheduled"
        assert map_nhl_game_state("OTHER") == "scheduled"

    def test_schedule_state_postponed(self):
        assert map_nhl_game_state("FUT", "PPD") == "postponed"
        assert map_nhl_game_state("PRE", "PPD") == "postponed"
        assert map_nhl_game_state("FUT", "SUSP") == "postponed"
        assert map_nhl_game_state("FUT", "ppd") == "postponed"

    def test_schedule_state_cancelled(self):
        assert map_nhl_game_state("FUT", "CNCL") == "cancelled"
        assert map_nhl_game_state("PRE", "CNCL") == "cancelled"

    def test_schedule_state_ok_does_not_override(self):
        assert map_nhl_game_state("FUT", "OK") == "scheduled"
        assert map_nhl_game_state("PRE", "TBD") == "scheduled"

    def test_played_game_state_wins_over_schedule_state(self):
        # A finished game should stay final even if schedule_state is stale.
        assert map_nhl_game_state("OFF", "PPD") == "final"
        assert map_nhl_game_state("LIVE", "PPD") == "live"


class TestParseDateTime:
    """Tests for parse_datetime function."""

    def test_parse_datetime_iso_format(self):
        result = parse_datetime("2024-01-15T19:00:00Z")
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15
        assert result.tzinfo is not None

    def test_parse_datetime_with_offset(self):
        result = parse_datetime("2024-01-15T19:00:00+00:00")
        assert result.year == 2024

    def test_parse_datetime_empty_returns_now(self):
        result = parse_datetime("")
        assert isinstance(result, datetime)
        assert result.tzinfo is not None

    def test_parse_datetime_none_returns_now(self):
        result = parse_datetime(None)
        assert isinstance(result, datetime)
        assert result.tzinfo is not None

    def test_parse_datetime_invalid_returns_now(self):
        result = parse_datetime("not a date")
        assert isinstance(result, datetime)


class TestOneDay:
    """Tests for one_day function."""

    def test_one_day_returns_timedelta(self):
        result = one_day()
        assert isinstance(result, timedelta)
        assert result.days == 1


# ============================================================================
# Tests for live/ncaab_models.py
# ============================================================================

from sports_scraper.live.ncaab_models import NCAABBoxscore, NCAABLiveGame
from sports_scraper.models import TeamIdentity


class TestNCAABLiveGame:
    """Tests for NCAABLiveGame dataclass."""

    def test_create_game(self):
        game = NCAABLiveGame(
            game_id=12345,
            game_date=datetime(2024, 1, 15, 19, 0),
            status="final",
            season=2024,
            home_team_id=1,
            home_team_name="Duke",
            away_team_id=2,
            away_team_name="UNC",
            home_score=75,
            away_score=70,
            neutral_site=False,
        )
        assert game.game_id == 12345
        assert game.status == "final"
        assert game.home_team_name == "Duke"
        assert game.home_score == 75

    def test_game_is_frozen(self):
        game = NCAABLiveGame(
            game_id=12345,
            game_date=datetime(2024, 1, 15),
            status="final",
            season=2024,
            home_team_id=1,
            home_team_name="Duke",
            away_team_id=2,
            away_team_name="UNC",
            home_score=75,
            away_score=70,
            neutral_site=False,
        )
        with pytest.raises(FrozenInstanceError):
            game.home_score = 80


class TestNCAABBoxscore:
    """Tests for NCAABBoxscore dataclass."""

    def test_create_boxscore(self):
        home_team = TeamIdentity(
            league_code="NCAAB",
            name="Duke",
            short_name="Duke",
            abbreviation=None,
            external_ref="1",
        )
        away_team = TeamIdentity(
            league_code="NCAAB",
            name="UNC",
            short_name="UNC",
            abbreviation=None,
            external_ref="2",
        )
        boxscore = NCAABBoxscore(
            game_id=12345,
            game_date=datetime(2024, 1, 15, 19, 0),
            status="final",
            season=2024,
            home_team=home_team,
            away_team=away_team,
            home_score=75,
            away_score=70,
            team_boxscores=[],
            player_boxscores=[],
        )
        assert boxscore.game_id == 12345
        assert boxscore.home_team.name == "Duke"
        assert boxscore.away_score == 70


# ============================================================================
# Tests for live/nhl_models.py
# ============================================================================

from sports_scraper.live.nhl_models import NHLBoxscore, NHLLiveGame


class TestNHLLiveGame:
    """Tests for NHLLiveGame dataclass."""

    def test_create_game(self):
        home_team = TeamIdentity(
            league_code="NHL",
            name="Tampa Bay Lightning",
            short_name="Lightning",
            abbreviation="TBL",
            external_ref="TBL",
        )
        away_team = TeamIdentity(
            league_code="NHL",
            name="Boston Bruins",
            short_name="Bruins",
            abbreviation="BOS",
            external_ref="BOS",
        )
        game = NHLLiveGame(
            game_id=2025020001,
            game_date=datetime(2024, 10, 15, 19, 0),
            status="final",
            status_text="Final",
            home_team=home_team,
            away_team=away_team,
            home_score=4,
            away_score=3,
        )
        assert game.game_id == 2025020001
        assert game.status == "final"
        assert game.home_team.abbreviation == "TBL"

    def test_game_is_frozen(self):
        home_team = TeamIdentity(
            league_code="NHL", name="TBL", short_name="TBL",
            abbreviation="TBL", external_ref="TBL"
        )
        away_team = TeamIdentity(
            league_code="NHL", name="BOS", short_name="BOS",
            abbreviation="BOS", external_ref="BOS"
        )
        game = NHLLiveGame(
            game_id=2025020001,
            game_date=datetime(2024, 10, 15),
            status="final",
            status_text=None,
            home_team=home_team,
            away_team=away_team,
            home_score=4,
            away_score=3,
        )
        with pytest.raises(FrozenInstanceError):
            game.home_score = 5


class TestNHLBoxscore:
    """Tests for NHLBoxscore dataclass."""

    def test_create_boxscore(self):
        home_team = TeamIdentity(
            league_code="NHL", name="TBL", short_name="TBL",
            abbreviation="TBL", external_ref="TBL"
        )
        away_team = TeamIdentity(
            league_code="NHL", name="BOS", short_name="BOS",
            abbreviation="BOS", external_ref="BOS"
        )
        boxscore = NHLBoxscore(
            game_id=2025020001,
            game_date=datetime(2024, 10, 15, 19, 0),
            status="final",
            home_team=home_team,
            away_team=away_team,
            home_score=4,
            away_score=3,
            team_boxscores=[],
            player_boxscores=[],
        )
        assert boxscore.game_id == 2025020001
        assert boxscore.home_score == 4
        assert boxscore.status == "final"
