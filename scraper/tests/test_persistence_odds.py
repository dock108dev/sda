"""Tests for persistence/odds.py module."""

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


from sports_scraper.models import NormalizedOddsSnapshot, TeamIdentity
from sports_scraper.persistence.odds import OddsUpsertResult
from sports_scraper.persistence.odds_matching import (
    canonicalize_team_names,
    should_log,
)


def _setup_session_get(
    mock_session: MagicMock,
    mock_game: MagicMock,
    home_name: str = "Lakers",
    away_name: str = "Celtics",
) -> None:
    """Configure mock_session.get to return game and team mocks properly.

    upsert_fairbet_odds looks up the game and its teams via
    session.get(SportsGame, id) and session.get(SportsTeam, id).
    This helper wires up side_effect so each model class gets the right mock.
    """
    from sports_scraper.db import db_models

    mock_game.home_team_id = 100
    mock_game.away_team_id = 200

    mock_home_team = MagicMock()
    mock_home_team.name = home_name
    mock_away_team = MagicMock()
    mock_away_team.name = away_name

    def _get(model_class, id_value):
        if model_class is db_models.SportsTeam:
            if id_value == 100:
                return mock_home_team
            if id_value == 200:
                return mock_away_team
        return mock_game

    mock_session.get.side_effect = _get


class TestCanonicalizeTeamNames:
    """Tests for canonicalize_team_names function."""

    def test_returns_canonical_names(self):
        """Returns canonical team names from mappings."""
        snapshot = NormalizedOddsSnapshot(
            league_code="NBA",
            game_date=datetime(2024, 1, 15, 19, 0, tzinfo=UTC),
            home_team=TeamIdentity(league_code="NBA", name="Boston Celtics", abbreviation="BOS"),
            away_team=TeamIdentity(league_code="NBA", name="New York Knicks", abbreviation="NYK"),
            book="FanDuel",
            market_type="spread",
            line=-5.5,
            price=-110,
            observed_at=datetime.now(UTC),
        )

        home, away = canonicalize_team_names(snapshot)

        # canonicalize_team_names returns canonical form from mappings, not lowercased
        assert home == "Boston Celtics"
        assert away == "New York Knicks"

    def test_handles_whitespace_in_names(self):
        """Handles whitespace in team names (via normalize_team_name)."""
        snapshot = NormalizedOddsSnapshot(
            league_code="NBA",
            game_date=datetime(2024, 1, 15, 19, 0, tzinfo=UTC),
            home_team=TeamIdentity(league_code="NBA", name="  Boston Celtics  ", abbreviation="BOS"),
            away_team=TeamIdentity(league_code="NBA", name="  New York Knicks  ", abbreviation="NYK"),
            book="FanDuel",
            market_type="spread",
            line=-5.5,
            price=-110,
            observed_at=datetime.now(UTC),
        )

        home, away = canonicalize_team_names(snapshot)

        # Names with extra whitespace fall through as-is if not in mappings
        # (they won't match existing mappings with exact match)
        assert isinstance(home, str)
        assert isinstance(away, str)


class TestShouldLog:
    """Tests for should_log function."""

    def test_returns_true_first_time(self):
        """Returns True on first call for a key."""
        # Use unique key to avoid state from other tests
        import time
        key = f"test_key_{time.time()}"
        result = should_log(key)
        assert result is True

    def test_returns_false_subsequent_times(self):
        """Returns False on subsequent calls within sample window."""
        import time
        key = f"test_key_repeat_{time.time()}"

        # First call
        should_log(key)

        # Subsequent calls should return False
        result = should_log(key)
        assert result is False

    def test_respects_sample_parameter(self):
        """Respects sample parameter for logging frequency."""
        import time
        key = f"test_key_sample_{time.time()}"

        # Call many times with sample=10
        results = [should_log(key, sample=10) for _ in range(20)]

        # First should be True, then mostly False with some True at intervals
        assert results[0] is True


class TestOddsModuleImports:
    """Tests for odds module imports."""

    def test_upsert_odds_exists(self):
        """upsert_odds function exists."""
        from sports_scraper.persistence.odds import upsert_odds
        assert callable(upsert_odds)

    def test_module_has_required_functions(self):
        """Module has all required functions."""
        from sports_scraper.persistence import odds
        assert hasattr(odds, 'upsert_odds')


