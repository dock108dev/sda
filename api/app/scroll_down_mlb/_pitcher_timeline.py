"""Pitcher-of-record reconstruction.

Given the upstream play feed and a per-pitcher `inningsPitched` summary,
walk the plays and produce, per `playIndex`, the name of the pitcher on
the mound when that play started.
"""

from __future__ import annotations

import re
from typing import Any

from .visual_mapper import classify_event, outs_delta_for

__all__ = ["compute_pitcher_timeline"]


def _innings_pitched_to_outs(ip: Any) -> int:
    """Convert an `inningsPitched` value (e.g. "5.2") to total outs."""
    if ip is None:
        return 0
    m = re.match(r"^(\d+)(?:\.(\d))?$", str(ip).strip())
    if not m:
        return 0
    innings = int(m.group(1))
    part = int(m.group(2)) if m.group(2) else 0
    return innings * 3 + part


def compute_pitcher_timeline(
    plays: list[dict[str, Any]],
    pitchers: list[dict[str, Any]] | None,
    home_team_full: str | None,
    away_team_full: str | None,
    home_team_abbr: str | None,
) -> dict[int, str | None]:
    """Walk plays and produce, per playIndex, the pitcher of record at the
    moment that play starts. Returns an empty map if the input is empty."""
    result: dict[int, str | None] = {}
    if not plays:
        return result

    by_team: dict[str, list[dict[str, Any]]] = {}
    if pitchers:
        for p in pitchers:
            team = (p.get("team") or "").strip()
            name = p.get("playerName")
            if not team or not name:
                continue
            outs = _innings_pitched_to_outs(p.get("inningsPitched"))
            by_team.setdefault(team, []).append(
                {"name": name.strip(), "outs_threshold": outs}
            )

    cum_by_team: dict[str, list[dict[str, Any]]] = {}
    for team, lst in by_team.items():
        acc = 0
        cum: list[dict[str, Any]] = []
        for r in lst:
            acc += r["outs_threshold"]
            cum.append({"name": r["name"], "cum_outs": acc})
        cum_by_team[team] = cum

    outs_by_team: dict[str, int] = {}
    sorted_plays = sorted(plays, key=lambda p: p.get("playIndex", 0))
    for play in sorted_plays:
        batting_abbr = (play.get("teamAbbreviation") or "").strip().upper()
        home_abbr = (home_team_abbr or "").strip().upper()
        pitching_team_full = (
            away_team_full
            if batting_abbr and home_abbr and batting_abbr == home_abbr
            else home_team_full
        )
        if not pitching_team_full:
            result[play.get("playIndex", 0)] = None
            continue
        plist = cum_by_team.get(pitching_team_full, [])
        outs_so_far = outs_by_team.get(pitching_team_full, 0)
        on_mound = next(
            (r for r in plist if outs_so_far < r["cum_outs"]),
            plist[-1] if plist else None,
        )
        if not on_mound:
            result[play.get("playIndex", 0)] = None
        else:
            result[play.get("playIndex", 0)] = on_mound["name"]
            event = classify_event(play)
            outs_by_team[pitching_team_full] = outs_so_far + outs_delta_for(event)

    return result
