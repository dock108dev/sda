"""SSOT per-game processing functions for all leagues.

Each function takes a session + SportsGame ORM object, fetches data from the
shared API client, calls shared persistence functions, and returns a
GameProcessResult. Functions do NOT handle game selection, rate limiting,
jitter, or locking -- those are caller-side concerns.

Both the live polling path (polling_helpers.py) and the manual/scheduled
ingestion path (pbp_*.py, *_boxscore_ingestion.py) call these same functions,
ensuring identical processing regardless of trigger.

Per-league implementations live in game_processors_{league}.py modules.
This file provides the shared dataclass, dispatchers, and re-exports for
backward compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GameProcessResult:
    """Result of processing a single game."""

    api_calls: int = 0
    events_inserted: int = 0
    boxscore_updated: bool = False
    transition: dict | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Re-exports for backward compatibility
# ---------------------------------------------------------------------------
# All callers that do `from .game_processors import process_game_pbp_nba`
# (or similar) will continue to work.

from .game_processors_mlb import (  # noqa: E402, F401
    check_game_status_mlb,
    process_game_boxscore_mlb,
    process_game_pbp_mlb,
)
from .game_processors_nba import (  # noqa: E402, F401
    check_game_status_nba,
    process_game_boxscore_nba,
    process_game_pbp_nba,
)
from .game_processors_ncaab import (  # noqa: E402, F401
    process_game_boxscore_ncaab,
    process_game_boxscores_ncaab_batch,
    process_game_pbp_ncaab,
)
from .game_processors_nfl import (  # noqa: E402, F401
    check_game_status_nfl,
    process_game_boxscore_nfl,
    process_game_pbp_nfl,
)
from .game_processors_nhl import (  # noqa: E402, F401
    check_game_status_nhl,
    process_game_boxscore_nhl,
    process_game_pbp_nhl,
)

# ---------------------------------------------------------------------------
# Dispatchers (route by league_code)
# ---------------------------------------------------------------------------


def process_game_pbp(session, game, league_code: str) -> GameProcessResult:
    """Dispatch PBP processing to the appropriate league handler."""
    if league_code == "NBA":
        return process_game_pbp_nba(session, game)
    elif league_code == "NHL":
        return process_game_pbp_nhl(session, game)
    elif league_code == "MLB":
        return process_game_pbp_mlb(session, game)
    elif league_code == "NCAAB":
        return process_game_pbp_ncaab(session, game)
    elif league_code == "NFL":
        return process_game_pbp_nfl(session, game)
    return GameProcessResult()


def process_game_boxscore(session, game, league_code: str) -> GameProcessResult:
    """Dispatch boxscore processing to the appropriate league handler."""
    if league_code == "NBA":
        return process_game_boxscore_nba(session, game)
    elif league_code == "NHL":
        return process_game_boxscore_nhl(session, game)
    elif league_code == "MLB":
        return process_game_boxscore_mlb(session, game)
    elif league_code == "NCAAB":
        return process_game_boxscore_ncaab(session, game)
    elif league_code == "NFL":
        return process_game_boxscore_nfl(session, game)
    return GameProcessResult()
