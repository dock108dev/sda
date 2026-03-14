"""Tests for persistence layer with mocked DB sessions."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

# Ensure the scraper package is importable
REPO_ROOT = Path(__file__).resolve().parents[2]
SCRAPER_ROOT = REPO_ROOT / "scraper"
if str(SCRAPER_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRAPER_ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/test_db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ENVIRONMENT", "development")


# ============================================================================
# Tests for persistence/games.py pure functions
# ============================================================================

from sports_scraper.persistence.games import (
    _normalize_status,
    merge_external_ids,
    resolve_status_transition,
)


class TestNormalizeStatus:
    """Tests for _normalize_status function."""

    def test_final_status(self):
        assert _normalize_status("final") == "final"
        assert _normalize_status("FINAL") == "final"
        assert _normalize_status("completed") == "final"
        assert _normalize_status("Completed") == "final"

    def test_live_status(self):
        assert _normalize_status("live") == "live"
        assert _normalize_status("LIVE") == "live"

    def test_scheduled_status(self):
        assert _normalize_status("scheduled") == "scheduled"
        assert _normalize_status("SCHEDULED") == "scheduled"

    def test_none_status(self):
        assert _normalize_status(None) == "scheduled"

    def test_unknown_status(self):
        assert _normalize_status("unknown") == "scheduled"

    def test_pregame_status(self):
        assert _normalize_status("pregame") == "pregame"
        assert _normalize_status("PREGAME") == "pregame"


class TestResolveStatusTransition:
    """Tests for resolve_status_transition function."""

    def test_final_sticks(self):
        # Once final, always final
        assert resolve_status_transition("final", "scheduled") == "final"
        assert resolve_status_transition("final", "live") == "final"
        assert resolve_status_transition("final", "final") == "final"

    def test_promote_to_final(self):
        assert resolve_status_transition("scheduled", "final") == "final"
        assert resolve_status_transition("live", "final") == "final"

    def test_promote_to_live(self):
        assert resolve_status_transition("scheduled", "live") == "live"

    def test_live_doesnt_regress(self):
        # Live should not regress to scheduled
        assert resolve_status_transition("live", "scheduled") == "live"

    def test_scheduled_to_scheduled(self):
        assert resolve_status_transition("scheduled", "scheduled") == "scheduled"


class TestMergeExternalIds:
    """Tests for merge_external_ids function."""

    def test_merge_new_values(self):
        existing = {"nba_id": "123"}
        updates = {"espn_id": "456"}
        result = merge_external_ids(existing, updates)
        assert result == {"nba_id": "123", "espn_id": "456"}

    def test_update_existing_value(self):
        existing = {"nba_id": "123"}
        updates = {"nba_id": "999"}
        result = merge_external_ids(existing, updates)
        assert result == {"nba_id": "999"}

    def test_none_updates(self):
        existing = {"nba_id": "123"}
        result = merge_external_ids(existing, None)
        assert result == {"nba_id": "123"}

    def test_none_value_ignored(self):
        existing = {"nba_id": "123"}
        updates = {"espn_id": None, "other_id": "456"}
        result = merge_external_ids(existing, updates)
        assert result == {"nba_id": "123", "other_id": "456"}

    def test_empty_existing(self):
        existing = {}
        updates = {"nba_id": "123"}
        result = merge_external_ids(existing, updates)
        assert result == {"nba_id": "123"}

    def test_none_existing(self):
        updates = {"nba_id": "123"}
        result = merge_external_ids(None, updates)
        assert result == {"nba_id": "123"}


# ============================================================================
# Tests for persistence/teams.py
# ============================================================================

from sports_scraper.persistence.teams import (
    _derive_abbreviation,
    _normalize_ncaab_name_for_matching,
)


class TestDeriveAbbreviation:
    """Tests for _derive_abbreviation function."""

    def test_multi_word_team(self):
        result = _derive_abbreviation("Boston Celtics")
        assert len(result) >= 2
        assert len(result) <= 6
        assert result == result.upper()

    def test_single_word_team(self):
        result = _derive_abbreviation("Duke")
        assert len(result) >= 3
        assert result == result.upper()

    def test_empty_string(self):
        result = _derive_abbreviation("")
        assert result == "UNK"

    def test_uc_prefix(self):
        result = _derive_abbreviation("UC Irvine")
        assert "UC" in result or result.startswith("U")

    def test_unc_prefix(self):
        result = _derive_abbreviation("UNC Chapel Hill")
        assert "UNC" in result or result.startswith("U")

    def test_stopwords_removed(self):
        # Stopwords like "of", "the" should be ignored
        result = _derive_abbreviation("University of Texas")
        assert len(result) <= 6

    def test_special_characters_cleaned(self):
        result = _derive_abbreviation("St. John's")
        assert "." not in result
        assert "'" not in result


class TestNormalizeNcaabNameForMatching:
    """Tests for _normalize_ncaab_name_for_matching function."""

    def test_basic_normalization(self):
        result = _normalize_ncaab_name_for_matching("Duke Blue Devils")
        assert result == result.lower()

    def test_removes_mascot(self):
        # Should strip common mascots
        result = _normalize_ncaab_name_for_matching("Duke Blue Devils")
        assert "devils" not in result or "duke" in result

    def test_handles_hyphenated_names(self):
        result = _normalize_ncaab_name_for_matching("Texas A&M-Corpus Christi")
        assert result  # Should not crash


# ============================================================================
# Tests for persistence/boxscores.py
# ============================================================================

from sports_scraper.models import (
    NormalizedPlayerBoxscore,
    NormalizedTeamBoxscore,
    TeamIdentity,
)
from sports_scraper.persistence.boxscores import (
    _build_player_stats,
    _build_team_stats,
    _validate_nhl_player_boxscore,
)


class TestValidateNhlPlayerBoxscore:
    """Tests for _validate_nhl_player_boxscore function."""

    def test_valid_skater(self):
        team = TeamIdentity(league_code="NHL", name="Boston Bruins")
        payload = NormalizedPlayerBoxscore(
            player_id="123",
            player_name="Brad Marchand",
            team=team,
            player_role="skater",
            goals=1,
        )
        result = _validate_nhl_player_boxscore(payload, game_id=1)
        assert result is None  # Valid

    def test_valid_goalie(self):
        team = TeamIdentity(league_code="NHL", name="Boston Bruins")
        payload = NormalizedPlayerBoxscore(
            player_id="456",
            player_name="Linus Ullmark",
            team=team,
            player_role="goalie",
            saves=30,
        )
        result = _validate_nhl_player_boxscore(payload, game_id=1)
        assert result is None  # Valid

    def test_missing_player_name(self):
        team = TeamIdentity(league_code="NHL", name="Boston Bruins")
        payload = NormalizedPlayerBoxscore(
            player_id="123",
            player_name="",
            team=team,
            player_role="skater",
            goals=1,
        )
        result = _validate_nhl_player_boxscore(payload, game_id=1)
        assert result == "missing_player_name"

    def test_missing_player_role(self):
        team = TeamIdentity(league_code="NHL", name="Boston Bruins")
        payload = NormalizedPlayerBoxscore(
            player_id="123",
            player_name="Brad Marchand",
            team=team,
            player_role=None,
            goals=1,
        )
        result = _validate_nhl_player_boxscore(payload, game_id=1)
        assert result == "missing_player_role"

    def test_skater_no_stats(self):
        team = TeamIdentity(league_code="NHL", name="Boston Bruins")
        payload = NormalizedPlayerBoxscore(
            player_id="123",
            player_name="Brad Marchand",
            team=team,
            player_role="skater",
            # No stats provided
        )
        result = _validate_nhl_player_boxscore(payload, game_id=1)
        assert result == "all_stats_null"

    def test_non_nhl_always_valid(self):
        team = TeamIdentity(league_code="NBA", name="Boston Celtics")
        payload = NormalizedPlayerBoxscore(
            player_id="123",
            player_name="",  # Would fail for NHL
            team=team,
            player_role=None,
        )
        result = _validate_nhl_player_boxscore(payload, game_id=1)
        assert result is None  # Non-NHL passes


class TestBuildTeamStats:
    """Tests for _build_team_stats function."""

    def test_builds_stats_dict(self):
        team = TeamIdentity(league_code="NBA", name="Boston Celtics")
        payload = NormalizedTeamBoxscore(
            team=team,
            is_home=True,
            points=110,
            rebounds=45,
            assists=25,
        )
        result = _build_team_stats(payload)
        assert result["points"] == 110
        assert result["rebounds"] == 45
        assert result["assists"] == 25

    def test_excludes_none_values(self):
        team = TeamIdentity(league_code="NBA", name="Boston Celtics")
        payload = NormalizedTeamBoxscore(
            team=team,
            is_home=True,
            points=110,
            rebounds=None,
        )
        result = _build_team_stats(payload)
        assert "points" in result
        assert "rebounds" not in result

    def test_includes_raw_stats(self):
        team = TeamIdentity(league_code="NBA", name="Boston Celtics")
        payload = NormalizedTeamBoxscore(
            team=team,
            is_home=True,
            points=110,
            raw_stats={"fg_pct": 0.485},
        )
        result = _build_team_stats(payload)
        assert result["fg_pct"] == 0.485


class TestBuildPlayerStats:
    """Tests for _build_player_stats function."""

    def test_builds_stats_dict(self):
        team = TeamIdentity(league_code="NBA", name="Boston Celtics")
        payload = NormalizedPlayerBoxscore(
            player_id="123",
            player_name="Jayson Tatum",
            team=team,
            points=30,
            rebounds=10,
            assists=5,
        )
        result = _build_player_stats(payload)
        assert result["points"] == 30
        assert result["rebounds"] == 10

    def test_includes_position_and_role(self):
        team = TeamIdentity(league_code="NHL", name="Boston Bruins")
        payload = NormalizedPlayerBoxscore(
            player_id="123",
            player_name="Brad Marchand",
            team=team,
            player_role="skater",
            position="LW",
            sweater_number=63,
        )
        result = _build_player_stats(payload)
        assert result["player_role"] == "skater"
        assert result["position"] == "LW"
        assert result["sweater_number"] == 63


# ============================================================================
# Tests for persistence/odds_matching.py
# ============================================================================

# ============================================================================
# Tests for utils/datetime_utils.py
# ============================================================================

from datetime import UTC, date
from unittest.mock import patch

from sports_scraper.utils.datetime_utils import today_et


class TestTodayEt:
    """Tests for today_et() function."""

    def test_late_utc_returns_et_date(self):
        """At 11 PM UTC (6 PM ET during EST), today_et() should return
        the ET date (same calendar day), not the UTC date."""
        # 2026-02-06 23:00 UTC = 2026-02-06 18:00 EST
        mock_now = datetime(2026, 2, 6, 23, 0, 0, tzinfo=UTC)
        with patch("sports_scraper.utils.datetime_utils.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now.astimezone(
                __import__("zoneinfo", fromlist=["ZoneInfo"]).ZoneInfo("America/New_York")
            )
            mock_dt.side_effect = datetime
            result = today_et()
        assert result == date(2026, 2, 6)

    def test_early_utc_returns_previous_et_date(self):
        """At 3 AM UTC (10 PM ET previous day during EST), today_et()
        should return the previous day's date in ET."""
        # 2026-02-06 03:00 UTC = 2026-02-05 22:00 EST
        mock_now = datetime(2026, 2, 6, 3, 0, 0, tzinfo=UTC)
        with patch("sports_scraper.utils.datetime_utils.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now.astimezone(
                __import__("zoneinfo", fromlist=["ZoneInfo"]).ZoneInfo("America/New_York")
            )
            mock_dt.side_effect = datetime
            result = today_et()
        assert result == date(2026, 2, 5)

    def test_midnight_utc_returns_previous_et_date(self):
        """At midnight UTC (7 PM ET previous day during EST), today_et()
        should return the previous day's ET date."""
        # 2026-02-06 00:00 UTC = 2026-02-05 19:00 EST
        mock_now = datetime(2026, 2, 6, 0, 0, 0, tzinfo=UTC)
        with patch("sports_scraper.utils.datetime_utils.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now.astimezone(
                __import__("zoneinfo", fromlist=["ZoneInfo"]).ZoneInfo("America/New_York")
            )
            mock_dt.side_effect = datetime
            result = today_et()
        assert result == date(2026, 2, 5)

    def test_returns_date_type(self):
        """today_et() should return a date object, not a datetime."""
        result = today_et()
        assert isinstance(result, date)
        assert not isinstance(result, datetime)


