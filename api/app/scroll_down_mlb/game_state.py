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
    build_base_movements,
    diff_advances,
    merge_parsed_advances,
    parse_description_advances,
    predict_advances,
)
from ._classify import build_event_result, classify_reveal_type
from ._pitcher_timeline import compute_pitcher_stat_snapshots, compute_pitcher_timeline
from ._state_readers import (
    EMPTY_BASES,
    inning_half_from_upstream,
    normalize_runner_label,
    read_base_state_after,
    read_base_state_before,
    read_count,
    read_count_before,
    read_num,
    read_str,
    read_upstream_runner_names,
    read_upstream_runner_names_before,
)
from .internal_types import HalfInningMeta, TimelineEntry
from .schemas import (
    BasesSituation,
    BaseState,
    CountSituation,
    GameSituation,
    GameSituationAfter,
    HalfInningEvent,
    HalfInningMetaPayload,
    PlayerSummary,
    RunnerSummary,
    ScoreChange,
    ScoreSituation,
    ScoreState,
    ScrollDownEventMatchup,
    ScrollDownHalfInningContainer,
    TeamSummary,
)
from .visual_mapper import (
    batter_dest_for_event,
    classify_animation_profile,
    classify_event,
    outs_delta_for,
)

LATE_LEVERAGE_INNING = 7

# Plate-appearance-terminating event classes. Used to reset the running
# count tracker at PA boundaries — once a PA ends, the next play (a
# new PA or a between-PA event) starts at 0-0.
_PA_ENDING_EVENTS: frozenset[str] = frozenset(
    {
        "single",
        "double",
        "triple",
        "home_run",
        "walk",
        "hit_by_pitch",
        "strikeout",
        "field_out",
        "fielders_choice",
        "sacrifice",
        "error",
        "double_play",
        "triple_play",
        "catcher_interference",
    }
)

__all__ = [
    "LATE_LEVERAGE_INNING",
    "_group_into_containers",
    "compute_pitcher_stat_snapshots",
    "compute_pitcher_timeline",
    "compute_timeline",
    "inning_half_from_upstream",
    "parse_description_advances",
    "summarize_half_innings",
]

# Sort key for half-inning ordering: top before bottom within the same
# inning. `sorted()` on the half string alone would put "bottom" first.
_HALF_SORT_ORDER = {"top": 0, "bottom": 1}


def _who_is_leading(home: int, away: int) -> str:
    if home > away:
        return "home"
    if away > home:
        return "away"
    return "tie"


