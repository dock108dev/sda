"""Game state reconstruction.

Port of `computeTimeline` and helpers from
`scroll-down-web/web/src/lib/catchup-cards.ts`.

Forward-propagates inning, half, score, base state, runner names, and
outs across the upstream play feed. Computes scoring/tying/lead-change/
late-leverage flags used by the deck builder for force-includes.

The timeline contains full game state (including post-play scores). The
spoiler-safe DTO conversion at the service boundary strips any field that
could leak the final result.

Implementation is split for size:
  * `_state_readers` — defensive readers for upstream play-dict shapes
  * `_advances`      — runner-advance derivation (parse / predict / diff)
  * `_pitcher_timeline` — pitcher-of-record reconstruction
This module owns `compute_timeline` + `summarize_half_innings` and
re-exports the rest as the public surface.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ._advances import (
    apply_advances,
    apply_run_constraint,
    apply_runner_names,
    diff_advances,
    merge_parsed_advances,
    parse_description_advances,
    predict_advances,
)
from ._pitcher_timeline import compute_pitcher_timeline
from ._state_readers import (
    EMPTY_BASES,
    inning_half_from_upstream,
    read_base_state_after,
    read_base_state_before,
    read_num,
    read_str,
    read_upstream_runner_names,
)
from .internal_types import HalfInningMeta, TimelineEntry
from .visual_mapper import (
    batter_dest_for_event,
    classify_animation_profile,
    classify_event,
    outs_delta_for,
)

LATE_LEVERAGE_INNING = 7

__all__ = [
    "LATE_LEVERAGE_INNING",
    "compute_pitcher_timeline",
    "compute_timeline",
    "inning_half_from_upstream",
    "parse_description_advances",
    "summarize_half_innings",
]


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
            if isinstance(h, int | float) and isinstance(a, int | float):
                upstream_score_before = {"home": int(h), "away": int(a)}
        if upstream_score_before is None:
            hsb = play.get("homeScoreBefore")
            asb = play.get("awayScoreBefore")
            if isinstance(hsb, int | float) and isinstance(asb, int | float):
                upstream_score_before = {"home": int(hsb), "away": int(asb)}
        score_before = upstream_score_before or dict(state_score)

        # scoreAfter.
        score_after = score_before
        s = play.get("score")
        if (
            isinstance(s, dict)
            and isinstance(s.get("home"), int | float)
            and isinstance(s.get("away"), int | float)
        ):
            score_after = {"home": int(s["home"]), "away": int(s["away"])}
        elif isinstance(play.get("homeScore"), int | float) and isinstance(
            play.get("awayScore"), int | float
        ):
            score_after = {
                "home": int(play["homeScore"]),
                "away": int(play["awayScore"]),
            }
        elif isinstance(play.get("pointsScored"), int | float) and play["pointsScored"] > 0:
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
        upstream_base_before = read_base_state_before(play)
        base_state_before = upstream_base_before or dict(state_bases)
        upstream_base_after = read_base_state_after(play)
        profile = classify_animation_profile(event, play.get("description") or "")

        # Runner names.
        upstream_names_before = (
            read_upstream_runner_names(play.get("runnersBefore"))
            or read_upstream_runner_names(play.get("baseRunnersBefore"))
            or read_upstream_runner_names(play.get("runners"))
            or read_upstream_runner_names(play.get("runnersOn"))
            or read_upstream_runner_names(play.get("baseRunners"))
            or read_upstream_runner_names(play.get("bases"))
        )
        runner_names_before = upstream_names_before or dict(state_runners)
        batter_name = read_str(
            play.get("batterName"), play.get("batter"), play.get("playerName")
        )

        upstream_names_after = read_upstream_runner_names(
            play.get("runnersAfter")
        ) or read_upstream_runner_names(play.get("baseRunnersAfter"))

        if upstream_base_after:
            predicted_advances = diff_advances(
                base_state_before,
                runner_names_before,
                upstream_base_after,
                upstream_names_after or {},
                batter_name,
                batter_dest_for_event(event),
                runs_scored,
            )
        else:
            predicted_advances = predict_advances(base_state_before, event, profile)

        parsed = parse_description_advances(
            play.get("description") or "", runner_names_before, batter_name
        )
        predicted_advances = merge_parsed_advances(predicted_advances, parsed)
        predicted_advances = apply_run_constraint(
            base_state_before, predicted_advances, runs_scored, event
        )

        base_state_after = upstream_base_after or apply_advances(
            base_state_before, predicted_advances
        )
        runner_names_after = upstream_names_after or apply_runner_names(
            runner_names_before, predicted_advances, batter_name
        )

        upstream_outs_after = read_num(play.get("outsAfter"))
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