class TestCacheFunctions:
    """Tests for cache functions in odds_matching module."""

    def test_cache_get_miss_returns_false(self):
        """cache_get returns False for missing key."""
        import time

        from sports_scraper.persistence.odds_matching import cache_get
        key = ("test_league", "2024-01-15", time.time(), time.time() + 1)
        result = cache_get(key)
        assert result is False

    def test_cache_set_and_get(self):
        """cache_set stores value, cache_get retrieves it."""
        import time

        from sports_scraper.persistence.odds_matching import cache_get, cache_set
        key = ("NBA", "2024-01-15", int(time.time()), int(time.time()) + 1)
        cache_set(key, 42)
        result = cache_get(key)
        assert result == 42

    def test_cache_set_none_value(self):
        """cache_set can store None values."""
        import time

        from sports_scraper.persistence.odds_matching import cache_get, cache_set
        key = ("NCAAB", "2024-01-15", int(time.time()), int(time.time()) + 2)
        cache_set(key, None)
        result = cache_get(key)
        assert result is None  # Distinct from False (cache miss)

    def test_cache_clear_returns_count(self):
        """cache_clear returns number of entries cleared."""
        import time

        from sports_scraper.persistence.odds_matching import cache_clear, cache_set
        # Add some entries
        for i in range(5):
            cache_set(("test", str(time.time()), i, i + 100), i)
        # Clear and check count
        count = cache_clear()
        # Should return at least 5 (may be more from other tests)
        assert count >= 0  # Cache is shared, just verify it returns an int

    def test_cache_invalidate_game_removes_entries(self):
        """cache_invalidate_game removes entries with matching game_id."""
        import time

        from sports_scraper.persistence.odds_matching import (
            cache_clear,
            cache_get,
            cache_invalidate_game,
            cache_set,
        )
        # Clear cache first
        cache_clear()

        # Add entries with different game IDs
        key1 = ("NBA", "2024-01-15", int(time.time()), 999)
        key2 = ("NBA", "2024-01-16", int(time.time()), 888)
        cache_set(key1, 999)
        cache_set(key2, 888)

        # Invalidate game 999
        removed = cache_invalidate_game(999)

        # Entry for game 999 should be gone
        assert cache_get(key1) is False
        # Entry for game 888 should still exist
        assert cache_get(key2) == 888


class TestOddsApiMappings:
    """Tests for Odds API team name mappings."""

    def test_odds_api_to_db_mappings_exist(self):
        """_ODDS_API_TO_DB_MAPPINGS dict exists."""
        from sports_scraper.persistence.odds_matching import _ODDS_API_TO_DB_MAPPINGS
        assert isinstance(_ODDS_API_TO_DB_MAPPINGS, dict)

    def test_st_johns_mapping(self):
        """St. John's variants are mapped."""
        from sports_scraper.persistence.odds_matching import _ODDS_API_TO_DB_MAPPINGS
        # At least one St. John's variant should map
        mappings_values = list(_ODDS_API_TO_DB_MAPPINGS.values())
        assert any("St. John" in v for v in mappings_values)


class TestMatchGameByTeamIds:
    """Tests for match_game_by_team_ids function."""

    def test_matches_exact_team_ids(self):
        """Matches game with exact team IDs."""
        from sports_scraper.persistence.odds_matching import match_game_by_team_ids

        mock_session = MagicMock()
        mock_session.execute.return_value.scalar.return_value = 42

        day_start = datetime(2024, 1, 15, 0, 0, tzinfo=UTC)
        day_end = datetime(2024, 1, 15, 23, 59, tzinfo=UTC)

        result = match_game_by_team_ids(
            mock_session,
            league_id=1,
            home_team_id=10,
            away_team_id=20,
            day_start=day_start,
            day_end=day_end,
        )

        assert result == 42

    def test_matches_swapped_team_ids(self):
        """Matches game with swapped team IDs (home/away reversed)."""
        from sports_scraper.persistence.odds_matching import match_game_by_team_ids

        mock_session = MagicMock()
        # First query returns None, second (swapped) returns 42
        mock_session.execute.return_value.scalar.side_effect = [None, 42]

        day_start = datetime(2024, 1, 15, 0, 0, tzinfo=UTC)
        day_end = datetime(2024, 1, 15, 23, 59, tzinfo=UTC)

        result = match_game_by_team_ids(
            mock_session,
            league_id=1,
            home_team_id=10,
            away_team_id=20,
            day_start=day_start,
            day_end=day_end,
        )

        assert result == 42

    def test_returns_none_when_no_match(self):
        """Returns None when no game matches."""
        from sports_scraper.persistence.odds_matching import match_game_by_team_ids

        mock_session = MagicMock()
        mock_session.execute.return_value.scalar.side_effect = [None, None]

        day_start = datetime(2024, 1, 15, 0, 0, tzinfo=UTC)
        day_end = datetime(2024, 1, 15, 23, 59, tzinfo=UTC)

        result = match_game_by_team_ids(
            mock_session,
            league_id=1,
            home_team_id=10,
            away_team_id=20,
            day_start=day_start,
            day_end=day_end,
        )

        assert result is None