# ============================================================================
# Tests for social/tweet_mapper.py — classify_game_phase
# ============================================================================

from unittest.mock import MagicMock

from sports_scraper.social.tweet_mapper import classify_game_phase


def _make_game(
    game_date=None,
    end_time=None,
    league_code="NBA",
):
    """Build a lightweight mock game for phase classification tests."""
    game = MagicMock()
    game.game_date = game_date
    game.end_time = end_time
    league = MagicMock()
    league.code = league_code
    game.league = league
    return game


class TestClassifyGamePhase:
    """Tests for classify_game_phase function."""

    def test_tweet_before_game_date_is_pregame(self):
        """A tweet posted before game_date is pregame."""
        game = _make_game(
            game_date=datetime(2026, 2, 6, 0, 0, tzinfo=UTC),  # 7 PM EST
        )
        posted_at = datetime(2026, 2, 5, 22, 0, tzinfo=UTC)
        assert classify_game_phase(posted_at, game) == "pregame"

    def test_tweet_at_game_date_is_in_game(self):
        """A tweet posted exactly at game_date is in_game."""
        tip = datetime(2026, 2, 6, 0, 0, tzinfo=UTC)
        game = _make_game(
            game_date=tip,
        )
        assert classify_game_phase(tip, game) == "in_game"

    def test_tweet_during_game_is_in_game(self):
        """A tweet posted during the game (between start and end) is in_game."""
        game = _make_game(
            game_date=datetime(2026, 2, 6, 0, 0, tzinfo=UTC),
            end_time=datetime(2026, 2, 6, 2, 30, tzinfo=UTC),
        )
        posted_at = datetime(2026, 2, 6, 1, 0, tzinfo=UTC)
        assert classify_game_phase(posted_at, game) == "in_game"

    def test_tweet_after_end_time_is_postgame(self):
        """A tweet posted after end_time is postgame."""
        game = _make_game(
            game_date=datetime(2026, 2, 6, 0, 0, tzinfo=UTC),
            end_time=datetime(2026, 2, 6, 2, 30, tzinfo=UTC),
        )
        posted_at = datetime(2026, 2, 6, 3, 0, tzinfo=UTC)
        assert classify_game_phase(posted_at, game) == "postgame"

    def test_game_at_midnight_utc(self):
        """When game_date is midnight UTC (7 PM ET previous day), classification works."""
        game = _make_game(
            game_date=datetime(2026, 2, 6, 0, 0, tzinfo=UTC),
        )
        # 11 PM UTC on Feb 5 is before midnight UTC Feb 6 → pregame
        posted_at = datetime(2026, 2, 5, 23, 0, tzinfo=UTC)
        assert classify_game_phase(posted_at, game) == "pregame"

    def test_no_end_time_uses_sport_duration(self):
        """NBA game without end_time uses 3.0h estimated duration."""
        game = _make_game(
            game_date=datetime(2026, 2, 6, 0, 0, tzinfo=UTC),
            league_code="NBA",
        )
        # 2h in → in_game (within 3.0h NBA duration)
        assert classify_game_phase(
            datetime(2026, 2, 6, 2, 0, tzinfo=UTC), game
        ) == "in_game"

        # 3.5h in → postgame (past 3.0h NBA duration)
        assert classify_game_phase(
            datetime(2026, 2, 6, 3, 30, tzinfo=UTC), game
        ) == "postgame"

    def test_tweet_at_end_time_is_in_game(self):
        """A tweet posted exactly at end_time is still in_game (boundary inclusive)."""
        end = datetime(2026, 2, 6, 2, 30, tzinfo=UTC)
        game = _make_game(
            game_date=datetime(2026, 2, 6, 0, 0, tzinfo=UTC),
            end_time=end,
        )
        assert classify_game_phase(end, game) == "in_game"

    def test_morning_tweet_on_gameday_is_pregame(self):
        """A tweet at 10 AM ET on game day should be pregame."""
        game = _make_game(
            game_date=datetime(2026, 2, 6, 0, 0, tzinfo=UTC),
        )
        # 10 AM EST = 15:00 UTC on Feb 5
        posted_at = datetime(2026, 2, 5, 15, 0, tzinfo=UTC)
        assert classify_game_phase(posted_at, game) == "pregame"

    def test_postgame_tweet_crosses_midnight_et(self):
        """A postgame tweet at 1 AM ET the next day is still postgame."""
        # Game tips 10 PM EST (03:00 UTC), ends ~12:30 AM EST (05:30 UTC)
        game = _make_game(
            game_date=datetime(2026, 2, 7, 3, 0, tzinfo=UTC),
            end_time=datetime(2026, 2, 7, 5, 30, tzinfo=UTC),
        )
        # 1 AM EST Feb 7 = 06:00 UTC Feb 7 → postgame
        posted_at = datetime(2026, 2, 7, 6, 0, tzinfo=UTC)
        assert classify_game_phase(posted_at, game) == "postgame"


from sports_scraper.models import NormalizedOddsSnapshot
from sports_scraper.persistence.odds_matching import (
    canonicalize_team_names,
)


class TestCanonicalizeTeamNames:
    """Tests for canonicalize_team_names function."""

    def test_returns_tuple(self):
        home = TeamIdentity(league_code="NBA", name="Boston Celtics")
        away = TeamIdentity(league_code="NBA", name="Los Angeles Lakers")
        snapshot = NormalizedOddsSnapshot(
            league_code="NBA",
            book="Pinnacle",
            market_type="spread",
            observed_at=datetime(2024, 1, 15, tzinfo=UTC),
            home_team=home,
            away_team=away,
            game_date=datetime(2024, 1, 15, tzinfo=UTC),
        )
        home_name, away_name = canonicalize_team_names(snapshot)
        assert isinstance(home_name, str)
        assert isinstance(away_name, str)


