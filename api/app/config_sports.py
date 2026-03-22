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

    # Season audit baselines (total league-wide unique games, not per-team)
    expected_regular_season_games: int | None = None
    expected_teams: int | None = None

    # Season calendar (month, day) — used to pro-rate expected games mid-season
    # season_start/end are relative to the season start year passed to the audit.
    # For cross-year seasons (NBA, NHL, NFL): end is in year+1.
    season_start_month: int | None = None    # Month the season typically starts
    season_start_day: int | None = None      # Day the season typically starts
    season_end_month: int | None = None      # Month the season typically ends
    season_end_day: int | None = None        # Day the season typically ends
    season_crosses_year: bool = False         # True if season spans two calendar years


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
        expected_regular_season_games=1230,  # 82 * 30 / 2
        expected_teams=30,
        season_start_month=10, season_start_day=22,   # Late October
        season_end_month=4, season_end_day=13,         # Mid April
        season_crosses_year=True,
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
        expected_regular_season_games=1312,  # 82 * 32 / 2
        expected_teams=32,
        season_start_month=10, season_start_day=8,     # Early October
        season_end_month=4, season_end_day=17,          # Mid April
        season_crosses_year=True,
    ),
    "NCAAB": LeagueConfig(
        code="NCAAB",
        display_name="NCAA Basketball",
        boxscores_enabled=True,
        odds_enabled=True,
        social_enabled=True,
        pbp_enabled=True,
        timeline_enabled=True,
        scheduled_ingestion=True,
        live_pbp_enabled=True,
        estimated_game_duration_hours=2.5,
        expected_regular_season_games=5460,  # ~30 * 364 / 2 (approximate)
        expected_teams=364,
        season_start_month=11, season_start_day=4,     # Early November
        season_end_month=3, season_end_day=16,          # Mid March (before tourney)
        season_crosses_year=True,
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
        estimated_game_duration_hours=3.5,
        expected_regular_season_games=2430,  # 162 * 30 / 2
        expected_teams=30,
        season_start_month=3, season_start_day=27,     # Late March
        season_end_month=9, season_end_day=28,          # Late September
        season_crosses_year=False,
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
        expected_regular_season_games=272,  # 17 * 32 / 2
        expected_teams=32,
        season_start_month=9, season_start_day=5,      # Early September
        season_end_month=1, season_end_day=4,           # Early January
        season_crosses_year=True,
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
