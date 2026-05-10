"""Pitcher-of-record reconstruction.

Given the upstream play feed and a per-pitcher `inningsPitched` summary,
walk the plays and produce, per `playIndex`, the name of the pitcher on
the mound when that play started.

Also exposes `compute_pitcher_stat_snapshots`: a per-play running
basic-line for the pitcher of record. The boxscore summary doesn't
arrive until the game ends, but every PBP at-bat carries
`matchup.pitcher`, so we walk plays in order and accumulate from the
events themselves. IP / K / BB / R / H / HR are all computable from
event_type plus the score delta. Earned runs are intentionally NOT
computed — they require the official scorer's reach-reason calls and
can't be derived live without bias.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .visual_mapper import classify_event, outs_delta_for

if TYPE_CHECKING:
    from .internal_types import TimelineEntry

__all__ = ["compute_pitcher_timeline", "compute_pitcher_stat_snapshots", "PitcherStatSnapshot"]


@dataclass(frozen=True)
class PitcherStatSnapshot:
    """Running stat line for the pitcher of record AT a specific play.

    `outs` is total outs accumulated, which renders as IP in baseball
    notation (e.g. 13 outs → "4.1"). All counts are cumulative for the
    pitcher over the plays they've thrown so far in this game.
    """

    name: str
    outs: int
    hits: int
    walks: int
    strikeouts: int
    runs: int
    home_runs: int

    @property
    def innings_pitched(self) -> str:
        """`13` outs → `"4.1"` (4 ⅓ innings)."""
        full = self.outs // 3
        part = self.outs % 3
        return f"{full}.{part}"

    def format_compact(self) -> str:
        """Header-strip rendering: "4.1 IP · 6 K · 1 BB · 2 R". Hits and
        home runs are dropped from the compact form to keep the line
        readable on phone widths; both are available on the struct if a
        wider layout wants them."""
        return f"{self.innings_pitched} IP · {self.strikeouts} K · {self.walks} BB · {self.runs} R"


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
    moment that play starts. Returns an empty map if the input is empty.

    Resolution order, in priority:
      1. The pitcher name on the play's own matchup (live PBP carries
         `matchup.pitcher` for every at-bat; the scraper writes it to
         `raw_data["pitcher"]["name"]`, which the BFF splats onto the
         play dict). This is always correct AND works for live games.
      2. The boxscore-derived `inningsPitched` reconstruction (legacy
         path that only resolves post-game). Kept as a fallback for any
         rows whose raw_data lost the pitcher field somewhere in the
         pipeline.
    """
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
        pid = play.get("playIndex", 0)

        # 1. Per-play matchup pitcher (live PBP source).
        per_play = _per_play_pitcher_name(play)
        if per_play:
            result[pid] = per_play
            # Still advance the boxscore-outs cursor so the post-game
            # fallback stays consistent for plays without raw_data.
            batting_abbr = (play.get("teamAbbreviation") or "").strip().upper()
            home_abbr = (home_team_abbr or "").strip().upper()
            pitching_team_full = (
                away_team_full
                if batting_abbr and home_abbr and batting_abbr == home_abbr
                else home_team_full
            )
            if pitching_team_full:
                event = classify_event(play)
                outs_by_team[pitching_team_full] = (
                    outs_by_team.get(pitching_team_full, 0) + outs_delta_for(event)
                )
            continue

        # 2. Boxscore-derived fallback (post-game).
        batting_abbr = (play.get("teamAbbreviation") or "").strip().upper()
        home_abbr = (home_team_abbr or "").strip().upper()
        pitching_team_full = (
            away_team_full
            if batting_abbr and home_abbr and batting_abbr == home_abbr
            else home_team_full
        )
        if not pitching_team_full:
            result[pid] = None
            continue
        plist = cum_by_team.get(pitching_team_full, [])
        outs_so_far = outs_by_team.get(pitching_team_full, 0)
        on_mound = next(
            (r for r in plist if outs_so_far < r["cum_outs"]),
            plist[-1] if plist else None,
        )
        if not on_mound:
            result[pid] = None
        else:
            result[pid] = on_mound["name"]
            event = classify_event(play)
            outs_by_team[pitching_team_full] = outs_so_far + outs_delta_for(event)

    return result


