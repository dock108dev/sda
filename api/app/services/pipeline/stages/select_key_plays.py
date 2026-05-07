"""Full-game key play selection for the catch-up summary pipeline.

Selects the 5-10 most narratively important plays from a completed game,
ranked by deterministic heuristics. Sport-aware via league_config.

Used by the GENERATE_SUMMARY stage as one of the inputs to the LLM prompt.
The selection is also surfaced on the consumer summary endpoint as
``referencedPlayIds`` so catch-up cards can link back to the same plays.
"""

from __future__ import annotations

from typing import Any

from .league_config import get_config

# Lead change is the dominant signal — anything that flips who's leading is a
# key play. Late-game and run-ending plays are next; raw scoring plays are
# the lowest-priority bucket. Blowout plays are halved because by then the
# narrative is decided.
_LEAD_CHANGE_BONUS = 100.0
_RUN_ENDING_BONUS = 25.0
_LATE_GAME_BONUS = 15.0
_SCORING_BONUS = 5.0
_FINAL_PLAY_BONUS = 30.0
_BLOWOUT_DAMPER = 0.5

MIN_KEY_PLAYS = 5
MAX_KEY_PLAYS = 10


def _is_scoring_play(play_type: str | None, score_changed: bool) -> bool:
    """A play 'scores' if the score changed or play_type explicitly says so."""
    if score_changed:
        return True
    if not play_type:
        return False
    return "score" in play_type.lower() or "goal" in play_type.lower()


def _detect_run_ending_plays(
    pbp_events: list[dict[str, Any]],
    scoring_run_min: int,
) -> set[int]:
    """Mark plays that ended a sustained scoring run by the same team.

    Approximates point-value with the score delta — works for all four sports
    because we only care about which team scored, not how many points.
    """
    run_enders: set[int] = set()
    consecutive_scorer: int | None = None
    run_total = 0
    last_run_play: int | None = None
    prev_h = 0
    prev_a = 0
    for ev in pbp_events:
        h = ev.get("home_score") or 0
        a = ev.get("away_score") or 0
        h_delta = h - prev_h
        a_delta = a - prev_a
        if h_delta > 0 and a_delta == 0:
            scorer = 1
            points = h_delta
        elif a_delta > 0 and h_delta == 0:
            scorer = -1
            points = a_delta
        else:
            prev_h, prev_a = h, a
            continue
        play_id = ev.get("play_index")
        if scorer == consecutive_scorer:
            run_total += points
            last_run_play = play_id
        else:
            if run_total >= scoring_run_min and last_run_play is not None:
                run_enders.add(last_run_play)
            consecutive_scorer = scorer
            run_total = points
            last_run_play = play_id
        prev_h, prev_a = h, a
    if run_total >= scoring_run_min and last_run_play is not None:
        run_enders.add(last_run_play)
    return run_enders


def select_key_plays_full_game(
    pbp_events: list[dict[str, Any]],
    league_code: str = "NBA",
) -> list[int]:
    """Pick the most narratively important plays for a whole game.

    Returns 5-10 ``play_index`` values, ordered chronologically. League-aware
    via league_config (late_game_period, blowout_margin, scoring_run_min).
    """
    if not pbp_events:
        return []

    cfg = get_config(league_code) if league_code else get_config("NBA")
    late_game_period = int(cfg["late_game_period"])
    blowout_margin = int(cfg["blowout_margin"])
    scoring_run_min = int(cfg["scoring_run_min"])

    run_enders = _detect_run_ending_plays(pbp_events, scoring_run_min)

    final_play_id = pbp_events[-1].get("play_index")

    play_scores: dict[int, float] = {}
    prev_leader = 0  # 1 = home leading, -1 = away, 0 = tied
    prev_h = 0
    prev_a = 0

    for ev in pbp_events:
        play_id = ev.get("play_index")
        if play_id is None:
            continue
        h = ev.get("home_score") or 0
        a = ev.get("away_score") or 0
        play_type = ev.get("play_type")
        period = ev.get("quarter") or ev.get("period") or 1
        score_changed = (h != prev_h) or (a != prev_a)

        score = 0.0

        current_leader = 1 if h > a else (-1 if a > h else 0)
        if (
            prev_leader != 0
            and current_leader != 0
            and prev_leader != current_leader
        ):
            score += _LEAD_CHANGE_BONUS
        if current_leader != 0:
            prev_leader = current_leader

        if _is_scoring_play(play_type, score_changed):
            score += _SCORING_BONUS

        if period >= late_game_period:
            score += _LATE_GAME_BONUS

        if play_id in run_enders:
            score += _RUN_ENDING_BONUS

        if play_id == final_play_id:
            score += _FINAL_PLAY_BONUS

        margin = abs(h - a)
        if margin > blowout_margin:
            score *= _BLOWOUT_DAMPER

        if score > 0:
            play_scores[play_id] = score

        prev_h, prev_a = h, a

    if not play_scores:
        return [final_play_id] if final_play_id is not None else []

    ranked = sorted(play_scores.items(), key=lambda item: item[1], reverse=True)
    selected = {pid for pid, _ in ranked[:MAX_KEY_PLAYS]}

    # Always include the final play so the summary can close on it.
    if final_play_id is not None:
        selected.add(final_play_id)

    # Keep at least MIN_KEY_PLAYS by topping up from the next-highest scores.
    if len(selected) < MIN_KEY_PLAYS:
        for pid, _ in ranked:
            selected.add(pid)
            if len(selected) >= MIN_KEY_PLAYS:
                break

    play_id_order = {ev.get("play_index"): i for i, ev in enumerate(pbp_events)}
    return sorted(selected, key=lambda pid: play_id_order.get(pid, 0))
