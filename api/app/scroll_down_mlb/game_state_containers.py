"""Half-inning summary and DTO container assembly."""

from __future__ import annotations

from collections.abc import Iterable

from ._classify import build_event_result, classify_reveal_type
from ._state_readers import normalize_runner_label
from .internal_types import HalfInningMeta, TimelineEntry
from .schemas import (
    BaseState,
    HalfInningEvent,
    HalfInningMetaPayload,
    PlayerSummary,
    ScoreChange,
    ScoreState,
    ScrollDownEventMatchup,
    ScrollDownHalfInningContainer,
    TeamSummary,
)

_HALF_SORT_ORDER = {"top": 0, "bottom": 1}


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