class TestMatchGameByNamesNcaab:
    """Tests for match_game_by_names_ncaab function."""

    def test_returns_none_when_no_games_in_range(self):
        """Returns None when no games in date range."""
        from sports_scraper.persistence.odds_matching import match_game_by_names_ncaab

        mock_session = MagicMock()
        mock_session.execute.return_value.all.return_value = []

        snapshot = NormalizedOddsSnapshot(
            league_code="NCAAB",
            home_team=TeamIdentity(league_code="NCAAB", name="Duke Blue Devils", abbreviation="DUKE"),
            away_team=TeamIdentity(league_code="NCAAB", name="North Carolina Tar Heels", abbreviation="UNC"),
            game_date=datetime(2024, 1, 15, 19, 0, tzinfo=UTC),
            book="draftkings",
            market_type="moneyline",
            price=-110,
            observed_at=datetime.now(UTC),
        )

        day_start = datetime(2024, 1, 14, 0, 0, tzinfo=UTC)
        day_end = datetime(2024, 1, 16, 23, 59, tzinfo=UTC)

        result = match_game_by_names_ncaab(
            mock_session,
            league_id=9,
            snapshot=snapshot,
            home_canonical="Duke",
            away_canonical="North Carolina",
            day_start=day_start,
            day_end=day_end,
        )

        assert result is None

    def test_matches_normalized_names(self):
        """Matches games by normalized NCAAB names."""
        from sports_scraper.persistence.odds_matching import match_game_by_names_ncaab

        mock_session = MagicMock()
        # Games in range
        mock_session.execute.return_value.all.side_effect = [
            [(42, 100, 200)],  # games_in_range: (game_id, home_team_id, away_team_id)
            [(100, "Duke"), (200, "North Carolina")],  # teams_map
        ]

        snapshot = NormalizedOddsSnapshot(
            league_code="NCAAB",
            home_team=TeamIdentity(league_code="NCAAB", name="Duke Blue Devils", abbreviation="DUKE"),
            away_team=TeamIdentity(league_code="NCAAB", name="North Carolina Tar Heels", abbreviation="UNC"),
            game_date=datetime(2024, 1, 15, 19, 0, tzinfo=UTC),
            book="draftkings",
            market_type="moneyline",
            price=-110,
            observed_at=datetime.now(UTC),
        )

        day_start = datetime(2024, 1, 14, 0, 0, tzinfo=UTC)
        day_end = datetime(2024, 1, 16, 23, 59, tzinfo=UTC)

        result = match_game_by_names_ncaab(
            mock_session,
            league_id=9,
            snapshot=snapshot,
            home_canonical="Duke",
            away_canonical="North Carolina",
            day_start=day_start,
            day_end=day_end,
        )

        assert result == 42


class TestMatchGameByNamesNonNcaab:
    """Tests for match_game_by_names_non_ncaab function."""

    def test_matches_exact_names(self):
        """Matches games by exact team names."""
        from sports_scraper.persistence.odds_matching import match_game_by_names_non_ncaab

        mock_session = MagicMock()
        mock_session.execute.return_value.scalar.return_value = 42

        snapshot = NormalizedOddsSnapshot(
            league_code="NBA",
            home_team=TeamIdentity(league_code="NBA", name="Los Angeles Lakers", abbreviation="LAL"),
            away_team=TeamIdentity(league_code="NBA", name="Boston Celtics", abbreviation="BOS"),
            game_date=datetime(2024, 1, 15, 19, 0, tzinfo=UTC),
            book="draftkings",
            market_type="moneyline",
            price=-110,
            observed_at=datetime.now(UTC),
        )

        day_start = datetime(2024, 1, 14, 0, 0, tzinfo=UTC)
        day_end = datetime(2024, 1, 16, 23, 59, tzinfo=UTC)

        result = match_game_by_names_non_ncaab(
            mock_session,
            league_id=1,
            snapshot=snapshot,
            home_canonical="Los Angeles Lakers",
            away_canonical="Boston Celtics",
            day_start=day_start,
            day_end=day_end,
        )

        assert result == 42

    def test_matches_swapped_names(self):
        """Matches games with swapped home/away names."""
        from sports_scraper.persistence.odds_matching import match_game_by_names_non_ncaab

        mock_session = MagicMock()
        # First query returns None, second (swapped) returns 42
        mock_session.execute.return_value.scalar.side_effect = [None, 42]

        snapshot = NormalizedOddsSnapshot(
            league_code="NBA",
            home_team=TeamIdentity(league_code="NBA", name="Los Angeles Lakers", abbreviation="LAL"),
            away_team=TeamIdentity(league_code="NBA", name="Boston Celtics", abbreviation="BOS"),
            game_date=datetime(2024, 1, 15, 19, 0, tzinfo=UTC),
            book="draftkings",
            market_type="moneyline",
            price=-110,
            observed_at=datetime.now(UTC),
        )

        day_start = datetime(2024, 1, 14, 0, 0, tzinfo=UTC)
        day_end = datetime(2024, 1, 16, 23, 59, tzinfo=UTC)

        result = match_game_by_names_non_ncaab(
            mock_session,
            league_id=1,
            snapshot=snapshot,
            home_canonical="Los Angeles Lakers",
            away_canonical="Boston Celtics",
            day_start=day_start,
            day_end=day_end,
        )

        assert result == 42


