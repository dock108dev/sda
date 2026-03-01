"""Tests for config_sports.py module."""

from __future__ import annotations

import os
import sys
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


from sports_scraper.config_sports import (
    LEAGUE_CONFIG,
    LeagueConfig,
    get_enabled_leagues,
    get_league_config,
    get_scheduled_leagues,
    get_social_enabled_leagues,
    get_timeline_enabled_leagues,
    is_social_enabled,
    is_timeline_enabled,
    validate_league_code,
)


class TestLeagueConfig:
    """Tests for LeagueConfig dataclass."""

    def test_create_config(self):
        """Can create a LeagueConfig with required fields."""
        config = LeagueConfig(code="TEST", display_name="Test League")
        assert config.code == "TEST"
        assert config.display_name == "Test League"

    def test_default_flags_enabled(self):
        """Default feature flags are True."""
        config = LeagueConfig(code="TEST", display_name="Test League")
        assert config.boxscores_enabled is True
        assert config.odds_enabled is True
        assert config.social_enabled is True
        assert config.pbp_enabled is True
        assert config.timeline_enabled is True
        assert config.scheduled_ingestion is True

    def test_config_is_frozen(self):
        """Config is immutable."""
        config = LeagueConfig(code="TEST", display_name="Test League")
        with pytest.raises(Exception):  # FrozenInstanceError
            config.code = "CHANGED"

    def test_override_flags(self):
        """Can override feature flags."""
        config = LeagueConfig(
            code="TEST",
            display_name="Test League",
            social_enabled=False,
            pbp_enabled=False,
        )
        assert config.social_enabled is False
        assert config.pbp_enabled is False


class TestLeagueConfigConstants:
    """Tests for LEAGUE_CONFIG constant."""

    def test_contains_nba(self):
        """Contains NBA configuration."""
        assert "NBA" in LEAGUE_CONFIG
        assert LEAGUE_CONFIG["NBA"].code == "NBA"

    def test_contains_nhl(self):
        """Contains NHL configuration."""
        assert "NHL" in LEAGUE_CONFIG
        assert LEAGUE_CONFIG["NHL"].code == "NHL"

    def test_contains_ncaab(self):
        """Contains NCAAB configuration."""
        assert "NCAAB" in LEAGUE_CONFIG
        assert LEAGUE_CONFIG["NCAAB"].code == "NCAAB"

    def test_ncaab_social_enabled(self):
        """NCAAB has social integration enabled."""
        assert LEAGUE_CONFIG["NCAAB"].social_enabled is True

    def test_contains_mlb(self):
        """Contains MLB configuration."""
        assert "MLB" in LEAGUE_CONFIG
        assert LEAGUE_CONFIG["MLB"].code == "MLB"

    def test_mlb_boxscores_disabled(self):
        """MLB has boxscores disabled (odds-only for now)."""
        assert LEAGUE_CONFIG["MLB"].boxscores_enabled is False

    def test_mlb_not_in_scheduled_leagues(self):
        """MLB is not in scheduled ingestion leagues."""
        assert "MLB" not in get_scheduled_leagues()

    def test_mlb_not_in_social_leagues(self):
        """MLB is not in social-enabled leagues."""
        assert "MLB" not in get_social_enabled_leagues()

    def test_mlb_not_in_timeline_leagues(self):
        """MLB is not in timeline-enabled leagues."""
        assert "MLB" not in get_timeline_enabled_leagues()

    def test_all_leagues_have_boxscores(self):
        """All leagues except MLB have boxscores enabled."""
        for code, league_config in LEAGUE_CONFIG.items():
            if code == "MLB":
                assert league_config.boxscores_enabled is False
            else:
                assert league_config.boxscores_enabled is True

    def test_all_leagues_have_odds(self):
        """All leagues have odds enabled."""
        for league_config in LEAGUE_CONFIG.values():
            assert league_config.odds_enabled is True


class TestGetLeagueConfig:
    """Tests for get_league_config function."""

    def test_returns_nba_config(self):
        """Returns NBA configuration."""
        config = get_league_config("NBA")
        assert config.code == "NBA"
        assert config.display_name == "NBA Basketball"

    def test_returns_nhl_config(self):
        """Returns NHL configuration."""
        config = get_league_config("NHL")
        assert config.code == "NHL"
        assert config.display_name == "NHL Hockey"

    def test_returns_ncaab_config(self):
        """Returns NCAAB configuration."""
        config = get_league_config("NCAAB")
        assert config.code == "NCAAB"
        assert config.display_name == "NCAA Basketball"

    def test_raises_for_invalid_league(self):
        """Raises ValueError for invalid league code."""
        with pytest.raises(ValueError) as exc_info:
            get_league_config("INVALID")
        assert "Unknown league" in str(exc_info.value)
        assert "INVALID" in str(exc_info.value)


