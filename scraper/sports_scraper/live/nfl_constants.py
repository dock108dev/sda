"""Constants for NFL live feed processing.

Contains ESPN API endpoints and event type mappings.
"""

from __future__ import annotations

# ESPN NFL API endpoints (free, no key required)
NFL_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates={date}"
NFL_SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event={game_id}"

# Play index multiplier to ensure unique ordering across periods
NFL_PERIOD_MULTIPLIER = 10000

# Minimum expected plays for a completed NFL game
NFL_MIN_EXPECTED_PLAYS = 100

# ESPN season type codes → internal season_type strings
NFL_SEASON_TYPE_MAP: dict[int, str] = {
    1: "preseason",
    2: "regular",
    3: "postseason",
}

# ESPN game status type → internal status
NFL_STATUS_MAP: dict[str, str] = {
    "STATUS_SCHEDULED": "scheduled",
    "STATUS_IN_PROGRESS": "live",
    "STATUS_HALFTIME": "live",
    "STATUS_END_PERIOD": "live",
    "STATUS_FINAL": "final",
    "STATUS_FINAL_OVERTIME": "final",
    "STATUS_POSTPONED": "postponed",
    "STATUS_CANCELED": "cancelled",
    "STATUS_DELAYED": "live",
}

# ESPN play type text → canonical event types
NFL_EVENT_TYPE_MAP: dict[str, str] = {
    # Passing
    "Pass": "PASS",
    "Pass Reception": "PASS_RECEPTION",
    "Pass Completion": "PASS_COMPLETION",
    "Pass Incompletion": "PASS_INCOMPLETION",
    "Passing Touchdown": "TOUCHDOWN",
    "Interception Return": "INTERCEPTION",
    "Sack": "SACK",
    # Rushing
    "Rush": "RUSH",
    "Rushing Touchdown": "TOUCHDOWN",
    # Scoring
    "Touchdown": "TOUCHDOWN",
    "Field Goal Good": "FIELD_GOAL",
    "Field Goal Missed": "FIELD_GOAL_MISSED",
    "Extra Point Good": "EXTRA_POINT",
    "Extra Point Missed": "EXTRA_POINT_MISSED",
    "Two-Point Conversion": "TWO_POINT_CONVERSION",
    "Safety": "SAFETY",
    # Special teams
    "Kickoff": "KICKOFF",
    "Kickoff Return": "KICKOFF_RETURN",
    "Punt": "PUNT",
    "Punt Return": "PUNT_RETURN",
    # Turnovers
    "Fumble": "FUMBLE",
    "Fumble Recovery (Own)": "FUMBLE_RECOVERY",
    "Fumble Recovery (Opponent)": "FUMBLE_RECOVERY",
    "Interception": "INTERCEPTION",
    # Penalties
    "Penalty": "PENALTY",
    # Game flow
    "Timeout": "TIMEOUT",
    "Two-Minute Warning": "TWO_MINUTE_WARNING",
    "End Period": "PERIOD_END",
    "End of Half": "PERIOD_END",
    "End of Game": "GAME_END",
    "Coin Toss": "COIN_TOSS",
}
