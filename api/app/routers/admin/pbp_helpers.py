"""Helper functions for PBP admin endpoints."""

from __future__ import annotations

from typing import Any

from ...db.sports import SportsGamePlay
from ...routers.sports.schemas.common import _score_obj
from .pbp_models import PlayDetail, PlaySummary


def build_resolution_summary(plays: list[SportsGamePlay]) -> dict[str, Any]:
    """Build resolution summary from plays."""
    total = len(plays)
    if total == 0:
        return {
            "total_plays": 0,
            "teams_resolved": 0,
            "teams_unresolved": 0,
            "team_resolution_rate": 0,
            "players_with_name": 0,
            "players_without_name": 0,
            "plays_with_score": 0,
            "plays_without_score": 0,
        }

    teams_resolved = sum(1 for p in plays if p.team_id is not None)
    teams_unresolved = sum(
        1 for p in plays if p.team_id is None and (p.description or "").strip()
    )
    players_with_name = sum(1 for p in plays if p.player_name)
    plays_with_score = sum(1 for p in plays if p.home_score is not None)

    return {
        "total_plays": total,
        "teams_resolved": teams_resolved,
        "teams_unresolved": teams_unresolved,
        "team_resolution_rate": round(teams_resolved / total * 100, 1)
        if total > 0
        else 0,
        "players_with_name": players_with_name,
        "players_without_name": total - players_with_name,
        "plays_with_score": plays_with_score,
        "plays_without_score": total - plays_with_score,
    }


def play_to_summary(play: SportsGamePlay) -> PlaySummary:
    """Convert a play to summary format."""
    return PlaySummary(
        play_index=play.play_index,
        quarter=play.quarter,
        game_clock=play.game_clock,
        play_type=play.play_type,
        team_abbreviation=play.team.abbreviation if play.team else None,
        team_id=play.team_id,
        team_resolved=play.team_id is not None,
        player_name=play.player_name,
        player_id=play.player_id,
        description=play.description,
        score=_score_obj(play.home_score, play.away_score),
        has_raw_data=bool(play.raw_data),
    )


def play_to_detail(play: SportsGamePlay) -> PlayDetail:
    """Convert a play to detail format."""
    return PlayDetail(
        play_index=play.play_index,
        quarter=play.quarter,
        game_clock=play.game_clock,
        play_type=play.play_type,
        team_abbreviation=play.team.abbreviation if play.team else None,
        team_id=play.team_id,
        team_name=play.team.name if play.team else None,
        player_name=play.player_name,
        player_id=play.player_id,
        description=play.description,
        score=_score_obj(play.home_score, play.away_score),
        raw_data=play.raw_data or {},
        created_at=play.created_at.isoformat(),
        updated_at=play.updated_at.isoformat(),
    )


def build_resolution_issues(
    plays: list[SportsGamePlay],
    issue_type: str = "all",
) -> dict[str, Any]:
    """Categorize resolution issues from PBP plays.

    Scans plays for missing team resolution, missing player names,
    missing scores, and missing game clocks.

    Args:
        plays: List of game plays (with team relationship loaded)
        issue_type: Filter type — "team", "player", "score", "clock", or "all"

    Returns:
        Dict with issues by category and summary counts
    """
    issues: dict[str, list[dict[str, Any]]] = {
        "team_unresolved": [],
        "player_missing": [],
        "score_missing": [],
        "clock_missing": [],
    }

    for play in plays:
        play_info = {
            "play_index": play.play_index,
            "quarter": play.quarter,
            "description": play.description[:100] if play.description else None,
        }

        # Team resolution issues
        if issue_type in ("all", "team") and play.team_id is None and play.description:
            raw_team = play.raw_data.get("teamTricode") or play.raw_data.get("team")
            if raw_team:
                issues["team_unresolved"].append(
                    {
                        **play_info,
                        "raw_team": raw_team,
                        "issue": "Team abbreviation in raw data but not resolved",
                    }
                )

        # Player issues
        if (
            issue_type in ("all", "player")
            and not play.player_name
            and play.description
            and play.play_type
            and play.play_type not in (
                "timeout",
                "substitution",
                "period_start",
                "period_end",
            )
        ):
            issues["player_missing"].append(
                {
                    **play_info,
                    "play_type": play.play_type,
                    "issue": "Expected player name but not found",
                }
            )

        # Score issues
        if issue_type in ("all", "score") and (play.home_score is None or play.away_score is None):
            issues["score_missing"].append(
                {
                    **play_info,
                    "issue": "Missing score information",
                }
            )

        # Clock issues
        if issue_type in ("all", "clock") and not play.game_clock:
            issues["clock_missing"].append(
                {
                    **play_info,
                    "issue": "Missing game clock",
                }
            )

    # Filter by requested type
    if issue_type != "all":
        filtered = {
            issue_type: issues.get(f"{issue_type}_unresolved", [])
            or issues.get(f"{issue_type}_missing", [])
        }
        issues = filtered

    return {
        "issues": issues,
        "summary": {
            "team_unresolved": len(issues.get("team_unresolved", [])),
            "player_missing": len(issues.get("player_missing", [])),
            "score_missing": len(issues.get("score_missing", [])),
            "clock_missing": len(issues.get("clock_missing", [])),
        },
    }
