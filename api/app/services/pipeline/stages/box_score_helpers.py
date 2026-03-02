"""Box score helpers for block-level statistical context.

This module computes cumulative box scores and mini box scores used to
enrich narrative blocks with per-team/per-player stat summaries.
"""

from __future__ import annotations

import re
from typing import Any

from .game_stats_helpers import (
    _apply_basketball_scoring,
    _compute_single_team_delta,
    _extract_assister_from_description,
    _extract_last_name,
    _extract_scorer_from_description,
)


def _extract_nhl_assisters(desc: str) -> list[str]:
    """Extract assist player names from an NHL goal description.

    Descriptions like "Goal (wrist-shot) (assists: Connor McDavid, Leon Draisaitl)"
    return ["Connor McDavid", "Leon Draisaitl"].
    """
    match = re.search(r"\(assists?:\s*(.+?)\)", desc, re.IGNORECASE)
    if match:
        return [name.strip() for name in match.group(1).split(",") if name.strip()]
    return []


def compute_cumulative_box_score(
    pbp_events: list[dict[str, Any]],
    up_to_play_index: int,
    home_team: str,
    away_team: str,
    league_code: str = "NBA",
    home_team_abbrev: str = "",
    away_team_abbrev: str = "",
) -> dict[str, Any]:
    """Compute full cumulative box score up to a specific play.

    Returns sport-specific stats for top contributors on each team.

    Args:
        pbp_events: All PBP events for the game
        up_to_play_index: Compute stats up to and including this play index
        home_team: Home team name (for display)
        away_team: Away team name (for display)
        league_code: League code (NBA, NCAAB, NHL, MLB)
        home_team_abbrev: Home team abbreviation (for matching, e.g., "GSW")
        away_team_abbrev: Away team abbreviation (for matching, e.g., "LAC")

    Returns:
        Box score dict with home/away team stats:
        {
            "home": {
                "team": "Hawks",
                "score": 45,
                "players": [
                    {"name": "Trae Young", "pts": 12, "reb": 2, "ast": 5, "3pm": 2},
                    ...
                ]
            },
            "away": {
                "team": "Celtics",
                "score": 42,
                "players": [...]
            }
        }

        For NHL:
        {
            "home": {
                "team": "Bruins",
                "score": 3,
                "players": [
                    {"name": "David Pastrnak", "goals": 1, "assists": 1, "sog": 4, "plusMinus": 2},
                    ...
                ],
                "goalie": {"name": "Jeremy Swayman", "saves": 24, "ga": 2, "savePct": 0.923}
            },
            "away": {...}
        }
    """
    # Track stats by player and team
    player_stats: dict[str, dict[str, Any]] = {}
    player_teams: dict[str, str] = {}  # player_name -> team_abbrev

    # Normalize abbreviations for team matching in score delta
    home_abbrev_upper = home_team_abbrev.upper() if home_team_abbrev else ""
    away_abbrev_upper = away_team_abbrev.upper() if away_team_abbrev else ""

    # Get final scores up to this point
    home_score = 0
    away_score = 0
    prev_home = 0
    prev_away = 0

    for event in pbp_events:
        if event.get("play_index", 0) > up_to_play_index:
            break

        # Track scores
        curr_home = event.get("home_score")
        if curr_home is None:
            curr_home = prev_home
        curr_away = event.get("away_score")
        if curr_away is None:
            curr_away = prev_away
        home_score = curr_home
        away_score = curr_away

        team_abbrev = event.get("team_abbreviation", "")
        score_delta = _compute_single_team_delta(
            curr_home, curr_away, prev_home, prev_away,
            team_abbreviation=team_abbrev,
            home_team_abbrev=home_abbrev_upper,
            away_team_abbrev=away_abbrev_upper,
        )

        player = event.get("player_name")

        if not player:
            prev_home = curr_home
            prev_away = curr_away
            continue

        # Track which team this player is on
        if player not in player_teams and team_abbrev:
            player_teams[player] = team_abbrev

        if player not in player_stats:
            if league_code == "MLB":
                player_stats[player] = {
                    "runs": 0,
                    "hits": 0,
                    "rbi": 0,
                    "hr": 0,
                    "sb": 0,
                    "k": 0,
                }
            elif league_code == "NHL":
                player_stats[player] = {
                    "goals": 0,
                    "assists": 0,
                    "sog": 0,  # shots on goal
                    "plusMinus": 0,
                    "saves": 0,
                    "ga": 0,  # goals against (for goalies)
                    "is_goalie": False,
                }
            else:
                # NBA/NCAAB
                player_stats[player] = {
                    "pts": 0,
                    "reb": 0,
                    "ast": 0,
                    "3pm": 0,
                    "fgm": 0,
                    "ftm": 0,
                }

        play_type = (event.get("play_type") or "").lower()
        desc = (event.get("description") or "").lower()
        original_desc = event.get("description") or ""

        if league_code == "MLB":
            _accumulate_mlb_stats(player_stats[player], play_type, desc, score_delta)
        elif league_code == "NHL":
            _accumulate_nhl_stats(player_stats[player], play_type, desc)
            # Credit assists from goal descriptions (format: "goal ... (assists: Name1, Name2)")
            if play_type.lower() in ("goal", "scored"):
                for assister in _extract_nhl_assisters(original_desc):
                    if assister not in player_stats:
                        player_stats[assister] = {
                            "goals": 0, "assists": 0, "sog": 0,
                            "plusMinus": 0, "saves": 0, "ga": 0, "is_goalie": False,
                        }
                    player_stats[assister]["assists"] += 1
                    if assister not in player_teams and team_abbrev:
                        player_teams[assister] = team_abbrev
        else:
            # Check if event player is actually the assister (NCAAB pattern:
            # player field = assister, description = "Scorer makes shot (Player assists)")
            actual_scorer = _extract_scorer_from_description(original_desc) if score_delta > 0 else None
            if actual_scorer and actual_scorer.lower() != player.lower() and score_delta > 0:
                # Event player is the assister; credit actual scorer with points
                if actual_scorer not in player_stats:
                    player_stats[actual_scorer] = {
                        "pts": 0, "reb": 0, "ast": 0, "3pm": 0, "fgm": 0, "ftm": 0
                    }
                if actual_scorer not in player_teams and team_abbrev:
                    player_teams[actual_scorer] = team_abbrev
                scored = _apply_basketball_scoring(player_stats[actual_scorer], score_delta)
                if scored:
                    player_stats[player]["ast"] += 1
            else:
                scored = _apply_basketball_scoring(player_stats[player], score_delta)

                # Extract and credit assists from scoring plays (NBA format)
                if scored:
                    assister = _extract_assister_from_description(original_desc)
                    if assister:
                        if assister not in player_stats:
                            player_stats[assister] = {
                                "pts": 0, "reb": 0, "ast": 0, "3pm": 0, "fgm": 0, "ftm": 0
                            }
                        player_stats[assister]["ast"] += 1
                        # Track assister's team (same as scorer's team)
                        if assister not in player_teams and team_abbrev:
                            player_teams[assister] = team_abbrev

            # Non-scoring stats: play_type matching for reb/ast
            if play_type in ("rebound", "offensive_rebound", "defensive_rebound"):
                player_stats[player]["reb"] += 1
            elif play_type == "assist":
                player_stats[player]["ast"] += 1

        prev_home = curr_home
        prev_away = curr_away

    # Assign players to home/away by abbreviation match
    home_players: list[dict[str, Any]] = []
    away_players: list[dict[str, Any]] = []

    for player_name, stats in player_stats.items():
        team_abbrev = player_teams.get(player_name, "")

        player_entry = {"name": player_name, **stats}

        if not team_abbrev:
            continue

        team_upper = team_abbrev.upper()

        if home_abbrev_upper and team_upper == home_abbrev_upper:
            home_players.append(player_entry)
        elif away_abbrev_upper and team_upper == away_abbrev_upper:
            away_players.append(player_entry)

    # Sort by contribution (points for basketball, goals+assists for hockey, runs+rbi for MLB)
    def _mlb_sort_key(p: dict[str, Any]) -> tuple[int, int]:
        return (p.get("runs", 0) + p.get("rbi", 0), p.get("hits", 0))

    def _nhl_sort_key(p: dict[str, Any]) -> tuple[int, int]:
        return (p.get("goals", 0) + p.get("assists", 0), p.get("sog", 0))

    def _basketball_sort_key(p: dict[str, Any]) -> tuple[int, int]:
        return (p.get("pts", 0), p.get("ast", 0))

    sort_key = _mlb_sort_key if league_code == "MLB" else (_nhl_sort_key if league_code == "NHL" else _basketball_sort_key)

    home_players.sort(key=sort_key, reverse=True)
    away_players.sort(key=sort_key, reverse=True)

    # Take top 5 contributors per team
    max_players = 5
    home_top = home_players[:max_players]
    away_top = away_players[:max_players]

    # Build result
    result: dict[str, Any] = {
        "home": {
            "team": home_team,
            "score": home_score,
            "players": home_top,
        },
        "away": {
            "team": away_team,
            "score": away_score,
            "players": away_top,
        },
    }

    # For NHL, extract goalie stats
    if league_code == "NHL":
        for side, players in [("home", home_players), ("away", away_players)]:
            goalies = [p for p in players if p.get("is_goalie")]
            if goalies:
                goalie = goalies[0]
                saves = goalie.get("saves", 0)
                ga = goalie.get("ga", 0)
                shots_faced = saves + ga
                save_pct = round(saves / shots_faced, 3) if shots_faced > 0 else 0.0
                result[side]["goalie"] = {
                    "name": goalie["name"],
                    "saves": saves,
                    "ga": ga,
                    "savePct": save_pct,
                }

    return result