def _bases_situation(
    occupancy: dict[str, bool],
    names: dict[str, str],
) -> BasesSituation:
    """Build a `BasesSituation` from internal occupancy + name dicts.

    `RunnerSummary.id` is left None — upstream player IDs are not yet
    wired through `_state_readers` (handled in a later issue). Empty-name
    runners on an occupied base still get a `RunnerSummary` (with empty
    `name`) so the renderer can show the bulb without a label.
    """
    def _slot(key: str) -> RunnerSummary | None:
        if not occupancy.get(key):
            return None
        return RunnerSummary(id=None, name=names.get(key, "") or "")

    return BasesSituation(
        first=_slot("first"),
        second=_slot("second"),
        third=_slot("third"),
    )


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
    # Running pitch-count tracker. Always (0, 0) at the start of a new
    # plate appearance; advanced to the upstream-reported count after
    # each mid-PA play (e.g. a pitch event) and reset to (0, 0) after
    # any PA-terminating event. The wire payload still only carries the
    # count on plays where upstream actually provided it — this state
    # exists so `situation_before.count` reflects the running pre-play
    # count when upstream supplies post-play counts mid-PA.
    state_count_balls = 0
    state_count_strikes = 0

    def reset_half() -> None:
        nonlocal outs_in_half, state_bases, state_runners
        nonlocal state_count_balls, state_count_strikes
        outs_in_half = 0
        state_bases = dict(EMPTY_BASES)
        state_runners = {}
        state_count_balls = 0
        state_count_strikes = 0

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

        # scoreBefore — prefer upstream `*Before` keys, else fall back to
        # the prior play's `score_after` (running state). `pointsScored`
        # is intentionally never read here; it informs score_after only,
        # and only when a team can be reliably attributed.
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
            # `pointsScored` is consulted only when an explicit team
            # attribution is available — `scoringTeamAbbr` + a known
            # `home_team_abbr`. Without both, the half-inning heuristic
            # is unsafe (corrupts every downstream score_before when
            # half was itself heuristically derived), so we leave
            # score_after = score_before rather than guess.
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

        runs_scored = max(
            0,
            (score_after["home"] - score_before["home"])
            + (score_after["away"] - score_before["away"]),
        )

        # Bases entering / leaving. Before-state uses only the explicit
        # `*Before` variants; ambiguous keys (`runners`, `runnersOn`,
        # `baseRunners`, `bases`) are never read as before-state because
        # some vendor feeds emit them post-play. Fall back to the prior
        # play's `situation_after.bases` via the running `state_bases`.
        upstream_base_before = read_base_state_before(play)
        base_state_before = upstream_base_before or dict(state_bases)
        upstream_base_after = read_base_state_after(play)
        profile = classify_animation_profile(event, play.get("description") or "")

        # Runner names — same trust tier as base-state-before.
        upstream_names_before = read_upstream_runner_names_before(play)
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

        # Snapshots — deterministic wire-facing summaries. `situation_before`
        # carries the running pre-play score (already public via prior cards).
        # `situation_after` uses the score-less `GameSituationAfter` type so
        # the post-play cumulative score cannot leak; the renderer reconstructs
        # it from `score_before + score_change` post-reveal.
        #
        # Count handling: explicit `*Before` keys override the running count
        # tracker for this play. Ambiguous `balls`/`strikes`/`count` keys
        # carry the post-play count (e.g. MLB stats API per-pitch shape).
        # `situation_before.count` is the pre-play state; `situation_after.count`
        # is the upstream post-play count when present, and is forced to `None`
        # on PA-terminating events (the count is no longer applicable once the
        # batter has either reached, walked, or been retired).
        upstream_count_before = read_count_before(play)
        if upstream_count_before is not None:
            state_count_balls, state_count_strikes = upstream_count_before
        upstream_count_after = read_count(play)
        is_pa_ending = event in _PA_ENDING_EVENTS

        count_before: CountSituation | None
        if upstream_count_before is not None or upstream_count_after is not None:
            count_before = CountSituation(
                balls=state_count_balls, strikes=state_count_strikes
            )
        else:
            count_before = None

        count_after: CountSituation | None
        if not is_pa_ending and upstream_count_after is not None:
            count_after = CountSituation(
                balls=upstream_count_after[0],
                strikes=upstream_count_after[1],
            )
        else:
            count_after = None

        situation_before = GameSituation(
            inning=inning,
            half=half,  # type: ignore[arg-type]
            outs=outs_before,
            score=ScoreSituation(
                home=score_before["home"], away=score_before["away"]
            ),
            count=count_before,
            bases=_bases_situation(base_state_before, runner_names_before),
        )
        situation_after = GameSituationAfter(
            inning=inning,
            half=half,  # type: ignore[arg-type]
            outs=outs_after,
            count=count_after,
            bases=_bases_situation(base_state_after, runner_names_after),
        )

        # Movements are derived from the same advance list that produced
        # `base_state_after`, so they are by construction a diff of
        # `situation_before.bases` vs `situation_after.bases` (plus the
        # batter's destination from event context). The batter's identity
        # is sourced here from the per-play `batter_name` — once the
        # `matchup.batter` payload lands, swap that in without changing
        # the diff itself.
        batter_summary = (
            RunnerSummary(id=None, name=batter_name) if batter_name else None
        )
        movements = build_base_movements(
            predicted_advances, situation_before.bases, batter_summary
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
            situation_before=situation_before,
            situation_after=situation_after,
            movements=movements,
        )

        # Advance state.
        state_score = score_after
        state_bases = base_state_after
        state_runners = runner_names_after
        if is_pa_ending:
            state_count_balls = 0
            state_count_strikes = 0
        elif upstream_count_after is not None:
            state_count_balls, state_count_strikes = upstream_count_after
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


def _base_state_dto(state: dict[str, bool]) -> BaseState:
    return BaseState(
        first=bool(state.get("first")),
        second=bool(state.get("second")),
        third=bool(state.get("third")),
    )


def _player_summary(name: str | None) -> PlayerSummary | None:
    """Build a normalized `PlayerSummary` from a raw upstream name.

    Returns `None` when upstream omits a name. The label is normalized to
    `FIRST_INITIAL LAST_NAME` so all wire surfaces share one format.
    Player ID is left `None` — upstream IDs are not yet threaded through
    the pipeline.
    """
    normalized = normalize_runner_label(name) if name else None
    if not normalized:
        return None
    return PlayerSummary(id=None, name=normalized)