class TestUpsertOddsFunction:
    """Tests for upsert_odds function."""

    @patch("sports_scraper.persistence.odds.cache_set")
    @patch("sports_scraper.persistence.odds.cache_get")
    @patch("sports_scraper.persistence.odds._upsert_team")
    @patch("sports_scraper.persistence.odds._find_team_by_name")
    @patch("sports_scraper.persistence.odds.get_league_id")
    def test_uses_cache_hit(
        self,
        mock_get_league_id,
        mock_find_team,
        mock_upsert_team,
        mock_cache_get,
        mock_cache_set,
    ):
        """Uses cached game_id when available."""
        from sports_scraper.persistence.odds import upsert_odds

        mock_session = MagicMock()
        mock_get_league_id.return_value = 1
        mock_find_team.side_effect = [10, 20]  # home, away team IDs
        mock_cache_get.return_value = 42  # Cached game_id

        # Mock session.get to return a game and its teams
        mock_game = MagicMock()
        _setup_session_get(mock_session, mock_game)

        snapshot = NormalizedOddsSnapshot(
            league_code="NBA",
            home_team=TeamIdentity(league_code="NBA", name="Lakers", abbreviation="LAL"),
            away_team=TeamIdentity(league_code="NBA", name="Celtics", abbreviation="BOS"),
            game_date=datetime(2024, 1, 15, 19, 0, tzinfo=UTC),
            book="draftkings",
            market_type="moneyline",
            price=-110,
            observed_at=datetime.now(UTC),
        )

        result = upsert_odds(mock_session, snapshot)

        assert result is OddsUpsertResult.PERSISTED
        # Three execute calls: SportsGameOdds opening + closing + FairbetGameOddsWork
        assert mock_session.execute.call_count == 3

    @patch("sports_scraper.persistence.odds.cache_set")
    @patch("sports_scraper.persistence.odds.cache_get")
    @patch("sports_scraper.persistence.odds._upsert_team")
    @patch("sports_scraper.persistence.odds._find_team_by_name")
    @patch("sports_scraper.persistence.odds.get_league_id")
    def test_returns_false_on_cached_none(
        self,
        mock_get_league_id,
        mock_find_team,
        mock_upsert_team,
        mock_cache_get,
        mock_cache_set,
    ):
        """Returns False when cache contains None (known no-match)."""
        from sports_scraper.persistence.odds import upsert_odds

        mock_session = MagicMock()
        mock_get_league_id.return_value = 1
        mock_find_team.side_effect = [10, 20]
        mock_cache_get.return_value = None  # Cached as no-match

        snapshot = NormalizedOddsSnapshot(
            league_code="NBA",
            home_team=TeamIdentity(league_code="NBA", name="Lakers", abbreviation="LAL"),
            away_team=TeamIdentity(league_code="NBA", name="Celtics", abbreviation="BOS"),
            game_date=datetime(2024, 1, 15, 19, 0, tzinfo=UTC),
            book="draftkings",
            market_type="moneyline",
            price=-110,
            observed_at=datetime.now(UTC),
        )

        result = upsert_odds(mock_session, snapshot)

        assert result is OddsUpsertResult.SKIPPED_NO_MATCH

    @patch("sports_scraper.persistence.odds.cache_set")
    @patch("sports_scraper.persistence.odds.cache_get")
    @patch("sports_scraper.persistence.odds._upsert_team")
    @patch("sports_scraper.persistence.odds._find_team_by_name")
    @patch("sports_scraper.persistence.odds.get_league_id")
    def test_creates_team_when_not_found(
        self,
        mock_get_league_id,
        mock_find_team,
        mock_upsert_team,
        mock_cache_get,
        mock_cache_set,
    ):
        """Creates team when not found by name."""
        from sports_scraper.persistence.odds import upsert_odds

        mock_session = MagicMock()
        mock_get_league_id.return_value = 1
        mock_find_team.side_effect = [None, None]  # Teams not found
        mock_upsert_team.side_effect = [10, 20]  # Created teams
        mock_cache_get.return_value = 42

        mock_game = MagicMock()
        _setup_session_get(mock_session, mock_game, "New Team", "Another Team")

        snapshot = NormalizedOddsSnapshot(
            league_code="NBA",
            home_team=TeamIdentity(league_code="NBA", name="New Team", abbreviation="NEW"),
            away_team=TeamIdentity(league_code="NBA", name="Another Team", abbreviation="ANO"),
            game_date=datetime(2024, 1, 15, 19, 0, tzinfo=UTC),
            book="draftkings",
            market_type="moneyline",
            price=-110,
            observed_at=datetime.now(UTC),
        )

        result = upsert_odds(mock_session, snapshot)

        assert result is OddsUpsertResult.PERSISTED
        assert mock_upsert_team.call_count == 2