class TestGetEnabledLeagues:
    """Tests for get_enabled_leagues function."""

    def test_returns_list(self):
        """Returns a list."""
        result = get_enabled_leagues()
        assert isinstance(result, list)

    def test_contains_all_configured_leagues(self):
        """Contains all configured leagues."""
        result = get_enabled_leagues()
        assert "NBA" in result
        assert "NHL" in result
        assert "NCAAB" in result
        assert "MLB" in result


class TestGetScheduledLeagues:
    """Tests for get_scheduled_leagues function."""

    def test_returns_list(self):
        """Returns a list."""
        result = get_scheduled_leagues()
        assert isinstance(result, list)

    def test_contains_scheduled_leagues(self):
        """Contains leagues with scheduled_ingestion=True."""
        result = get_scheduled_leagues()
        # All currently configured leagues have scheduled_ingestion=True
        assert "NBA" in result
        assert "NHL" in result
        assert "NCAAB" in result


class TestGetSocialEnabledLeagues:
    """Tests for get_social_enabled_leagues function."""

    def test_returns_list(self):
        """Returns a list."""
        result = get_social_enabled_leagues()
        assert isinstance(result, list)

    def test_contains_nba_and_nhl(self):
        """Contains NBA and NHL (which have social enabled)."""
        result = get_social_enabled_leagues()
        assert "NBA" in result
        assert "NHL" in result

    def test_includes_ncaab(self):
        """Includes NCAAB (which has social enabled)."""
        result = get_social_enabled_leagues()
        assert "NCAAB" in result


class TestGetTimelineEnabledLeagues:
    """Tests for get_timeline_enabled_leagues function."""

    def test_returns_list(self):
        """Returns a list."""
        result = get_timeline_enabled_leagues()
        assert isinstance(result, list)

    def test_contains_all_leagues_with_timeline(self):
        """Contains all leagues with timeline enabled."""
        result = get_timeline_enabled_leagues()
        assert "NBA" in result
        assert "NHL" in result
        assert "NCAAB" in result


class TestValidateLeagueCode:
    """Tests for validate_league_code function."""

    def test_returns_valid_code(self):
        """Returns the league code if valid."""
        assert validate_league_code("NBA") == "NBA"
        assert validate_league_code("NHL") == "NHL"
        assert validate_league_code("NCAAB") == "NCAAB"

    def test_raises_for_invalid_code(self):
        """Raises ValueError for invalid league code."""
        with pytest.raises(ValueError) as exc_info:
            validate_league_code("INVALID")
        assert "Invalid league_code" in str(exc_info.value)
        assert "INVALID" in str(exc_info.value)


class TestIsSocialEnabled:
    """Tests for is_social_enabled function."""

    def test_nba_enabled(self):
        """NBA has social enabled."""
        assert is_social_enabled("NBA") is True

    def test_nhl_enabled(self):
        """NHL has social enabled."""
        assert is_social_enabled("NHL") is True

    def test_ncaab_enabled(self):
        """NCAAB has social enabled."""
        assert is_social_enabled("NCAAB") is True

    def test_unknown_league_uses_default(self):
        """Unknown league uses default config (social_enabled=True)."""
        # Default LeagueConfig has social_enabled=True
        assert is_social_enabled("UNKNOWN") is True


class TestIsTimelineEnabled:
    """Tests for is_timeline_enabled function."""

    def test_nba_enabled(self):
        """NBA has timeline enabled."""
        assert is_timeline_enabled("NBA") is True

    def test_nhl_enabled(self):
        """NHL has timeline enabled."""
        assert is_timeline_enabled("NHL") is True

    def test_ncaab_enabled(self):
        """NCAAB has timeline enabled."""
        assert is_timeline_enabled("NCAAB") is True

    def test_unknown_league_uses_default(self):
        """Unknown league uses default config (timeline_enabled=True)."""
        # Default LeagueConfig has timeline_enabled=True
        assert is_timeline_enabled("UNKNOWN") is True


class TestLiveOddsDisabled:
    """Tests for live_odds_enabled safety invariant."""

    def test_all_leagues_have_live_odds_disabled(self):
        """All configured leagues must have live_odds_enabled=False."""
        for code, cfg in LEAGUE_CONFIG.items():
            assert cfg.live_odds_enabled is False, f"{code} has live_odds_enabled=True"

    def test_default_live_odds_disabled(self):
        """Default LeagueConfig has live_odds_enabled=False."""
        config = LeagueConfig(code="TEST", display_name="Test")
        assert config.live_odds_enabled is False