def _matchup_for_play(
    play: dict | None,
    pitcher_name: str | None,
) -> ScrollDownEventMatchup:
    """Resolve `(batter, pitcher)` from upstream play context."""
    batter_raw: str | None = None
    if play is not None:
        raw = (
            play.get("batterName")
            or play.get("playerName")
        )
        if isinstance(raw, str) and raw.strip():
            batter_raw = raw.strip()
        else:
            batter_obj = play.get("batter")
            if isinstance(batter_obj, dict):
                n = batter_obj.get("name")
                if isinstance(n, str) and n.strip():
                    batter_raw = n.strip()
    return ScrollDownEventMatchup(
        batter=_player_summary(batter_raw),
        pitcher=_player_summary(pitcher_name),
    )


def _event_dto(
    entry: TimelineEntry,
    sequence: int,
    selected_play_indices: set[int],
    play: dict | None,
    pitcher_name: str | None,
) -> HalfInningEvent:
    score_change = ScoreChange(
        home=entry.score_after_home - entry.score_before_home,
        away=entry.score_after_away - entry.score_before_away,
    )
    description = ""
    if play is not None:
        raw_desc = play.get("description")
        if isinstance(raw_desc, str):
            description = raw_desc
    result = build_event_result(
        event_type=entry.event_type,
        description=description,
        outs_after=entry.outs_after,
        score_change_home=score_change.home,
        score_change_away=score_change.away,
    )
    return HalfInningEvent(
        sequence=sequence,
        play_index=entry.play_index,
        event_type=entry.event_type,
        outs_before=entry.outs_before,
        outs_after=entry.outs_after,
        base_state_before=_base_state_dto(entry.base_state_before),
        base_state_after=_base_state_dto(entry.base_state_after),
        score_before=ScoreState(
            home=entry.score_before_home, away=entry.score_before_away
        ),
        runs_scored_on_play=entry.runs_scored,
        score_change=score_change,
        movements=list(entry.movements),
        reveal_type=classify_reveal_type(entry.event_type),
        result=result,
        matchup=_matchup_for_play(play, pitcher_name),
        is_selected=entry.play_index in selected_play_indices,
    )


def _group_into_containers(
    *,
    game_id: int,
    timeline: dict[int, TimelineEntry],
    selected_play_indices: set[int],
    half_meta: dict[str, HalfInningMeta],
    home_team: TeamSummary,
    away_team: TeamSummary,
    plays_by_index: dict[int, dict] | None = None,
    pitcher_by_play: dict[int, str | None] | None = None,
) -> list[ScrollDownHalfInningContainer]:
    """Group timeline entries into ordered half-inning containers.

    The container holds every event in the half-inning; the deck builder's
    curated subset is overlaid via `selectedPlayIndices` and the per-event
    `isSelected` flag. Containers are ordered by (inning, half) with the
    top half preceding the bottom half of the same inning.

    Partial trailing half-innings (live games with no inning-end signal)
    are emitted as open containers — the grouping pass treats every
    half-inning observed in the timeline uniformly regardless of whether
    its third out is captured.
    """
    buckets: dict[tuple[int, str], list[TimelineEntry]] = {}
    for entry in sorted(timeline.values(), key=lambda e: e.play_index):
        buckets.setdefault((entry.inning, entry.half), []).append(entry)

    containers: list[ScrollDownHalfInningContainer] = []
    for (inning, half), entries in sorted(
        buckets.items(),
        key=lambda kv: (kv[0][0], _HALF_SORT_ORDER.get(kv[0][1], 0)),
    ):
        meta_src = half_meta.get(f"{inning}:{half}") or HalfInningMeta()
        # Top of the inning: away batting, home fielding. Bottom: reversed.
        if half == "top":
            batting, fielding = away_team, home_team
        else:
            batting, fielding = home_team, away_team
        events = [
            _event_dto(
                entry,
                seq,
                selected_play_indices,
                (plays_by_index or {}).get(entry.play_index),
                (pitcher_by_play or {}).get(entry.play_index),
            )
            for seq, entry in enumerate(entries, start=1)
        ]
        containers.append(
            ScrollDownHalfInningContainer(
                game_id=str(game_id),
                inning=inning,
                half=half,  # type: ignore[arg-type]
                batting_team=batting,
                fielding_team=fielding,
                events=events,
                meta=HalfInningMetaPayload(
                    scored_runs=meta_src.scored_runs,
                    had_activity=meta_src.had_activity,
                    had_lead_change=meta_src.had_lead_change,
                    had_tying=meta_src.had_tying,
                ),
                selected_play_indices=sorted(
                    e.play_index
                    for e in entries
                    if e.play_index in selected_play_indices
                ),
            )
        )
    return containers
