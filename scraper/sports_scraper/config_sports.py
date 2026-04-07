"""
Single Source of Truth (SSOT) for enabled sports/leagues.

All scheduled jobs, post-scrape triggers, and pipelines should reference
this configuration. Never hardcode league strings elsewhere.

To add a new sport:
1. Add entry to LEAGUE_CONFIG with appropriate feature flags
2. Run: no other code changes needed for basic ingestion
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LeagueConfig:
    """Configuration for a single league/sport.

    This is the Single Source of Truth (SSOT) for per-league live-data behavior:
    - live_pbp_enabled: poll live play-by-play data
    - live_boxscore_enabled: poll live boxscores during games
    - live_odds_enabled: persist odds for live games (must remain False —
      closing-line architecture requires pre-game odds only)
    """

    code: str                       # "NBA", "NHL", "NCAAB", "MLB"
    display_name: str               # "NBA Basketball"

    # Pipeline feature flags
    boxscores_enabled: bool = True
    odds_enabled: bool = True
    social_enabled: bool = True     # X/Twitter integration
    pbp_enabled: bool = True        # Play-by-play
    timeline_enabled: bool = True   # Timeline/moments generation

    # Scheduling
    scheduled_ingestion: bool = True  # Include in daily scheduled runs

    # Game-state-machine window config
    pregame_window_hours: int = 6       # Hours before game_date to enter pregame
    postgame_window_hours: int = 3      # Hours after final to keep in active window
    live_pbp_poll_minutes: int = 5      # Minutes between PBP polls for live games
    live_pbp_enabled: bool = True       # Whether to poll live PBP for this league
    live_boxscore_enabled: bool = True  # Whether to poll live boxscores for this league
    live_odds_enabled: bool = False   # Must remain False — closing-line-only architecture
    estimated_game_duration_hours: float = 3.0  # Typical game length for time-based fallback


# Master configuration for all leagues
LEAGUE_CONFIG: dict[str, LeagueConfig] = {
    "NBA": LeagueConfig(
        code="NBA",
        display_name="NBA Basketball",
        boxscores_enabled=True,
        odds_enabled=True,
        social_enabled=True,
        pbp_enabled=True,
        timeline_enabled=True,
        scheduled_ingestion=True,
    ),
    "NHL": LeagueConfig(
        code="NHL",
        display_name="NHL Hockey",
        boxscores_enabled=True,
        odds_enabled=True,
        social_enabled=True,
        pbp_enabled=True,
        timeline_enabled=True,
        scheduled_ingestion=True,
    ),
    "NCAAB": LeagueConfig(
        code="NCAAB",
        display_name="NCAA Basketball",
        boxscores_enabled=True,
        odds_enabled=True,
        social_enabled=True,
        pbp_enabled=True,
        timeline_enabled=True,
        scheduled_ingestion=True,  # Uses api.collegebasketballdata.com
        live_pbp_enabled=True,  # Handled via NCAAB batch polling
        estimated_game_duration_hours=2.5,  # Regulation ~2h + OT buffer
    ),
    "MLB": LeagueConfig(
        code="MLB",
        display_name="MLB Baseball",
        boxscores_enabled=True,
        odds_enabled=True,
        social_enabled=True,
        pbp_enabled=True,
        timeline_enabled=True,
        scheduled_ingestion=True,
        live_pbp_enabled=True,
        live_boxscore_enabled=True,
        estimated_game_duration_hours=5.0,  # 3.5h game + buffer for rain delays
    ),
    "NFL": LeagueConfig(
        code="NFL",
        display_name="NFL Football",
        boxscores_enabled=True,
        odds_enabled=True,
        social_enabled=True,
        pbp_enabled=True,
        timeline_enabled=True,
        scheduled_ingestion=True,
        live_pbp_enabled=True,
        live_boxscore_enabled=True,
        estimated_game_duration_hours=3.5,
    ),
}

# --- Static validation: live_odds_enabled must remain False for all leagues ---
# Live odds would overwrite pre-game closing lines. This assertion catches
# accidental config changes at import time.
for _code, _cfg in LEAGUE_CONFIG.items():
    assert not _cfg.live_odds_enabled, (
        f"live_odds_enabled must be False for {_code}. "
        f"Live odds would overwrite pre-game closing lines."
    )


def get_league_config(league_code: str) -> LeagueConfig:
    """
    Get configuration for a specific league.

    Raises:
        ValueError: If league_code is not in LEAGUE_CONFIG
    """
    if league_code not in LEAGUE_CONFIG:
        valid = ", ".join(LEAGUE_CONFIG.keys())
        raise ValueError(f"Unknown league '{league_code}'. Valid leagues: {valid}")
    return LEAGUE_CONFIG[league_code]


def get_enabled_leagues() -> list[str]:
    """Get list of all configured league codes."""
    return list(LEAGUE_CONFIG.keys())


def get_scheduled_leagues() -> list[str]:
    """Get leagues enabled for scheduled daily ingestion."""
    return [code for code, cfg in LEAGUE_CONFIG.items() if cfg.scheduled_ingestion]


def get_social_enabled_leagues() -> list[str]:
    """Get leagues with social/X integration enabled."""
    return [code for code, cfg in LEAGUE_CONFIG.items() if cfg.social_enabled]


def get_timeline_enabled_leagues() -> list[str]:
    """Get leagues with timeline generation enabled."""
    return [code for code, cfg in LEAGUE_CONFIG.items() if cfg.timeline_enabled]


def validate_league_code(league_code: str) -> str:
    """
    Validate and return league code.

    Raises:
        ValueError: If league_code is not valid
    """
    if league_code not in LEAGUE_CONFIG:
        valid = ", ".join(LEAGUE_CONFIG.keys())
        raise ValueError(f"Invalid league_code '{league_code}'. Must be one of: {valid}")
    return league_code


def is_social_enabled(league_code: str) -> bool:
    """Check if social integration is enabled for a league."""
    return LEAGUE_CONFIG.get(league_code, LeagueConfig(code="", display_name="")).social_enabled


def is_timeline_enabled(league_code: str) -> bool:
    """Check if timeline generation is enabled for a league."""
    return LEAGUE_CONFIG.get(league_code, LeagueConfig(code="", display_name="")).timeline_enabled


def get_odds_enabled_leagues() -> list[str]:
    """Get leagues with odds scraping enabled."""
    return [code for code, cfg in LEAGUE_CONFIG.items() if cfg.odds_enabled]
