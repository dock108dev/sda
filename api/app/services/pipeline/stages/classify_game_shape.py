"""CLASSIFY_GAME_SHAPE Stage Implementation.

Deterministically labels a game with one of seven archetype strings before
any LLM call. Downstream stages (GROUP_BLOCKS, RENDER_BLOCKS, VALIDATE_BLOCKS)
consume the archetype from the accumulated pipeline output to drive
archetype-aware boundary, evidence, and prompt selection.

Archetypes
----------
- ``wire_to_wire``       — winner led from the first score; lead never flipped
- ``comeback``           — winner trailed by ≥ ``meaningful_lead`` at some point
- ``back_and_forth``     — three or more lead changes
- ``blowout``            — peak margin sustained past the league's blowout
                           threshold (MLB sub-type: ``early_avalanche_blowout``
                           when 4+ runs are scored in the first 2 innings)
- ``low_event``          — combined scoring below the league threshold or the
                           losing team is shut out
- ``fake_close``         — final margin within 1 possession but the lead spent
                           the majority of the game past ``large_lead``
- ``late_separation``    — entering the final period within 1 possession but
                           separated by more than 1 possession at the end

The stage is pure and deterministic — same inputs produce the same archetype.
"""

from __future__ import annotations

import logging
from typing import Any

from ..helpers.score_timeline import ScoreTimeline, build_score_timeline
from ..models import StageInput, StageOutput
from .block_analysis import detect_blowout
from .league_config import _NBA_DEFAULTS, LEAGUE_CONFIG, get_flow_thresholds

logger = logging.getLogger(__name__)


_DEFAULT_ARCHETYPE = "wire_to_wire"


def _resolve_league_cfg(league_code: str) -> dict[str, Any]:
    code = (league_code or "NBA").upper()
    return LEAGUE_CONFIG.get(code, _NBA_DEFAULTS)


def _one_possession_margin(league_code: str) -> int:
    """Sport-specific 'within 1 possession' margin.

    Used by both fake_close and late_separation since neither is captured
    cleanly by the existing ``close_game_margin`` (which is a wider clutch
    window, not a possession-sized margin).
    """
    code = (league_code or "NBA").upper()
    if code in {"NBA", "NCAAB"}:
        return 3
    if code == "MLB":
        return 1
    if code == "NHL":
        return 1
    if code == "NFL":
        return 8
    return 3


def _large_lead_threshold(league_code: str) -> int:
    """Margin that qualifies as a 'large lead' for fake_close detection."""
    flow = get_flow_thresholds(league_code)
    if "large_lead" in flow:
        return int(flow["large_lead"])
    if "blowout_run_margin" in flow:
        return int(flow["blowout_run_margin"])
    return int(_resolve_league_cfg(league_code).get("blowout_margin", 15))


def _is_low_event(timeline: ScoreTimeline, league_code: str) -> bool:
    """Detect pitcher's-duel / defensive-battle style games.

    For MLB: combined runs ≤ ``low_scoring_combined`` or the losing team is
    held to ≤ ``shutout`` runs. Other leagues currently have no explicit
    low-event threshold and fall through.
    """
    if not timeline.per_play:
        return False
    code = (league_code or "NBA").upper()
    flow = get_flow_thresholds(league_code)
    final = timeline.per_play[-1]
    combined = final.home_score + final.away_score
    loser = min(final.home_score, final.away_score)

    if code == "MLB":
        if combined <= int(flow.get("low_scoring_combined", 4)):
            return True
        if loser <= int(flow.get("shutout", 0)):
            return True
    return False


def _is_early_avalanche_mlb(
    pbp_events: list[dict[str, Any]],
    flow: dict[str, Any],
) -> bool:
    """MLB sub-archetype: ≥ ``early_avalanche_runs`` in the first N innings."""
    runs_threshold = int(flow.get("early_avalanche_runs", 4))
    inning_threshold = int(flow.get("early_avalanche_innings", 2))
    end_home = 0
    end_away = 0
    for ev in pbp_events:
        inning = ev.get("quarter") or 0
        if inning <= inning_threshold:
            end_home = ev.get("home_score") or end_home
            end_away = ev.get("away_score") or end_away
    return end_home >= runs_threshold or end_away >= runs_threshold


def _is_comeback(timeline: ScoreTimeline, league_code: str) -> bool:
    """Eventual winner trailed by ≥ ``meaningful_lead`` at some point."""
    if not timeline.per_play:
        return False
    final = timeline.per_play[-1]
    if final.lead == 0:
        return False
    cfg = _resolve_league_cfg(league_code)
    meaningful = int(cfg.get("meaningful_lead", 10))
    if final.lead > 0:
        return any(sp.lead <= -meaningful for sp in timeline.per_play)
    return any(sp.lead >= meaningful for sp in timeline.per_play)


def _final_period_entry_lead(
    pbp_events: list[dict[str, Any]],
    final_period: int,
) -> int | None:
    """Signed lead carried into the start of ``final_period``.

    Returns the score-difference from the last play in any prior period, or
    ``None`` if no plays exist before the final period (game has no pre-final
    history — late_separation cannot apply).
    """
    pre_home = 0
    pre_away = 0
    saw_pre_final = False
    for ev in pbp_events:
        period = ev.get("quarter") or 1
        if period < final_period:
            pre_home = ev.get("home_score") or pre_home
            pre_away = ev.get("away_score") or pre_away
            saw_pre_final = True
    if not saw_pre_final:
        return None
    return pre_home - pre_away


