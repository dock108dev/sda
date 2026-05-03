"""Per-segment evidence selection for narrative generation.

Given a contiguous play range within a game and the precomputed score timeline,
extract structured evidence the prompt can consume directly: scoring plays,
lead changes, scoring runs, featured players (by delta contribution), special
markers (power-play, empty net, home run, overtime), and a leverage label
(HIGH / MEDIUM / LOW).

This is the primary "what happened in the segment" payload for downstream
narrative generation; it replaces the older approach of forwarding an
undifferentiated dump of play-by-play.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..stages.league_config import LEAGUE_CONFIG, get_flow_thresholds
from ..stages.score_detection import is_scoring_play
from .score_timeline import ScoreTimeline

LEVERAGE_HIGH = "HIGH"
LEVERAGE_MEDIUM = "MEDIUM"
LEVERAGE_LOW = "LOW"


@dataclass(frozen=True)
class ScoringPlay:
    """A play that changed the score within the segment."""

    play_index: int
    player: str | None
    team: str | None
    score_before: tuple[int, int]
    score_after: tuple[int, int]
    play_type: str | None
    is_home_run: bool = False
    is_power_play_goal: bool = False
    is_short_handed_goal: bool = False
    is_empty_net_goal: bool = False
    is_overtime: bool = False


@dataclass(frozen=True)
class LeadChangeEvidence:
    """A lead flip that occurred inside the segment."""

    play_index: int
    from_lead: int
    to_lead: int


@dataclass(frozen=True)
class ScoringRunEvidence:
    """A run of consecutive scoring plays by one team within the segment."""

    team: str | None
    points: int
    duration_plays: int
    start_play_index: int
    end_play_index: int


@dataclass(frozen=True)
class FeaturedPlayer:
    """Top contributor by delta scoring inside the segment."""

    name: str
    team: str | None
    delta_contribution: int


@dataclass(frozen=True)
class SegmentEvidence:
    """Structured evidence for a single narrative segment."""

    scoring_plays: list[ScoringPlay] = field(default_factory=list)
    lead_changes: list[LeadChangeEvidence] = field(default_factory=list)
    scoring_runs: list[ScoringRunEvidence] = field(default_factory=list)
    featured_players: list[FeaturedPlayer] = field(default_factory=list)
    leverage: str = LEVERAGE_MEDIUM
    is_overtime: bool = False
    is_scoring_run: bool = False
    is_power_play_goal: bool = False
    is_short_handed_goal: bool = False
    is_empty_net: bool = False


def _resolve_cfg(league_code: str) -> dict[str, Any]:
    code = (league_code or "NBA").upper()
    return LEAGUE_CONFIG.get(code, LEAGUE_CONFIG["NBA"])


def _detect_power_play_goal(event: dict[str, Any]) -> bool:
    """NHL: detect power-play goal from play_type or description.

    Other leagues never produce a power-play goal flag.
    """
    play_type = (event.get("play_type") or "").lower()
    desc = (event.get("description") or "").lower()
    if "power_play" in play_type or "powerplay" in play_type or "pp_goal" in play_type:
        return True
    if "power play" in desc or "power-play" in desc:
        return True
    return "(pp)" in desc or " pp " in f" {desc} "


def _detect_empty_net_goal(event: dict[str, Any]) -> bool:
    """NHL: detect empty-net goal from play_type or description."""
    play_type = (event.get("play_type") or "").lower()
    desc = (event.get("description") or "").lower()
    if "empty_net" in play_type or "empty-net" in play_type:
        return True
    if "empty net" in desc or "empty-net" in desc:
        return True
    return "(en)" in desc


def _detect_short_handed_goal(event: dict[str, Any]) -> bool:
    """NHL: detect short-handed goal from play_type or description."""
    play_type = (event.get("play_type") or "").lower()
    desc = (event.get("description") or "").lower()
    if "short_handed" in play_type or "short-handed" in play_type or "shorthanded" in play_type:
        return True
    if "short-handed" in desc or "shorthanded" in desc or "short handed" in desc:
        return True
    return "(sh)" in desc or " sh " in f" {desc} "


def _detect_home_run(event: dict[str, Any]) -> bool:
    """MLB: detect home run from play_type or description."""
    play_type = (event.get("play_type") or "").lower()
    desc = (event.get("description") or "").lower()
    if play_type == "home_run":
        return True
    return "home run" in desc or "homer" in desc or "homers" in desc


def _is_overtime_event(event: dict[str, Any], regulation_periods: int) -> bool:
    period = event.get("quarter") or 1
    return period > regulation_periods


def _filter_segment_events(
    pbp_events: list[dict[str, Any]],
    play_range: tuple[int, int],
) -> list[dict[str, Any]]:
    """Return events whose play_index lies inside the inclusive range."""
    start, end = play_range
    if start > end:
        return []
    return [
        ev
        for ev in pbp_events
        if ev.get("play_index") is not None
        and start <= ev["play_index"] <= end
    ]


def _previous_event_index(
    pbp_events: list[dict[str, Any]],
    target_play_index: int,
) -> int | None:
    """Return the list index of the event immediately preceding target_play_index.

    Walks the input order (assumed sorted by play_index, matching NORMALIZE_PBP).
    Returns None if no event precedes the target.
    """
    prev_idx: int | None = None
    for i, ev in enumerate(pbp_events):
        pi = ev.get("play_index")
        if pi is None:
            continue
        if pi >= target_play_index:
            return prev_idx
        prev_idx = i
    return prev_idx


def _extract_scoring_plays(
    pbp_events: list[dict[str, Any]],
    segment_events: list[dict[str, Any]],
    league_code: str,
    regulation_periods: int,
) -> list[ScoringPlay]:
    code = (league_code or "NBA").upper()
    out: list[ScoringPlay] = []
    for ev in segment_events:
        play_index = ev.get("play_index")
        if play_index is None:
            continue
        prev_list_idx = _previous_event_index(pbp_events, play_index)
        prev_ev = pbp_events[prev_list_idx] if prev_list_idx is not None else None
        if not is_scoring_play(ev, prev_ev):
            continue
        prev_home = (prev_ev.get("home_score") if prev_ev else 0) or 0
        prev_away = (prev_ev.get("away_score") if prev_ev else 0) or 0
        curr_home = ev.get("home_score") or 0
        curr_away = ev.get("away_score") or 0

        is_hr = code == "MLB" and _detect_home_run(ev)
        is_pp = code == "NHL" and _detect_power_play_goal(ev)
        is_sh = code == "NHL" and _detect_short_handed_goal(ev)
        is_en = code == "NHL" and _detect_empty_net_goal(ev)
        is_ot = _is_overtime_event(ev, regulation_periods)

        out.append(
            ScoringPlay(
                play_index=play_index,
                player=ev.get("player_name"),
                team=ev.get("team_abbreviation"),
                score_before=(prev_home, prev_away),
                score_after=(curr_home, curr_away),
                play_type=ev.get("play_type"),
                is_home_run=is_hr,
                is_power_play_goal=is_pp,
                is_short_handed_goal=is_sh,
                is_empty_net_goal=is_en,
                is_overtime=is_ot,
            )
        )
    return out


def _extract_lead_changes(
    score_timeline: ScoreTimeline,
    play_range: tuple[int, int],
) -> list[LeadChangeEvidence]:
    start, end = play_range
    out: list[LeadChangeEvidence] = []
    for evt in score_timeline.lead_change_events:
        if start <= evt.play_index <= end:
            out.append(
                LeadChangeEvidence(
                    play_index=evt.play_index,
                    from_lead=evt.previous_lead,
                    to_lead=evt.new_lead,
                )
            )
    return out


def _scoring_run_threshold(league_code: str) -> tuple[int, int]:
    """Return (run_pts_min, opp_pts_max) for in-segment scoring run detection.

    Falls back to NBA's flow thresholds for unconfigured leagues, and to
    LEAGUE_CONFIG.scoring_run_min when the flow thresholds don't define
    ``scoring_run_pts`` (MLB, NHL).
    """
    flow = get_flow_thresholds(league_code)
    if "scoring_run_pts" in flow:
        return int(flow["scoring_run_pts"]), int(flow.get("scoring_run_opp_pts", 0))
    cfg = _resolve_cfg(league_code)
    return int(cfg.get("scoring_run_min", 8)), 0


def _detect_scoring_runs(
    scoring_plays: list[ScoringPlay],
    league_code: str,
) -> list[ScoringRunEvidence]:
    """Detect maximal one-team scoring runs within ``scoring_plays``.

    A run is a maximal contiguous stretch of scoring plays attributed to one
    team where the other team does not score; if total points reach
    ``scoring_run_pts``, it is emitted.
    """
    if not scoring_plays:
        return []

    run_pts_min, _ = _scoring_run_threshold(league_code)
    out: list[ScoringRunEvidence] = []

    current_team: str | None = None
    run_points = 0
    run_plays = 0
    run_start_idx: int | None = None
    run_end_idx: int | None = None

    def _flush() -> None:
        nonlocal current_team, run_points, run_plays, run_start_idx, run_end_idx
        if (
            run_points >= run_pts_min
            and run_start_idx is not None
            and run_end_idx is not None
        ):
            out.append(
                ScoringRunEvidence(
                    team=current_team,
                    points=run_points,
                    duration_plays=run_plays,
                    start_play_index=run_start_idx,
                    end_play_index=run_end_idx,
                )
            )

    for sp in scoring_plays:
        prev_h, prev_a = sp.score_before
        curr_h, curr_a = sp.score_after
        delta_h = max(0, curr_h - prev_h)
        delta_a = max(0, curr_a - prev_a)
        if delta_h == 0 and delta_a == 0:
            continue
        scoring_team = sp.team
        # Use score deltas as ground truth for which side scored when team
        # abbreviation is missing/ambiguous.
        if delta_h > 0 and delta_a == 0:
            team_side = "HOME"
        elif delta_a > 0 and delta_h == 0:
            team_side = "AWAY"
        else:
            # Both moved (rare; treat as run break)
            _flush()
            current_team = None
            run_points = 0
            run_plays = 0
            run_start_idx = None
            run_end_idx = None
            continue

        team_key = scoring_team or team_side
        points = delta_h + delta_a
        if current_team is None or current_team != team_key:
            _flush()
            current_team = team_key
            run_points = points
            run_plays = 1
            run_start_idx = sp.play_index
            run_end_idx = sp.play_index
        else:
            run_points += points
            run_plays += 1
            run_end_idx = sp.play_index

    _flush()
    return out


def _compute_featured_players(
    scoring_plays: list[ScoringPlay],
    top_n: int = 2,
) -> list[FeaturedPlayer]:
    """Pick top-N scorers by total points contributed within the segment."""
    if not scoring_plays:
        return []
    contribution: dict[str, int] = {}
    teams: dict[str, str | None] = {}
    for sp in scoring_plays:
        if not sp.player:
            continue
        prev_h, prev_a = sp.score_before
        curr_h, curr_a = sp.score_after
        delta = max(0, curr_h - prev_h) + max(0, curr_a - prev_a)
        if delta <= 0:
            continue
        contribution[sp.player] = contribution.get(sp.player, 0) + delta
        teams.setdefault(sp.player, sp.team)
    ranked = sorted(
        contribution.items(), key=lambda kv: (-kv[1], kv[0])
    )
    return [
        FeaturedPlayer(name=name, team=teams.get(name), delta_contribution=points)
        for name, points in ranked[:top_n]
    ]


def _classify_leverage(
    segment_events: list[dict[str, Any]],
    score_timeline: ScoreTimeline,
    play_range: tuple[int, int],
    lead_changes_in_segment: int,
    league_code: str,
) -> str:
    """Return HIGH / MEDIUM / LOW leverage for the segment.

    Order of evaluation:
        1. LOW when the game is decided in the segment's late-game window
           (large lead deep into the late period).
        2. HIGH when overtime is touched, a lead flip occurs in segment, or
           the segment sits inside the late-game clutch window with a tight
           score.
        3. MEDIUM otherwise.
    """
    if not segment_events:
        return LEVERAGE_MEDIUM

    code = (league_code or "NBA").upper()
    cfg = _resolve_cfg(code)
    flow = get_flow_thresholds(code)
    regulation_periods = int(cfg.get("regulation_periods", 4))
    late_game_period = int(cfg.get("late_game_period", regulation_periods))

    last_event = segment_events[-1]
    last_period = last_event.get("quarter") or 1
    in_late_game = last_period >= late_game_period
    touches_overtime = any(
        _is_overtime_event(ev, regulation_periods) for ev in segment_events
    )

    # Final-state lead at end of segment.
    last_h = last_event.get("home_score") or 0
    last_a = last_event.get("away_score") or 0
    end_margin = abs(last_h - last_a)

    # Peak margin observed inside the segment (from timeline restricted to range).
    start_pi, end_pi = play_range
    peak_segment_margin = 0
    for sp in score_timeline.per_play:
        if start_pi <= sp.play_index <= end_pi:
            margin = abs(sp.lead)
            if margin > peak_segment_margin:
                peak_segment_margin = margin

    # ---- LOW: game decided ----
    if code == "MLB":
        blowout_margin = int(flow.get("blowout_run_margin", 7))
        blowout_after = int(flow.get("blowout_after_inning", 5))
        if last_period >= blowout_after and end_margin >= blowout_margin:
            return LEVERAGE_LOW
    else:
        out_of_reach_lead = int(
            flow.get("game_out_of_reach_lead", cfg.get("blowout_margin", 15))
        )
        garbage_margin = int(cfg.get("garbage_time_margin", out_of_reach_lead))
        garbage_period = int(cfg.get("garbage_time_period", late_game_period))
        if last_period >= garbage_period and end_margin >= garbage_margin:
            return LEVERAGE_LOW
        if in_late_game and end_margin >= out_of_reach_lead:
            return LEVERAGE_LOW

    # ---- HIGH: overtime, lead change, or late clutch ----
    if touches_overtime:
        return LEVERAGE_HIGH
    if lead_changes_in_segment > 0:
        return LEVERAGE_HIGH

    if code == "MLB":
        late_inning = int(flow.get("late_leverage_inning", 7))
        clutch_runs = int(flow.get("multi_run_inning", 2))
        if last_period >= late_inning and end_margin <= clutch_runs:
            return LEVERAGE_HIGH
    elif code == "NHL":
        close_third = int(flow.get("close_game_entering_third", 1))
        if in_late_game and end_margin <= close_third:
            return LEVERAGE_HIGH
    else:
        clutch_pts = int(flow.get("clutch_window_pts", cfg.get("close_game_margin", 5)))
        if in_late_game and end_margin <= clutch_pts:
            return LEVERAGE_HIGH

    # ---- HIGH: segment built or erased a meaningful lead ----
    meaningful = int(cfg.get("meaningful_lead", 10))
    if peak_segment_margin >= meaningful and end_margin <= max(meaningful // 2, 1):
        return LEVERAGE_HIGH

    return LEVERAGE_MEDIUM


def select_evidence(
    segment_play_range: tuple[int, int],
    score_timeline: ScoreTimeline,
    pbp_events: list[dict[str, Any]],
    league_code: str = "NBA",
) -> SegmentEvidence:
    """Select structured per-segment evidence for narrative generation.

    Args:
        segment_play_range: Inclusive ``(start_play_index, end_play_index)``
            range describing the segment's play coverage.
        score_timeline: Precomputed timeline (see ``score_timeline`` helper).
            Lead-change events outside the range are ignored.
        pbp_events: Full normalized PBP event list for the game.
        league_code: League code (NBA, MLB, NHL, NCAAB, NFL); unknown codes
            fall back to NBA.

    Returns:
        ``SegmentEvidence`` aggregating scoring plays, lead changes, scoring
        runs, featured players, leverage, and special-event flags. Returns
        an empty (non-error) evidence object when the segment contains no
        scoring activity.
    """
    if not pbp_events or segment_play_range[0] > segment_play_range[1]:
        return SegmentEvidence(leverage=LEVERAGE_MEDIUM)

    cfg = _resolve_cfg(league_code)
    regulation_periods = int(cfg.get("regulation_periods", 4))

    segment_events = _filter_segment_events(pbp_events, segment_play_range)
    if not segment_events:
        return SegmentEvidence(leverage=LEVERAGE_MEDIUM)

    scoring_plays = _extract_scoring_plays(
        pbp_events,
        segment_events,
        league_code,
        regulation_periods,
    )
    lead_changes = _extract_lead_changes(score_timeline, segment_play_range)
    scoring_runs = _detect_scoring_runs(scoring_plays, league_code)
    featured_players = _compute_featured_players(scoring_plays)
    leverage = _classify_leverage(
        segment_events,
        score_timeline,
        segment_play_range,
        len(lead_changes),
        league_code,
    )

    is_overtime = any(sp.is_overtime for sp in scoring_plays) or any(
        _is_overtime_event(ev, regulation_periods) for ev in segment_events
    )

    return SegmentEvidence(
        scoring_plays=scoring_plays,
        lead_changes=lead_changes,
        scoring_runs=scoring_runs,
        featured_players=featured_players,
        leverage=leverage,
        is_overtime=is_overtime,
        is_scoring_run=bool(scoring_runs),
        is_power_play_goal=any(sp.is_power_play_goal for sp in scoring_plays),
        is_short_handed_goal=any(sp.is_short_handed_goal for sp in scoring_plays),
        is_empty_net=any(sp.is_empty_net_goal for sp in scoring_plays),
    )