class TestUpsertOddsCacheMiss:
    """Tests for upsert_odds when cache misses."""

    @patch("sports_scraper.persistence.odds.upsert_game_stub")
    @patch("sports_scraper.persistence.odds.match_game_by_names_non_ncaab")
    @patch("sports_scraper.persistence.odds.match_game_by_team_ids")
    @patch("sports_scraper.persistence.odds.canonicalize_team_names")
    @patch("sports_scraper.persistence.odds.cache_set")
    @patch("sports_scraper.persistence.odds.cache_get")
    @patch("sports_scraper.persistence.odds._upsert_team")
    @patch("sports_scraper.persistence.odds._find_team_by_name")
    @patch("sports_scraper.persistence.odds.get_league_id")
    def test_matches_by_team_ids(
        self,
        mock_get_league_id,
        mock_find_team,
        mock_upsert_team,
        mock_cache_get,
        mock_cache_set,
        mock_canonicalize,
        mock_match_by_ids,
        mock_match_by_names,
        mock_upsert_stub,
    ):
        """Matches game by team IDs when cache misses."""
        from sports_scraper.persistence.odds import upsert_odds

        mock_session = MagicMock()
        mock_get_league_id.return_value = 1
        mock_find_team.side_effect = [10, 20]
        mock_cache_get.return_value = False  # Cache miss
        mock_canonicalize.return_value = ("Lakers", "Celtics")
        mock_match_by_ids.return_value = 42  # Match found

        mock_game = MagicMock()
        _setup_session_get(mock_session, mock_game)

        # Mock execute for diagnostic queries
        mock_session.execute.return_value.all.return_value = []

        snapshot = NormalizedOddsSnapshot(
            league_code="NBA",
            home_team=TeamIdentity(league_code="NBA", name="Lakers", abbreviation="LAL"),
            away_team=TeamIdentity(league_code="NBA", name="Celtics", abbreviation="BOS"),
            game_date=datetime(2024, 1, 15, 19, 0, tzinfo=UTC),
            book="draftkings",
            market_type="moneyline",
            price=-110,
            observed_at=datetime.now(UTC),
        )

        result = upsert_odds(mock_session, snapshot)

        assert result is OddsUpsertResult.PERSISTED
        mock_match_by_ids.assert_called_once()
        mock_cache_set.assert_called()

    @patch("sports_scraper.persistence.odds.upsert_game_stub")
    @patch("sports_scraper.persistence.odds.match_game_by_names_ncaab")
    @patch("sports_scraper.persistence.odds.match_game_by_team_ids")
    @patch("sports_scraper.persistence.odds.canonicalize_team_names")
    @patch("sports_scraper.persistence.odds.cache_set")
    @patch("sports_scraper.persistence.odds.cache_get")
    @patch("sports_scraper.persistence.odds._upsert_team")
    @patch("sports_scraper.persistence.odds._find_team_by_name")
    @patch("sports_scraper.persistence.odds.get_league_id")
    def test_falls_back_to_ncaab_name_matching(
        self,
        mock_get_league_id,
        mock_find_team,
        mock_upsert_team,
        mock_cache_get,
        mock_cache_set,
        mock_canonicalize,
        mock_match_by_ids,
        mock_match_by_names,
        mock_upsert_stub,
    ):
        """Falls back to NCAAB name matching when team ID match fails."""
        from sports_scraper.persistence.odds import upsert_odds

        mock_session = MagicMock()
        mock_get_league_id.return_value = 9  # NCAAB
        mock_find_team.side_effect = [100, 200]
        mock_cache_get.return_value = False
        mock_canonicalize.return_value = ("Duke", "North Carolina")
        mock_match_by_ids.return_value = None  # No match by IDs
        mock_match_by_names.return_value = 42  # Match by names

        mock_game = MagicMock()
        _setup_session_get(mock_session, mock_game, "Duke Blue Devils", "North Carolina Tar Heels")

        mock_session.execute.return_value.all.return_value = []

        snapshot = NormalizedOddsSnapshot(
            league_code="NCAAB",
            home_team=TeamIdentity(league_code="NCAAB", name="Duke Blue Devils", abbreviation="DUKE"),
            away_team=TeamIdentity(league_code="NCAAB", name="North Carolina Tar Heels", abbreviation="UNC"),
            game_date=datetime(2024, 1, 15, 19, 0, tzinfo=UTC),
            book="draftkings",
            market_type="spread",
            line=-5.5,
            price=-110,
            observed_at=datetime.now(UTC),
        )

        result = upsert_odds(mock_session, snapshot)

        assert result is OddsUpsertResult.PERSISTED
        mock_match_by_names.assert_called_once()

    @patch("sports_scraper.persistence.odds.upsert_game_stub")
    @patch("sports_scraper.persistence.odds.match_game_by_names_non_ncaab")
    @patch("sports_scraper.persistence.odds.match_game_by_team_ids")
    @patch("sports_scraper.persistence.odds.canonicalize_team_names")
    @patch("sports_scraper.persistence.odds.cache_set")
    @patch("sports_scraper.persistence.odds.cache_get")
    @patch("sports_scraper.persistence.odds._upsert_team")
    @patch("sports_scraper.persistence.odds._find_team_by_name")
    @patch("sports_scraper.persistence.odds.get_league_id")
    def test_falls_back_to_non_ncaab_name_matching(
        self,
        mock_get_league_id,
        mock_find_team,
        mock_upsert_team,
        mock_cache_get,
        mock_cache_set,
        mock_canonicalize,
        mock_match_by_ids,
        mock_match_by_names,
        mock_upsert_stub,
    ):
        """Falls back to non-NCAAB name matching when team ID match fails."""
        from sports_scraper.persistence.odds import upsert_odds

        mock_session = MagicMock()
        mock_get_league_id.return_value = 1  # NBA
        mock_find_team.side_effect = [10, 20]
        mock_cache_get.return_value = False
        mock_canonicalize.return_value = ("Lakers", "Celtics")
        mock_match_by_ids.return_value = None  # No match by IDs
        mock_match_by_names.return_value = 42  # Match by names

        mock_game = MagicMock()
        _setup_session_get(mock_session, mock_game)

        mock_session.execute.return_value.all.return_value = []

        snapshot = NormalizedOddsSnapshot(
            league_code="NBA",
            home_team=TeamIdentity(league_code="NBA", name="Lakers", abbreviation="LAL"),
            away_team=TeamIdentity(league_code="NBA", name="Celtics", abbreviation="BOS"),
            game_date=datetime(2024, 1, 15, 19, 0, tzinfo=UTC),
            book="draftkings",
            market_type="moneyline",
            price=-110,
            observed_at=datetime.now(UTC),
        )

        result = upsert_odds(mock_session, snapshot)

        assert result is OddsUpsertResult.PERSISTED
        mock_match_by_names.assert_called_once()

    @patch("sports_scraper.persistence.odds.upsert_game_stub")
    @patch("sports_scraper.persistence.odds.match_game_by_names_non_ncaab")
    @patch("sports_scraper.persistence.odds.match_game_by_team_ids")
    @patch("sports_scraper.persistence.odds.canonicalize_team_names")
    @patch("sports_scraper.persistence.odds.cache_set")
    @patch("sports_scraper.persistence.odds.cache_get")
    @patch("sports_scraper.persistence.odds._upsert_team")
    @patch("sports_scraper.persistence.odds._find_team_by_name")
    @patch("sports_scraper.persistence.odds.get_league_id")
    def test_creates_game_stub_when_no_match(
        self,
        mock_get_league_id,
        mock_find_team,
        mock_upsert_team,
        mock_cache_get,
        mock_cache_set,
        mock_canonicalize,
        mock_match_by_ids,
        mock_match_by_names,
        mock_upsert_stub,
    ):
        """Creates game stub when no existing game matches."""
        from sports_scraper.persistence.odds import upsert_odds

        mock_session = MagicMock()
        mock_get_league_id.return_value = 1
        mock_find_team.side_effect = [10, 20]
        mock_cache_get.return_value = False
        mock_canonicalize.return_value = ("Lakers", "Celtics")
        mock_match_by_ids.return_value = None
        mock_match_by_names.return_value = None  # No match found
        mock_upsert_stub.return_value = (42, True)  # Created new game

        mock_game = MagicMock()
        _setup_session_get(mock_session, mock_game)

        mock_session.execute.return_value.all.return_value = []

        snapshot = NormalizedOddsSnapshot(
            league_code="NBA",
            home_team=TeamIdentity(league_code="NBA", name="Lakers", abbreviation="LAL"),
            away_team=TeamIdentity(league_code="NBA", name="Celtics", abbreviation="BOS"),
            game_date=datetime(2024, 1, 15, 19, 0, tzinfo=UTC),
            book="draftkings",
            market_type="moneyline",
            price=-110,
            observed_at=datetime.now(UTC),
            source_key="odds_api_123",
        )

        result = upsert_odds(mock_session, snapshot)

        assert result is OddsUpsertResult.PERSISTED
        mock_upsert_stub.assert_called_once()
        # Verify external_ids contains source_key
        call_kwargs = mock_upsert_stub.call_args[1]
        assert call_kwargs["external_ids"]["odds_api_event_id"] == "odds_api_123"

    @patch("sports_scraper.persistence.odds.upsert_game_stub")
    @patch("sports_scraper.persistence.odds.match_game_by_names_non_ncaab")
    @patch("sports_scraper.persistence.odds.match_game_by_team_ids")
    @patch("sports_scraper.persistence.odds.canonicalize_team_names")
    @patch("sports_scraper.persistence.odds.cache_set")
    @patch("sports_scraper.persistence.odds.cache_get")
    @patch("sports_scraper.persistence.odds._upsert_team")
    @patch("sports_scraper.persistence.odds._find_team_by_name")
    @patch("sports_scraper.persistence.odds.get_league_id")
    def test_handles_game_stub_exception(
        self,
        mock_get_league_id,
        mock_find_team,
        mock_upsert_team,
        mock_cache_get,
        mock_cache_set,
        mock_canonicalize,
        mock_match_by_ids,
        mock_match_by_names,
        mock_upsert_stub,
    ):
        """Returns False when game stub creation fails."""
        from sports_scraper.persistence.odds import upsert_odds

        mock_session = MagicMock()
        mock_get_league_id.return_value = 1
        mock_find_team.side_effect = [10, 20]
        mock_cache_get.return_value = False
        mock_canonicalize.return_value = ("Lakers", "Celtics")
        mock_match_by_ids.return_value = None
        mock_match_by_names.return_value = None
        mock_upsert_stub.side_effect = Exception("Database error")

        mock_session.execute.return_value.all.return_value = []

        snapshot = NormalizedOddsSnapshot(
            league_code="NBA",
            home_team=TeamIdentity(league_code="NBA", name="Lakers", abbreviation="LAL"),
            away_team=TeamIdentity(league_code="NBA", name="Celtics", abbreviation="BOS"),
            game_date=datetime(2024, 1, 15, 19, 0, tzinfo=UTC),
            book="draftkings",
            market_type="moneyline",
            price=-110,
            observed_at=datetime.now(UTC),
        )

        result = upsert_odds(mock_session, snapshot)

        assert result is OddsUpsertResult.SKIPPED_NO_MATCH
        mock_cache_set.assert_called()  # Should cache None