def _is_fake_close(timeline: ScoreTimeline, league_code: str) -> bool:
    """Final margin within 1 possession; eventual winner led by ≥ large_lead for majority.

    Distinguishes fake_close from comeback by requiring the *winner* to have
    been the leader during the wide-margin stretch — a comeback has the
    eventual loser leading then collapsing.
    """
    if not timeline.per_play:
        return False
    one_poss = _one_possession_margin(league_code)
    large = _large_lead_threshold(league_code)
    final = timeline.per_play[-1]
    if final.lead == 0:
        return False
    if abs(final.lead) > one_poss:
        return False
    winner_sign = 1 if final.lead > 0 else -1
    plays_with_winner_large = sum(
        1 for sp in timeline.per_play if (sp.lead * winner_sign) >= large
    )
    return plays_with_winner_large * 2 > len(timeline.per_play)


def _is_late_separation(
    timeline: ScoreTimeline,
    pbp_events: list[dict[str, Any]],
    league_code: str,
) -> bool:
    """Within 1 possession entering the final period; separated by more than 1 possession at the end."""
    if not timeline.per_play or not pbp_events:
        return False
    cfg = _resolve_league_cfg(league_code)
    regulation_periods = int(cfg.get("regulation_periods", 4))
    max_period = max((ev.get("quarter") or 1) for ev in pbp_events)
    final_period = max(regulation_periods, max_period)

    entry_lead = _final_period_entry_lead(pbp_events, final_period)
    if entry_lead is None:
        return False
    one_poss = _one_possession_margin(league_code)
    final_lead = abs(timeline.per_play[-1].lead)
    return abs(entry_lead) <= one_poss and final_lead > one_poss


def classify_archetype(
    timeline: ScoreTimeline,
    pbp_events: list[dict[str, Any]],
    moments: list[dict[str, Any]],
    league_code: str,
) -> str:
    """Pure, deterministic archetype classifier.

    Rules are evaluated in priority order; the first match wins. The order is
    chosen so more specific shapes (low_event, blowout) take precedence over
    looser ones (back_and_forth, wire_to_wire).
    """
    if not timeline.per_play:
        return _DEFAULT_ARCHETYPE

    code = (league_code or "NBA").upper()
    flow = get_flow_thresholds(league_code)

    if _is_low_event(timeline, code):
        return "low_event"

    # Comeback is checked before blowout: a comeback game's losing team often
    # led by ≥ blowout_margin earlier, so detect_blowout would mislabel it.
    if _is_comeback(timeline, code):
        return "comeback"

    # Fake-close is checked before blowout: a game that built a large lead and
    # then closed to within one possession looks like a blowout under
    # detect_blowout (sustained margin), but the close finish is the more
    # specific narrative shape.
    if _is_fake_close(timeline, code):
        return "fake_close"

    is_blowout = False
    if moments:
        # detect_blowout raises KeyError for league codes outside LEAGUE_CONFIG.
        # Mirror the score_timeline fallback by passing "NBA" for unknown codes.
        detect_code = code if code in LEAGUE_CONFIG else "NBA"
        is_blowout, _, _ = detect_blowout(moments, league_code=detect_code)
    if is_blowout:
        if code == "MLB" and _is_early_avalanche_mlb(pbp_events, flow):
            return "early_avalanche_blowout"
        return "blowout"

    if len(timeline.lead_change_events) >= 3:
        return "back_and_forth"

    if _is_late_separation(timeline, pbp_events, code):
        return "late_separation"

    return "wire_to_wire"


async def execute_classify_game_shape(stage_input: StageInput) -> StageOutput:
    """Deterministically classify the game's archetype.

    Reads moments and pbp_events from the accumulated previous-stage output,
    builds a :class:`ScoreTimeline`, and selects one of seven archetype
    strings. The chosen archetype is added to the stage output dict so
    downstream stages can read it from accumulated pipeline context.
    """
    output = StageOutput(data={})
    game_id = stage_input.game_id
    output.add_log(f"Starting CLASSIFY_GAME_SHAPE for game {game_id}")

    previous_output = stage_input.previous_output
    if not previous_output:
        raise ValueError("CLASSIFY_GAME_SHAPE requires VALIDATE_MOMENTS output")

    moments = previous_output.get("moments", [])
    pbp_events = previous_output.get("pbp_events", [])
    league_code = (
        stage_input.game_context.get("sport", "NBA")
        if stage_input.game_context
        else "NBA"
    )

    timeline = build_score_timeline(pbp_events, league_code=league_code)
    archetype = classify_archetype(timeline, pbp_events, moments, league_code)

    output.add_log(
        f"Game {game_id} classified as archetype={archetype} "
        f"(league={league_code}, lead_changes={len(timeline.lead_change_events)}, "
        f"peak_lead={timeline.peak_lead})"
    )

    output.data = {
        "archetype": archetype,
        "shape_classified": True,
        # Passthrough keeps direct invocations consistent with the executor's
        # accumulation layer.
        "moments": moments,
        "pbp_events": pbp_events,
        "validated": previous_output.get("validated", True),
        "errors": previous_output.get("errors", []),
    }
    return output
