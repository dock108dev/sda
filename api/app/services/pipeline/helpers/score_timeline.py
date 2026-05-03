"""Deterministic per-play score and lead timeline helper.

Consumes normalized PBP events (NORMALIZE_PBP output) and aggregates them into a
queryable timeline structure. Downstream consumers (game-shape classification,
boundary selection, evidence selection) read this aggregated view rather than
re-deriving lead/score state per stage.

The primitive lead/score predicates live in
``api/app/services/pipeline/stages/score_detection.py`` — this module imports
them rather than duplicating the logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, NamedTuple

from ..stages.league_config import LEAGUE_CONFIG, get_config, get_flow_thresholds
from ..stages.score_detection import is_lead_change_play, is_scoring_play


class ScorePoint(NamedTuple):
    """Score state at a single play.

    ``lead`` is signed: positive => home leading by that margin,
    negative => away leading, zero => tied.
    """

    play_index: int
    home_score: int
    away_score: int
    lead: int


class LeadChangeEvent(NamedTuple):
    """A play that flipped the lead between teams.

    Only emitted when both the previous and current state had a leader and they
    differed — going tied->lead or lead->tied is not a lead change (matches
    ``score_detection.is_lead_change`` semantics).
    """

    play_index: int
    previous_lead: int
    new_lead: int
    scoring_team: str | None


class ScoringDrought(NamedTuple):
    """A maximal contiguous interval of plays with no score change.

    ``period`` is the period/inning at the drought's start (NBA quarter, MLB
    inning, NHL period, etc.).
    """

    start_idx: int
    end_idx: int
    period: int


class TiedInterval(NamedTuple):
    """A maximal contiguous interval of plays where ``lead == 0``."""

    start_idx: int
    end_idx: int


@dataclass(frozen=True)
class ScoreTimeline:
    """Aggregated per-game score/lead view derived from normalized PBP."""

    per_play: list[ScorePoint] = field(default_factory=list)
    lead_change_events: list[LeadChangeEvent] = field(default_factory=list)
    scoring_droughts: list[ScoringDrought] = field(default_factory=list)
    tied_intervals: list[TiedInterval] = field(default_factory=list)
    peak_lead: int = 0
    peak_lead_idx: int | None = None
    first_meaningful_lead_idx: int | None = None


def _score_pair(event: dict[str, Any]) -> tuple[int, int]:
    home = event.get("home_score") or 0
    away = event.get("away_score") or 0
    return home, away


def _lookup_meaningful_lead(league_code: str) -> int:
    """Resolve the meaningful-lead threshold for a league.

    Falls back to NBA when the code is unknown — consistent with the existing
    league_config pattern (per MEMORY.md: unknown leagues fall back to NBA).
    """
    code = (league_code or "NBA").upper()
    if code in LEAGUE_CONFIG:
        return int(get_config(code)["meaningful_lead"])
    return int(LEAGUE_CONFIG["NBA"]["meaningful_lead"])


def lookup_lead_created_threshold(league_code: str) -> int:
    """Resolve the 'first meaningful lead creation' threshold for a league.

    Used by boundary selection (moment-level HARD trigger and block-level
    candidates). Distinct from ``meaningful_lead``: this is the smaller margin
    that signals the first time one team has built any real cushion (NBA: 6,
    MLB: 2 runs / multi_run_inning, NCAAB: 6). Unknown leagues fall back to
    the league's configured ``meaningful_lead``.
    """
    flow = get_flow_thresholds(league_code)
    if "lead_created" in flow:
        return int(flow["lead_created"])
    if "multi_run_inning" in flow:
        return int(flow["multi_run_inning"])
    return _lookup_meaningful_lead(league_code)


def find_first_lead_created_play_idx(
    events: list[dict[str, Any]],
    league_code: str = "NBA",
) -> int | None:
    """Return play_index of first event where |lead| >= the lead-created threshold.

    Pure function over normalized PBP. Returns ``None`` if no event ever
    reaches the threshold (e.g., a tied or single-possession game).
    """
    if not events:
        return None
    threshold = lookup_lead_created_threshold(league_code)
    for ev in events:
        h = ev.get("home_score") or 0
        a = ev.get("away_score") or 0
        if abs(h - a) >= threshold:
            return ev.get("play_index")
    return None


def build_score_timeline(
    events: list[dict[str, Any]],
    league_code: str = "NBA",
) -> ScoreTimeline:
    """Aggregate normalized PBP events into a score/lead timeline.

    Pure function: same input always produces the same output. Events are
    expected to be ordered as emitted by NORMALIZE_PBP (already sorted by
    ``play_index``); ordering is preserved, not enforced.

    Args:
        events: Normalized PBP events with ``home_score``, ``away_score``,
            ``play_index``, ``quarter``, ``team_abbreviation``.
        league_code: League code used to resolve the meaningful-lead threshold.

    Returns:
        A ``ScoreTimeline`` aggregating per-play state, lead changes, scoring
        droughts, tied intervals, peak lead, and the first meaningful-lead play.
    """
    if not events:
        return ScoreTimeline()

    meaningful_lead = _lookup_meaningful_lead(league_code)

    per_play: list[ScorePoint] = []
    lead_changes: list[LeadChangeEvent] = []
    droughts: list[ScoringDrought] = []
    tied: list[TiedInterval] = []

    peak_lead = 0
    peak_lead_idx: int | None = None
    first_meaningful_idx: int | None = None

    drought_start_idx: int | None = None
    drought_start_period: int | None = None
    tie_start_idx: int | None = None

    prev_event: dict[str, Any] | None = None
    prev_play_index: int | None = None

    for i, event in enumerate(events):
        home, away = _score_pair(event)
        lead = home - away
        play_idx = event.get("play_index", i)
        period = event.get("quarter") or 1

        per_play.append(ScorePoint(play_idx, home, away, lead))

        if is_lead_change_play(event, prev_event):
            prev_home, prev_away = _score_pair(prev_event) if prev_event else (0, 0)
            lead_changes.append(
                LeadChangeEvent(
                    play_index=play_idx,
                    previous_lead=prev_home - prev_away,
                    new_lead=lead,
                    scoring_team=event.get("team_abbreviation"),
                )
            )

        # Peak lead by absolute margin; first occurrence wins on ties so peak_lead_idx
        # reflects the earliest play that hit that margin.
        if abs(lead) > peak_lead:
            peak_lead = abs(lead)
            peak_lead_idx = play_idx

        if first_meaningful_idx is None and abs(lead) >= meaningful_lead:
            first_meaningful_idx = play_idx

        if lead == 0:
            if tie_start_idx is None:
                tie_start_idx = play_idx
        else:
            if tie_start_idx is not None:
                tie_end = prev_play_index if prev_play_index is not None else tie_start_idx
                tied.append(TiedInterval(tie_start_idx, tie_end))
                tie_start_idx = None

        scoring = is_scoring_play(event, prev_event)
        if scoring:
            if drought_start_idx is not None:
                drought_end = prev_play_index if prev_play_index is not None else drought_start_idx
                droughts.append(
                    ScoringDrought(
                        start_idx=drought_start_idx,
                        end_idx=drought_end,
                        period=drought_start_period or 1,
                    )
                )
                drought_start_idx = None
                drought_start_period = None
        else:
            if drought_start_idx is None:
                drought_start_idx = play_idx
                drought_start_period = period

        prev_event = event
        prev_play_index = play_idx

    if tie_start_idx is not None:
        tie_end = prev_play_index if prev_play_index is not None else tie_start_idx
        tied.append(TiedInterval(tie_start_idx, tie_end))

    if drought_start_idx is not None:
        drought_end = prev_play_index if prev_play_index is not None else drought_start_idx
        droughts.append(
            ScoringDrought(
                start_idx=drought_start_idx,
                end_idx=drought_end,
                period=drought_start_period or 1,
            )
        )

    return ScoreTimeline(
        per_play=per_play,
        lead_change_events=lead_changes,
        scoring_droughts=droughts,
        tied_intervals=tied,
        peak_lead=peak_lead,
        peak_lead_idx=peak_lead_idx,
        first_meaningful_lead_idx=first_meaningful_idx,
    )
