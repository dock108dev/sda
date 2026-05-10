"""Game state reconstruction.

Port of `computeTimeline` and helpers from
`scroll-down-web/web/src/lib/catchup-cards.ts`.

Forward-propagates inning, half, score, base state, runner names, and
outs across the upstream play feed. Computes scoring/tying/lead-change/
late-leverage flags used by the deck builder for force-includes.

The timeline contains full game state (including post-play scores). The
spoiler-safe DTO conversion at the service boundary strips any field that
could leak the final result.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from .internal_types import (
    HalfInningMeta,
    RunnerAdvance,
    TimelineEntry,
)
from .visual_mapper import (
    batter_dest_for_event,
    classify_animation_profile,
    classify_event,
    downgrade_implausible,
    outs_delta_for,
)

LATE_LEVERAGE_INNING = 7
EMPTY_BASES: dict[str, bool] = {"first": False, "second": False, "third": False}


# ---------------------------------------------------------------------------
# Defensive readers
# ---------------------------------------------------------------------------


def _read_num(*candidates: Any) -> int | None:
    for c in candidates:
        if isinstance(c, (int, float)) and not isinstance(c, bool):
            return int(c)
    return None


def _read_str(*candidates: Any) -> str | None:
    for c in candidates:
        if isinstance(c, str) and c.strip():
            return c.strip()
    return None


_BASE_KEYS: dict[str, str] = {
    "1": "first",
    "2": "second",
    "3": "third",
    "first": "first",
    "second": "second",
    "third": "third",
    "1b": "first",
    "2b": "second",
    "3b": "third",
}


def _read_base_state(raw: Any) -> dict[str, bool] | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        if "first" in raw or "second" in raw or "third" in raw:
            return {
                "first": bool(raw.get("first")),
                "second": bool(raw.get("second")),
                "third": bool(raw.get("third")),
            }
    if isinstance(raw, list):
        occupied: dict[str, bool] = {"first": False, "second": False, "third": False}
        for entry in raw:
            key: str | None = None
            if isinstance(entry, str):
                key = entry
            elif isinstance(entry, dict):
                v = entry.get("base")
                if v is None:
                    v = entry.get("on")
                if v is not None:
                    key = str(v)
            if not key:
                continue
            norm = _BASE_KEYS.get(key.lower())
            if norm:
                occupied[norm] = True
        return occupied
    return None


def _read_base_state_before(play: dict[str, Any]) -> dict[str, bool] | None:
    return (
        _read_base_state(play.get("baseStateBefore"))
        or _read_base_state(play.get("runnersBefore"))
        or _read_base_state(play.get("baseRunnersBefore"))
        or _read_base_state(play.get("basesBefore"))
        or _read_base_state(play.get("runners"))
        or _read_base_state(play.get("runnersOn"))
        or _read_base_state(play.get("baseRunners"))
        or _read_base_state(play.get("bases"))
    )


def _read_base_state_after(play: dict[str, Any]) -> dict[str, bool] | None:
    return (
        _read_base_state(play.get("baseStateAfter"))
        or _read_base_state(play.get("runnersAfter"))
        or _read_base_state(play.get("baseRunnersAfter"))
        or _read_base_state(play.get("basesAfter"))
    )


def _read_upstream_runner_names(raw: Any) -> dict[str, str] | None:
    if not raw:
        return None
    if isinstance(raw, dict):
        names: dict[str, str] = {}

        def grab(slot: str, *keys: str) -> None:
            for k in keys:
                v = raw.get(k)
                if isinstance(v, str) and v.strip():
                    names[slot] = v.strip()
                    return
                if isinstance(v, dict):
                    n = v.get("name") or v.get("runnerName") or v.get("playerName")
                    if isinstance(n, str) and n.strip():
                        names[slot] = n.strip()
                        return

        grab("first", "first", "1", "1B")
        grab("second", "second", "2", "2B")
        grab("third", "third", "3", "3B")
        if names:
            return names
    if isinstance(raw, list):
        names = {}
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            base_key = str(entry.get("base") or entry.get("on") or "").lower()
            slot = (
                "first"
                if base_key in ("1", "first", "1b")
                else "second"
                if base_key in ("2", "second", "2b")
                else "third"
                if base_key in ("3", "third", "3b")
                else None
            )
            if not slot:
                continue
            name = entry.get("name") or entry.get("runnerName") or entry.get("playerName")
            if isinstance(name, str) and name.strip():
                names[slot] = name.strip()
        if names:
            return names
    return None


# ---------------------------------------------------------------------------
# Inning-half detection
# ---------------------------------------------------------------------------


def inning_half_from_upstream(
    play: dict[str, Any], home_team_abbr: str | None
) -> str | None:
    phase = (play.get("phase") or "").strip().lower()
    if phase:
        if re.match(r"^(t|top|t1|0)$", phase):
            return "top"
        if re.match(r"^(b|bot|bottom|t2|1)$", phase):
            return "bottom"
        if "top" in phase:
            return "top"
        if "bot" in phase:
            return "bottom"
    label = (play.get("periodLabel") or "").strip().upper()
    if label:
        if label.startswith("TOP") or label.startswith("T ") or label == "T":
            return "top"
        if label.startswith("BOT") or label.startswith("B ") or label == "B":
            return "bottom"
        if re.match(r"^T\d+$", label):
            return "top"
        if re.match(r"^B\d+$", label):
            return "bottom"
    team = (play.get("teamAbbreviation") or "").strip().upper()
    home = (home_team_abbr or "").strip().upper()
    if team and home:
        return "bottom" if team == home else "top"
    return None


# ---------------------------------------------------------------------------
# Description-derived runner advances
# ---------------------------------------------------------------------------

# Matches one or more capitalized tokens. Single-word names and multi-word
# names both happen in real feeds.
_NAME_PATTERN = r"[À-ɏ\p{Lu}A-Z][À-ɏ\p{L}a-zA-Z'.\-]*(?:\s+[À-ɏ\p{Lu}A-Z][À-ɏ\p{L}a-zA-Z'.\-]*)*"
# Python 're' doesn't support \p{} natively. Use a simpler approximation that
# works for ASCII + most accented Latin chars.
_NAME = r"[A-ZÀ-ɏ][a-zA-ZÀ-ɏ'.\-]*(?:\s+[A-ZÀ-ɏ][a-zA-ZÀ-ɏ'.\-]*)*"
_BASE = r"1st|first|2nd|second|3rd|third|home(?:\s+plate)?"

_RE_SCORES = re.compile(rf"({_NAME})\s+scores\b", re.UNICODE)
_RE_TO_BASE = re.compile(rf"({_NAME})\s+to\s+({_BASE})\b", re.UNICODE)
_RE_OUT_AT = re.compile(
    rf"({_NAME})\s+(?:thrown\s+out\s+at|tagged\s+out\s+at|out\s+at|forced\s+out\s+at|caught\s+stealing(?:\s+at)?|picked\s+off\s+(?:at\s+)?)\s*({_BASE})\b",
    re.UNICODE,
)


def _parse_target_base(raw: str) -> str:
    t = raw.strip().lower()
    if t in ("1st", "first"):
        return "first"
    if t in ("2nd", "second"):
        return "second"
    if t in ("3rd", "third"):
        return "third"
    return "home"


def _names_match(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    x = a.strip().lower()
    y = b.strip().lower()
    if x == y:
        return True
    x_last = x.split()[-1] if x.split() else None
    y_last = y.split()[-1] if y.split() else None
    if x_last and y_last and x_last == y_last:
        return True
    if x_last and x_last in y:
        return True
    return bool(y_last and y_last in x)


def parse_description_advances(
    description: str,
    names_before: dict[str, str],
    batter_name: str | None,
) -> list[RunnerAdvance]:
    if not description:
        return []

    def from_base_for(name: str) -> str | None:
        if _names_match(name, names_before.get("first")):
            return "first"
        if _names_match(name, names_before.get("second")):
            return "second"
        if _names_match(name, names_before.get("third")):
            return "third"
        if _names_match(name, batter_name):
            return "home"
        return None

    advances: list[RunnerAdvance] = []
    for m in _RE_SCORES.finditer(description):
        from_b = from_base_for(m.group(1))
        if from_b:
            advances.append(RunnerAdvance(from_base=from_b, to="home"))
    for m in _RE_TO_BASE.finditer(description):
        from_b = from_base_for(m.group(1))
        if not from_b:
            continue
        to = _parse_target_base(m.group(2))
        advances.append(RunnerAdvance(from_base=from_b, to=to))
    for m in _RE_OUT_AT.finditer(description):
        from_b = from_base_for(m.group(1))
        if not from_b:
            continue
        out_at = _parse_target_base(m.group(2))
        advances.append(RunnerAdvance(from_base=from_b, to="out", out_at=out_at))
    return advances


def _merge_parsed_advances(
    predicted: list[RunnerAdvance], parsed: list[RunnerAdvance]
) -> list[RunnerAdvance]:
    if not parsed:
        return predicted
    by_from: dict[str, RunnerAdvance] = {}
    for a in predicted:
        by_from[a.from_base] = a
    for a in parsed:
        by_from[a.from_base] = a
    return list(by_from.values())


# ---------------------------------------------------------------------------
# Predict + diff advances
# ---------------------------------------------------------------------------


def _predict_advances(
    before: dict[str, bool], raw_event: str, profile: str | None
) -> list[RunnerAdvance]:
    event = downgrade_implausible(before, raw_event)
    advances: list[RunnerAdvance] = []
    advance_bases = (
        1 if event == "single"
        else 2 if event == "double"
        else 3 if event == "triple"
        else 4 if event == "home_run"
        else 0
    )
    dp_fly = profile == "double_play_fly"
    dp_grounder = profile == "double_play_grounder"
    is_force_walk = event in ("walk", "hit_by_pitch", "catcher_interference")
    is_free_base = event in ("balk", "wild_pitch", "passed_ball", "error")

    if before.get("third"):
        if advance_bases >= 1 or event == "sacrifice":
            advances.append(RunnerAdvance(from_base="third", to="home"))
        elif event in ("double_play", "triple_play"):
            if dp_fly:
                advances.append(RunnerAdvance(from_base="third", to="out", out_at="home"))
        elif is_free_base or is_force_walk and before.get("first") and before.get("second"):
            advances.append(RunnerAdvance(from_base="third", to="home"))
    if before.get("second"):
        if advance_bases >= 2:
            advances.append(RunnerAdvance(from_base="second", to="home"))
        elif advance_bases >= 1:
            advances.append(RunnerAdvance(from_base="second", to="third"))
        elif event in ("double_play", "triple_play"):
            if dp_grounder:
                advances.append(
                    RunnerAdvance(from_base="second", to="out", out_at="third")
                )
        elif event == "fielders_choice":
            advances.append(
                RunnerAdvance(from_base="second", to="out", out_at="third")
            )
        elif is_free_base or is_force_walk and before.get("first"):
            advances.append(RunnerAdvance(from_base="second", to="third"))
    if before.get("first"):
        if advance_bases >= 3:
            advances.append(RunnerAdvance(from_base="first", to="home"))
        elif advance_bases == 2:
            advances.append(RunnerAdvance(from_base="first", to="third"))
        elif advance_bases == 1 or is_force_walk:
            advances.append(RunnerAdvance(from_base="first", to="second"))
        elif event in ("double_play", "triple_play"):
            advances.append(
                RunnerAdvance(
                    from_base="first",
                    to="out",
                    out_at="first" if dp_fly else "second",
                )
            )
        elif event == "fielders_choice" and not before.get("second"):
            advances.append(
                RunnerAdvance(from_base="first", to="out", out_at="second")
            )
        elif is_free_base:
            advances.append(RunnerAdvance(from_base="first", to="second"))

    if event in ("caught_stealing", "pickoff"):
        if before.get("first"):
            advances.append(
                RunnerAdvance(
                    from_base="first",
                    to="out",
                    out_at="first" if event == "pickoff" else "second",
                )
            )
        elif before.get("second"):
            advances.append(
                RunnerAdvance(
                    from_base="second",
                    to="out",
                    out_at="second" if event == "pickoff" else "third",
                )
            )
        elif before.get("third"):
            advances.append(
                RunnerAdvance(from_base="third", to="out", out_at="home")
            )

    batter_dest = batter_dest_for_event(event)
    if batter_dest:
        out_at: str | None = None
        if batter_dest == "out" and event in (
            "field_out",
            "double_play",
            "triple_play",
            "sacrifice",
        ):
            if profile in ("popup", "shallow_fly", "deep_fly", "sacrifice_fly"):
                out_at = None
            else:
                out_at = "first"
        advances.append(
            RunnerAdvance(from_base="home", to=batter_dest, out_at=out_at)
        )

    return advances


def _apply_run_constraint(
    before: dict[str, bool],
    advances: list[RunnerAdvance],
    runs_scored: int,
    event: str,
) -> list[RunnerAdvance]:
    """Reconcile advances with reported runsScored. Two-pass:
    1. Promote existing in-play advances to home (lead runner first).
    2. Add synthetic scoring advances for occupied bases without an entry.
    """
    if runs_scored <= 0:
        return advances
    out = list(advances)
    predicted_scores = sum(1 for a in out if a.to == "home")
    if predicted_scores >= runs_scored:
        return out

    from_order = {"third": 0, "second": 1, "first": 2, "home": 3}

    # Pass 1: promote existing in-play advances.
    while predicted_scores < runs_scored:
        best_idx = -1
        best_priority = float("inf")
        for i, a in enumerate(out):
            if a.to in ("home", "out"):
                continue
            if a.from_base == "home" and event != "home_run":
                continue
            p = from_order.get(a.from_base, 4)
            if p < best_priority:
                best_priority = p
                best_idx = i
        if best_idx < 0:
            break
        a = out[best_idx]
        out[best_idx] = RunnerAdvance(from_base=a.from_base, to="home", out_at=a.out_at)
        predicted_scores += 1

    # Pass 2: synthetic advances from unaccounted-for occupied bases.
    if predicted_scores < runs_scored:
        advanced_froms = {a.from_base for a in out}
        occupied_lead_first: list[str] = []
        if before.get("third"):
            occupied_lead_first.append("third")
        if before.get("second"):
            occupied_lead_first.append("second")
        if before.get("first"):
            occupied_lead_first.append("first")
        for b in occupied_lead_first:
            if predicted_scores >= runs_scored:
                break
            if b not in advanced_froms:
                out.append(RunnerAdvance(from_base=b, to="home"))
                advanced_froms.add(b)
                predicted_scores += 1

    return out


def _apply_advances(
    before: dict[str, bool], advances: list[RunnerAdvance]
) -> dict[str, bool]:
    after = dict(before)
    for adv in advances:
        if adv.from_base in ("first", "second", "third"):
            after[adv.from_base] = False
    for adv in advances:
        if adv.to in ("first", "second", "third"):
            after[adv.to] = True
    return after


def _apply_runner_names(
    before: dict[str, str],
    advances: list[RunnerAdvance],
    batter_name: str | None,
) -> dict[str, str]:
    after = dict(before)
    for adv in advances:
        if adv.from_base in ("first", "second", "third"):
            after.pop(adv.from_base, None)
    for adv in advances:
        name = (
            before.get(adv.from_base)
            if adv.from_base in ("first", "second", "third")
            else batter_name
            if adv.from_base == "home"
            else None
        )
        if not name:
            continue
        if adv.to in ("first", "second", "third"):
            after[adv.to] = name
    return after


def _diff_advances(
    before: dict[str, bool],
    names_before: dict[str, str],
    after: dict[str, bool],
    names_after: dict[str, str],
    batter_name: str | None,
    batter_dest: str | None,
    runs_scored: int,
) -> list[RunnerAdvance]:
    """Derive RunnerAdvance[] from a known before/after pair.

    Matches by name first, then falls back to lead-runner positional matching.
    Used when upstream supplies basesAfter — preferred over predicting because
    it can't lie about which runner went where.
    """
    base_rank = {"home": 0, "first": 1, "second": 2, "third": 3}
    before_slots: list[dict[str, Any]] = []
    if before.get("first"):
        before_slots.append({"base": "first", "name": names_before.get("first")})
    if before.get("second"):
        before_slots.append({"base": "second", "name": names_before.get("second")})
    if before.get("third"):
        before_slots.append({"base": "third", "name": names_before.get("third")})
    after_slots: list[dict[str, Any]] = []
    if after.get("first"):
        after_slots.append({"base": "first", "name": names_after.get("first")})
    if after.get("second"):
        after_slots.append({"base": "second", "name": names_after.get("second")})
    if after.get("third"):
        after_slots.append({"base": "third", "name": names_after.get("third")})

    advances: list[RunnerAdvance] = []
    used_after: set[int] = set()

    # Pass 1: name-match every before-slot whose name we know.
    for b in before_slots:
        if not b["name"]:
            continue
        for i, a in enumerate(after_slots):
            if i in used_after:
                continue
            if a["name"] == b["name"]:
                used_after.add(i)
                if a["base"] != b["base"]:
                    advances.append(
                        RunnerAdvance(from_base=b["base"], to=a["base"])
                    )
                break

    # Pass 2: unmatched before-slots — runner left without a destination.
    runs_to_allocate = max(
        0, runs_scored - sum(1 for a in advances if a.to == "home")
    )
    if batter_dest == "home":
        runs_to_allocate = max(0, runs_to_allocate - 1)
    used_before_bases = {a.from_base for a in advances}
    unmatched_before = [
        b for b in before_slots if b["base"] not in used_before_bases
        and not any(
            i not in used_after and after_slots[i]["base"] == b["base"]
            for i in range(len(after_slots))
        )
    ]
    unmatched_before.sort(key=lambda x: -base_rank[x["base"]])
    for b in unmatched_before:
        if runs_to_allocate > 0:
            advances.append(RunnerAdvance(from_base=b["base"], to="home"))
            runs_to_allocate -= 1
        else:
            advances.append(RunnerAdvance(from_base=b["base"], to="out"))

    # Pass 3: batter destination.
    if batter_name and batter_dest and batter_dest not in ("out", "home"):
        advances.append(RunnerAdvance(from_base="home", to=batter_dest))
    elif batter_dest == "home":
        advances.append(RunnerAdvance(from_base="home", to="home"))
    elif batter_dest == "out":
        advances.append(RunnerAdvance(from_base="home", to="out"))

    return advances


# ---------------------------------------------------------------------------
# Pitcher of record reconstruction
# ---------------------------------------------------------------------------


def _innings_pitched_to_outs(ip: Any) -> int:
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


# ---------------------------------------------------------------------------
# Main: compute_timeline
# ---------------------------------------------------------------------------


def _who_is_leading(home: int, away: int) -> str:
    if home > away:
        return "home"
    if away > home:
        return "away"
    return "tie"


def compute_timeline(
    plays: list[dict[str, Any]], home_team_abbr: str | None
) -> dict[int, TimelineEntry]:
    """Forward walk over every upstream play.

    Computes inning, half, outs, scores, base state, runner names, and
    selection flags (scoring/tying/lead-change/late-leverage) at every step.
    """
    result: dict[int, TimelineEntry] = {}
    if not plays:
        return result

    sorted_plays = sorted(plays, key=lambda p: p.get("playIndex", 0))

    state_inning = sorted_plays[0].get("quarter") or 1
    state_half: str = "top"
    outs_in_half = 0
    state_score = {"home": 0, "away": 0}
    state_bases = dict(EMPTY_BASES)
    state_runners: dict[str, str] = {}

    def reset_half() -> None:
        nonlocal outs_in_half, state_bases, state_runners
        outs_in_half = 0
        state_bases = dict(EMPTY_BASES)
        state_runners = {}

    for play in sorted_plays:
        event = classify_event(play)
        upstream_half = inning_half_from_upstream(play, home_team_abbr)
        upstream_inning = play.get("quarter") or state_inning

        # Inning advance / half rotation.
        if upstream_inning != state_inning:
            state_inning = upstream_inning
            state_half = upstream_half or "top"
            reset_half()
        elif upstream_half and upstream_half != state_half:
            state_half = upstream_half
            reset_half()
        elif not upstream_half and outs_in_half >= 3:
            state_half = "bottom" if state_half == "top" else "top"
            reset_half()

        inning = state_inning
        half = state_half
        outs_before = outs_in_half

        # scoreBefore — prefer upstream, else running state.
        upstream_score_before = None
        sb = play.get("scoreBefore")
        if isinstance(sb, dict):
            h = sb.get("home")
            a = sb.get("away")
            if isinstance(h, (int, float)) and isinstance(a, (int, float)):
                upstream_score_before = {"home": int(h), "away": int(a)}
        if upstream_score_before is None:
            hsb = play.get("homeScoreBefore")
            asb = play.get("awayScoreBefore")
            if isinstance(hsb, (int, float)) and isinstance(asb, (int, float)):
                upstream_score_before = {"home": int(hsb), "away": int(asb)}
        score_before = upstream_score_before or dict(state_score)

        # scoreAfter.
        score_after = score_before
        s = play.get("score")
        if (
            isinstance(s, dict)
            and isinstance(s.get("home"), (int, float))
            and isinstance(s.get("away"), (int, float))
        ):
            score_after = {"home": int(s["home"]), "away": int(s["away"])}
        elif isinstance(play.get("homeScore"), (int, float)) and isinstance(
            play.get("awayScore"), (int, float)
        ):
            score_after = {
                "home": int(play["homeScore"]),
                "away": int(play["awayScore"]),
            }
        elif isinstance(play.get("pointsScored"), (int, float)) and play["pointsScored"] > 0:
            pts = int(play["pointsScored"])
            scoring_abbr = play.get("scoringTeamAbbr")
            if scoring_abbr and home_team_abbr:
                if scoring_abbr == home_team_abbr:
                    score_after = {
                        "home": score_before["home"] + pts,
                        "away": score_before["away"],
                    }
                else:
                    score_after = {
                        "home": score_before["home"],
                        "away": score_before["away"] + pts,
                    }
            else:
                home_add = pts if half == "bottom" else 0
                away_add = pts if half == "top" else 0
                score_after = {
                    "home": score_before["home"] + home_add,
                    "away": score_before["away"] + away_add,
                }

        runs_scored = max(
            0,
            (score_after["home"] - score_before["home"])
            + (score_after["away"] - score_before["away"]),
        )

        # Bases entering / leaving.
        upstream_base_before = _read_base_state_before(play)
        base_state_before = upstream_base_before or dict(state_bases)
        upstream_base_after = _read_base_state_after(play)
        profile = classify_animation_profile(event, play.get("description") or "")

        # Runner names.
        upstream_names_before = (
            _read_upstream_runner_names(play.get("runnersBefore"))
            or _read_upstream_runner_names(play.get("baseRunnersBefore"))
            or _read_upstream_runner_names(play.get("runners"))
            or _read_upstream_runner_names(play.get("runnersOn"))
            or _read_upstream_runner_names(play.get("baseRunners"))
            or _read_upstream_runner_names(play.get("bases"))
        )
        runner_names_before = upstream_names_before or dict(state_runners)
        batter_name = _read_str(
            play.get("batterName"), play.get("batter"), play.get("playerName")
        )

        upstream_names_after = _read_upstream_runner_names(
            play.get("runnersAfter")
        ) or _read_upstream_runner_names(play.get("baseRunnersAfter"))

        if upstream_base_after:
            predicted_advances = _diff_advances(
                base_state_before,
                runner_names_before,
                upstream_base_after,
                upstream_names_after or {},
                batter_name,
                batter_dest_for_event(event),
                runs_scored,
            )
        else:
            predicted_advances = _predict_advances(base_state_before, event, profile)

        parsed = parse_description_advances(
            play.get("description") or "", runner_names_before, batter_name
        )
        predicted_advances = _merge_parsed_advances(predicted_advances, parsed)
        predicted_advances = _apply_run_constraint(
            base_state_before, predicted_advances, runs_scored, event
        )

        base_state_after = upstream_base_after or _apply_advances(
            base_state_before, predicted_advances
        )
        runner_names_after = upstream_names_after or _apply_runner_names(
            runner_names_before, predicted_advances, batter_name
        )

        upstream_outs_after = _read_num(play.get("outsAfter"))
        outs_after = (
            min(3, upstream_outs_after)
            if upstream_outs_after is not None
            else min(3, outs_before + outs_delta_for(event))
        )

        is_scoring_play = runs_scored > 0
        leading_before = _who_is_leading(score_before["home"], score_before["away"])
        leading_after = _who_is_leading(score_after["home"], score_after["away"])
        is_tying_play = (
            is_scoring_play and leading_after == "tie" and leading_before != "tie"
        )
        is_lead_change_play = (
            is_scoring_play
            and leading_before != leading_after
            and leading_before != "tie"
            and leading_after != "tie"
        )
        close_game = abs(score_before["home"] - score_before["away"]) <= 2
        is_late_leverage = (
            inning >= LATE_LEVERAGE_INNING
            and close_game
            and (
                is_scoring_play
                or event in ("home_run", "triple", "walk", "single", "double")
            )
        )

        result[play.get("playIndex", 0)] = TimelineEntry(
            play_index=int(play.get("playIndex", 0)),
            inning=inning,
            half=half,
            outs_before=outs_before,
            outs_after=outs_after,
            score_before_home=score_before["home"],
            score_before_away=score_before["away"],
            score_after_home=score_after["home"],
            score_after_away=score_after["away"],
            base_state_before=base_state_before,
            base_state_after=base_state_after,
            runner_names_before=runner_names_before,
            runner_names_after=runner_names_after,
            advances=predicted_advances,
            event_type=event,
            runs_scored=runs_scored,
            is_scoring_play=is_scoring_play,
            is_tying_play=is_tying_play,
            is_lead_change_play=is_lead_change_play,
            is_late_leverage=is_late_leverage,
            half_from_upstream=upstream_half is not None,
        )

        # Advance state.
        state_score = score_after
        state_bases = base_state_after
        state_runners = runner_names_after
        outs_in_half = outs_after
        if outs_in_half >= 3:
            state_half = "bottom" if state_half == "top" else "top"
            reset_half()

    return result


def summarize_half_innings(
    entries: Iterable[TimelineEntry],
) -> dict[str, HalfInningMeta]:
    """Build the half-inning meta map for the rhythm planner."""
    result: dict[str, HalfInningMeta] = {}
    for e in entries:
        key = f"{e.inning}:{e.half}"
        meta = result.get(key) or HalfInningMeta()
        meta.scored_runs += e.runs_scored
        meta.had_activity = True
        if e.is_lead_change_play:
            meta.had_lead_change = True
        if e.is_tying_play:
            meta.had_tying = True
        result[key] = meta
    return result


__all__ = [
    "compute_pitcher_timeline",
    "compute_timeline",
    "inning_half_from_upstream",
    "parse_description_advances",
    "summarize_half_innings",
]