def compute_pitcher_stat_snapshots(
    plays: list[dict[str, Any]],
    pitcher_timeline: dict[int, str | None],
    timeline: dict[int, "TimelineEntry"] | None = None,
) -> dict[int, PitcherStatSnapshot]:
    """Walk plays in order and produce, per `playIndex`, the running
    stat line for the pitcher of record at that play.

    Stats are accumulated PER PITCHER NAME (so a reliever's line resets
    when they enter). The snapshot represents the line AFTER the play's
    event has been applied — i.e. for a strikeout, the snapshot at that
    play already shows the new K count and the bumped IP. The downstream
    deck builder embeds this on the play card, so the user reads "after
    this play, here's where the pitcher stood."

    Runs are pulled from `timeline[pid].runs_scored` when the timeline
    is supplied (the authoritative per-play delta). Without the
    timeline we fall through to `play.runsScoredOnPlay` only — never to
    a `score - scoreBefore` delta, because upstream play rows often
    ship the post-play running score with no scoreBefore companion, so
    the delta computes against zero and counts the cumulative tally on
    every play (the regression that produced "7 R" after a single run).

    Earned runs are intentionally absent — see module docstring.
    """
    snapshots: dict[int, PitcherStatSnapshot] = {}
    if not plays:
        return snapshots

    state: dict[str, dict[str, int]] = {}
    sorted_plays = sorted(plays, key=lambda p: p.get("playIndex", 0))
    for play in sorted_plays:
        pid = play.get("playIndex", 0)
        name = pitcher_timeline.get(pid)
        if not name:
            continue
        bucket = state.setdefault(
            name,
            {"outs": 0, "hits": 0, "walks": 0, "strikeouts": 0, "runs": 0, "home_runs": 0},
        )
        event = classify_event(play)
        bucket["outs"] += outs_delta_for(event)
        if event in ("single", "double", "triple", "home_run"):
            bucket["hits"] += 1
        if event == "home_run":
            bucket["home_runs"] += 1
        if event in ("walk", "intent_walk"):
            bucket["walks"] += 1
        if event == "strikeout":
            bucket["strikeouts"] += 1
        bucket["runs"] += _runs_charged_on_play(play, timeline)

        snapshots[pid] = PitcherStatSnapshot(
            name=name,
            outs=bucket["outs"],
            hits=bucket["hits"],
            walks=bucket["walks"],
            strikeouts=bucket["strikeouts"],
            runs=bucket["runs"],
            home_runs=bucket["home_runs"],
        )
    return snapshots


def _per_play_pitcher_name(play: dict[str, Any]) -> str | None:
    """Pull the pitcher's name from the splatted raw_data. The scraper
    writes `raw_data["pitcher"] = {"id": int|None, "name": str|None}`;
    other legacy payloads occasionally ship a bare string."""
    p = play.get("pitcher")
    if isinstance(p, dict):
        name = p.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    elif isinstance(p, str) and p.strip():
        return p.strip()
    return None


def _runs_charged_on_play(
    play: dict[str, Any],
    timeline: dict[int, "TimelineEntry"] | None,
) -> int:
    """Runs the pitcher gave up on this play. Always non-negative.

    Source priority:
      1. `timeline[pid].runs_scored` — the authoritative per-play delta
         reconstructed in `compute_timeline`. This is the only source
         that's safe when upstream rows ship the running post-play
         score with no scoreBefore companion.
      2. `play["runsScoredOnPlay"]` — set by some upstream payloads
         (Phase 3 DTO carries it; the live scraper does not).

    NOTE: we intentionally do NOT fall back to a `score - scoreBefore`
    delta. Upstream play rows often only carry the post-play running
    score, with no scoreBefore — the delta then equals the cumulative
    score and the pitcher's R accumulates that value on every play,
    producing nonsense like "7 R" after a single run scored.
    """
    if timeline is not None:
        pid = play.get("playIndex", 0)
        frame = timeline.get(pid)
        if frame is not None:
            return max(0, frame.runs_scored)
    rs = play.get("runsScoredOnPlay")
    if isinstance(rs, int) and rs >= 0:
        return rs
    return 0