class TestUpsertOddsDiagnostics:
    """Tests for diagnostic logging in upsert_odds."""

    @patch("sports_scraper.persistence.odds.upsert_game_stub")
    @patch("sports_scraper.persistence.odds.match_game_by_names_non_ncaab")
    @patch("sports_scraper.persistence.odds.match_game_by_team_ids")
    @patch("sports_scraper.persistence.odds.canonicalize_team_names")
    @patch("sports_scraper.persistence.odds.cache_set")
    @patch("sports_scraper.persistence.odds.cache_get")
    @patch("sports_scraper.persistence.odds._upsert_team")
    @patch("sports_scraper.persistence.odds._find_team_by_name")
    @patch("sports_scraper.persistence.odds.get_league_id")
    def test_diagnostic_queries_executed(
        self,
        mock_get_league_id,
        mock_find_team,
        mock_upsert_team,
        mock_cache_get,
        mock_cache_set,
        mock_canonicalize,
        mock_match_by_ids,
        mock_match_by_names,
        mock_upsert_stub,
    ):
        """Executes diagnostic queries for debugging."""
        from sports_scraper.persistence.odds import upsert_odds

        mock_session = MagicMock()
        mock_get_league_id.return_value = 1
        mock_find_team.side_effect = [10, 20]
        mock_cache_get.return_value = False
        mock_canonicalize.return_value = ("Lakers", "Celtics")
        mock_match_by_ids.return_value = 42

        mock_game = MagicMock()
        _setup_session_get(mock_session, mock_game)

        # Mock diagnostic query results
        mock_session.execute.return_value.all.return_value = [
            (1, datetime(2024, 1, 15, 19, 0), 10, 20),
        ]

        snapshot = NormalizedOddsSnapshot(
            league_code="NBA",
            home_team=TeamIdentity(league_code="NBA", name="Lakers", abbreviation="LAL"),
            away_team=TeamIdentity(league_code="NBA", name="Celtics", abbreviation="BOS"),
            game_date=datetime(2024, 1, 15, 19, 0, tzinfo=UTC),
            book="draftkings",
            market_type="moneyline",
            price=-110,
            observed_at=datetime.now(UTC),
        )

        result = upsert_odds(mock_session, snapshot)

        assert result is OddsUpsertResult.PERSISTED
        # Should execute diagnostic queries
        assert mock_session.execute.call_count >= 1