def _accumulate_nhl_stats(
    stats: dict[str, Any],
    play_type: str,
    desc: str,
) -> None:
    """Accumulate NHL stats for a player from a play event."""
    if play_type in ("goal", "scored"):
        stats["goals"] += 1
    elif play_type == "assist":
        stats["assists"] += 1
    elif play_type in ("shot", "shot_on_goal", "sog"):
        stats["sog"] += 1
    elif play_type == "save":
        stats["saves"] += 1
        stats["is_goalie"] = True
    elif play_type in ("goal_against", "goal_allowed"):
        stats["ga"] += 1
        stats["is_goalie"] = True
    else:
        # Parse description
        if "goal" in desc and "saved" not in desc:
            stats["goals"] += 1
        elif "assist" in desc:
            stats["assists"] += 1
        elif "shot" in desc and "blocked" not in desc:
            stats["sog"] += 1
        elif "save" in desc:
            stats["saves"] += 1
            stats["is_goalie"] = True


def _accumulate_mlb_stats(
    stats: dict[str, Any],
    play_type: str,
    desc: str,
    score_delta: int,
) -> None:
    """Accumulate MLB stats for a player from a play event."""
    pt = play_type.lower()
    dl = desc.lower()

    # Scoring
    if score_delta > 0:
        stats["runs"] += score_delta

    # Hits
    if pt in ("single", "double", "triple", "home_run") or "single" in dl or "doubles" in dl or "triples" in dl:
        stats["hits"] += 1

    # Home runs
    if pt == "home_run" or "home run" in dl or "homer" in dl:
        stats["hr"] += 1
        stats["hits"] += 0  # already counted above when pt == "home_run"

    # RBI (from description, e.g., "2 RBI")
    rbi_match = re.search(r"(\d+)\s*rbi", dl)
    if rbi_match:
        stats["rbi"] += int(rbi_match.group(1))
    elif score_delta > 0 and pt in ("single", "double", "triple", "home_run", "sac_fly", "sac_bunt", "grounded_into_double_play"):
        stats["rbi"] += score_delta

    # Stolen bases
    if pt == "stolen_base" or "steals" in dl or "stolen base" in dl:
        stats["sb"] += 1

    # Strikeouts (batter)
    if pt == "strikeout" or "strikes out" in dl or "struck out" in dl:
        stats["k"] += 1