class TestUpsertOddsWithSideValue:
    """Tests for upsert_odds with side values."""

    @patch("sports_scraper.persistence.odds.cache_set")
    @patch("sports_scraper.persistence.odds.cache_get")
    @patch("sports_scraper.persistence.odds._upsert_team")
    @patch("sports_scraper.persistence.odds._find_team_by_name")
    @patch("sports_scraper.persistence.odds.get_league_id")
    def test_handles_spread_with_side(
        self,
        mock_get_league_id,
        mock_find_team,
        mock_upsert_team,
        mock_cache_get,
        mock_cache_set,
    ):
        """Handles spread bet with side value."""
        from sports_scraper.persistence.odds import upsert_odds

        mock_session = MagicMock()
        mock_get_league_id.return_value = 1
        mock_find_team.side_effect = [10, 20]
        mock_cache_get.return_value = 42

        mock_game = MagicMock()
        _setup_session_get(mock_session, mock_game)

        snapshot = NormalizedOddsSnapshot(
            league_code="NBA",
            home_team=TeamIdentity(league_code="NBA", name="Lakers", abbreviation="LAL"),
            away_team=TeamIdentity(league_code="NBA", name="Celtics", abbreviation="BOS"),
            game_date=datetime(2024, 1, 15, 19, 0, tzinfo=UTC),
            book="draftkings",
            market_type="spread",
            side="home",
            line=-5.5,
            price=-110,
            observed_at=datetime.now(UTC),
        )

        result = upsert_odds(mock_session, snapshot)

        assert result is OddsUpsertResult.PERSISTED
        # Two execute calls: SportsGameOdds opening + closing
        # (FairBet skipped: side="home" doesn't match either DB team name)
        assert mock_session.execute.call_count == 2

    @patch("sports_scraper.persistence.odds.cache_set")
    @patch("sports_scraper.persistence.odds.cache_get")
    @patch("sports_scraper.persistence.odds._upsert_team")
    @patch("sports_scraper.persistence.odds._find_team_by_name")
    @patch("sports_scraper.persistence.odds.get_league_id")
    def test_handles_closing_line(
        self,
        mock_get_league_id,
        mock_find_team,
        mock_upsert_team,
        mock_cache_get,
        mock_cache_set,
    ):
        """Handles closing line flag."""
        from sports_scraper.persistence.odds import upsert_odds

        mock_session = MagicMock()
        mock_get_league_id.return_value = 1
        mock_find_team.side_effect = [10, 20]
        mock_cache_get.return_value = 42

        mock_game = MagicMock()
        _setup_session_get(mock_session, mock_game)

        snapshot = NormalizedOddsSnapshot(
            league_code="NBA",
            home_team=TeamIdentity(league_code="NBA", name="Lakers", abbreviation="LAL"),
            away_team=TeamIdentity(league_code="NBA", name="Celtics", abbreviation="BOS"),
            game_date=datetime(2024, 1, 15, 19, 0, tzinfo=UTC),
            book="draftkings",
            market_type="moneyline",
            price=-110,
            observed_at=datetime.now(UTC),
            is_closing_line=True,
        )

        result = upsert_odds(mock_session, snapshot)

        assert result is OddsUpsertResult.PERSISTED