def compute_block_mini_box(
    pbp_events: list[dict[str, Any]],
    block_start_play_idx: int,
    block_end_play_idx: int,
    prev_block_end_play_idx: int | None,
    home_team: str,
    away_team: str,
    league_code: str = "NBA",
    home_team_abbrev: str = "",
    away_team_abbrev: str = "",
) -> dict[str, Any]:
    """Compute mini box score for a block with cumulative stats and segment deltas.

    Returns a mini box with:
    - Cumulative stats at end of block (top 3 performers per team)
    - Delta stats showing production during this block segment (+x)
    - Block segment contributors highlighted

    Args:
        pbp_events: All PBP events for the game
        block_start_play_idx: First play index in this block
        block_end_play_idx: Last play index in this block
        prev_block_end_play_idx: Last play index of previous block (None for first block)
        home_team: Home team name
        away_team: Away team name
        league_code: League code (NBA, NCAAB, NHL, MLB)
        home_team_abbrev: Home team abbreviation
        away_team_abbrev: Away team abbreviation

    Returns:
        Mini box dict:
        {
            "home": {
                "team": "Hawks",
                "players": [
                    {"name": "Trae Young", "pts": 18, "deltaPts": 6, "reb": 2, "ast": 7},
                    ...
                ]
            },
            "away": {...},
            "blockStars": ["Young", "Mitchell"]  # Top contributors this segment
        }
    """
    # Get cumulative box at end of this block
    cumulative = compute_cumulative_box_score(
        pbp_events,
        block_end_play_idx,
        home_team,
        away_team,
        league_code,
        home_team_abbrev,
        away_team_abbrev,
    )

    # Get cumulative box at end of previous block (for deltas)
    if prev_block_end_play_idx is not None:
        prev_cumulative = compute_cumulative_box_score(
            pbp_events,
            prev_block_end_play_idx,
            home_team,
            away_team,
            league_code,
            home_team_abbrev,
            away_team_abbrev,
        )
    else:
        # First block - no previous stats
        prev_cumulative = {
            "home": {"team": home_team, "score": 0, "players": []},
            "away": {"team": away_team, "score": 0, "players": []},
        }

    # Build lookup for previous stats
    prev_home_stats: dict[str, dict[str, int]] = {
        p["name"]: p for p in prev_cumulative["home"].get("players", [])
    }
    prev_away_stats: dict[str, dict[str, int]] = {
        p["name"]: p for p in prev_cumulative["away"].get("players", [])
    }

    # Key stat for sorting (points for basketball, goals+assists for hockey, runs+rbi for MLB)
    if league_code == "MLB":
        key_stat = "runs"
        delta_key = "deltaRuns"
    elif league_code == "NHL":
        key_stat = "goals"
        delta_key = "deltaGoals"
    else:
        key_stat = "pts"
        delta_key = "deltaPts"

    block_stars: list[str] = []

    # Add deltas to cumulative stats
    for side, prev_stats in [("home", prev_home_stats), ("away", prev_away_stats)]:
        for player in cumulative[side].get("players", []):
            name = player["name"]
            prev = prev_stats.get(name, {})

            # Calculate deltas for key stats
            if league_code == "MLB":
                player["deltaRuns"] = player.get("runs", 0) - prev.get("runs", 0)
                player["deltaHits"] = player.get("hits", 0) - prev.get("hits", 0)
                player["deltaRbi"] = player.get("rbi", 0) - prev.get("rbi", 0)
                delta_contribution = player.get("deltaRuns", 0) + player.get("deltaRbi", 0)
            elif league_code == "NHL":
                player["deltaGoals"] = player.get("goals", 0) - prev.get("goals", 0)
                player["deltaAssists"] = player.get("assists", 0) - prev.get("assists", 0)
                delta_contribution = player.get("deltaGoals", 0) + player.get("deltaAssists", 0)
            else:
                player["deltaPts"] = player.get("pts", 0) - prev.get("pts", 0)
                player["deltaReb"] = player.get("reb", 0) - prev.get("reb", 0)
                player["deltaAst"] = player.get("ast", 0) - prev.get("ast", 0)
                delta_contribution = player.get("deltaPts", 0)

            # Track block stars (players who contributed significantly this segment)
            if delta_contribution >= 5 or (league_code in ("NHL", "MLB") and delta_contribution >= 1):
                last_name = _extract_last_name(name)
                block_stars.append(last_name)

    # Trim to top 3 per team for mini box
    for side in ["home", "away"]:
        players = cumulative[side].get("players", [])
        # Sort by cumulative contribution, then by delta
        players.sort(
            key=lambda p: (p.get(key_stat, 0), p.get(delta_key, 0)),
            reverse=True,
        )
        cumulative[side]["players"] = players[:3]

    # Strip mini box to key stats only
    if league_code == "MLB":
        pra_keys = {"name", "runs", "hits", "rbi", "hr", "deltaRuns", "deltaHits", "deltaRbi"}
    elif league_code == "NHL":
        pra_keys = {"name", "goals", "assists", "deltaGoals", "deltaAssists"}
    else:
        pra_keys = {"name", "pts", "reb", "ast", "deltaPts", "deltaReb", "deltaAst"}
    for side in ["home", "away"]:
        cumulative[side]["players"] = [
            {k: v for k, v in p.items() if k in pra_keys}
            for p in cumulative[side]["players"]
        ]

    # Remove scores from mini_box (already in block score_before/after)
    cumulative["home"].pop("score", None)
    cumulative["away"].pop("score", None)

    # Add block stars (top 2)
    cumulative["blockStars"] = block_stars[:2]

    return cumulative