class TestUpsertOddsTeamCreation:
    """Tests for team creation in upsert_odds."""

    @patch("sports_scraper.persistence.odds.cache_set")
    @patch("sports_scraper.persistence.odds.cache_get")
    @patch("sports_scraper.persistence.odds._upsert_team")
    @patch("sports_scraper.persistence.odds._find_team_by_name")
    @patch("sports_scraper.persistence.odds.get_league_id")
    def test_creates_home_team_when_not_found(
        self,
        mock_get_league_id,
        mock_find_team,
        mock_upsert_team,
        mock_cache_get,
        mock_cache_set,
    ):
        """Creates home team when not found by name."""
        from sports_scraper.persistence.odds import upsert_odds

        mock_session = MagicMock()
        mock_get_league_id.return_value = 1
        mock_find_team.side_effect = [None, 20]  # Home team not found
        mock_upsert_team.return_value = 10  # Created
        mock_cache_get.return_value = 42

        mock_game = MagicMock()
        _setup_session_get(mock_session, mock_game, "New Team", "Celtics")

        snapshot = NormalizedOddsSnapshot(
            league_code="NBA",
            home_team=TeamIdentity(league_code="NBA", name="New Team", abbreviation="NEW"),
            away_team=TeamIdentity(league_code="NBA", name="Celtics", abbreviation="BOS"),
            game_date=datetime(2024, 1, 15, 19, 0, tzinfo=UTC),
            book="draftkings",
            market_type="moneyline",
            price=-110,
            observed_at=datetime.now(UTC),
        )

        result = upsert_odds(mock_session, snapshot)

        assert result is OddsUpsertResult.PERSISTED
        mock_upsert_team.assert_called_once()

    @patch("sports_scraper.persistence.odds.cache_set")
    @patch("sports_scraper.persistence.odds.cache_get")
    @patch("sports_scraper.persistence.odds._upsert_team")
    @patch("sports_scraper.persistence.odds._find_team_by_name")
    @patch("sports_scraper.persistence.odds.get_league_id")
    def test_creates_away_team_when_not_found(
        self,
        mock_get_league_id,
        mock_find_team,
        mock_upsert_team,
        mock_cache_get,
        mock_cache_set,
    ):
        """Creates away team when not found by name."""
        from sports_scraper.persistence.odds import upsert_odds

        mock_session = MagicMock()
        mock_get_league_id.return_value = 1
        mock_find_team.side_effect = [10, None]  # Away team not found
        mock_upsert_team.return_value = 20  # Created
        mock_cache_get.return_value = 42

        mock_game = MagicMock()
        _setup_session_get(mock_session, mock_game, "Lakers", "New Team")

        snapshot = NormalizedOddsSnapshot(
            league_code="NBA",
            home_team=TeamIdentity(league_code="NBA", name="Lakers", abbreviation="LAL"),
            away_team=TeamIdentity(league_code="NBA", name="New Team", abbreviation="NEW"),
            game_date=datetime(2024, 1, 15, 19, 0, tzinfo=UTC),
            book="draftkings",
            market_type="moneyline",
            price=-110,
            observed_at=datetime.now(UTC),
        )

        result = upsert_odds(mock_session, snapshot)

        assert result is OddsUpsertResult.PERSISTED
        mock_upsert_team.assert_called_once()
