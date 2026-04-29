"""NHL narrative fallback template blocks.

Produces 4 blocks: SETUP → MOMENTUM_SHIFT → DECISION_POINT → RESOLUTION.
All narratives use NHL-specific voice (periods, puck possession, power plays, shots).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from . import GameMiniBox


def _mini_box(h_goals: int, a_goals: int, h_delta: int, a_delta: int) -> dict[str, Any]:
    return {
        "cumulative": {
            "home": {"goals": h_goals, "shots": max(10, h_goals * 8), "saves": max(5, a_goals * 5)},
            "away": {"goals": a_goals, "shots": max(10, a_goals * 8), "saves": max(5, h_goals * 5)},
        },
        "delta": {"goals_home": h_delta, "goals_away": a_delta},
    }


def render_blocks(
    mb: GameMiniBox,
    moment_chunks: list[list[int]],
    scores: list[tuple[int, int]],
) -> list[dict[str, Any]]:
    """Return 4 NHL template blocks."""
    home, away = mb.home_team, mb.away_team
    hs, as_ = mb.home_score, mb.away_score
    winner, loser = (home, away) if hs >= as_ else (away, home)

    q1h, q1a = scores[0]
    q2h, q2a = scores[1]
    q3h, q3a = scores[2]

    q1_leader = home if q1h >= q1a else away
    q1_score = f"{q1h}-{q1a}"
    half_leader = home if q2h >= q2a else away
    q3_leader = home if q3h >= q3a else away
    q3_trailer = away if q3h >= q3a else home

    setup_narrative = (
        f"{away} and {home} opened with a structured first period marked by tight defensive "
        f"coverage and limited odd-man opportunities. Both goaltenders were sharp when called "
        f"upon, and {q1_leader} broke through to take a {q1_score} lead on a well-worked "
        f"zone entry that ended with a clean finish past the blocker."
    )

    shift_narrative = (
        f"The second period saw {half_leader} assert control through sustained puck possession "
        f"and effective defensive-zone clears. A power-play conversion added to their total, "
        f"and {half_leader} carried a {q2h}-{q2a} advantage into the second intermission "
        f"with their penalty kill and goaltender both performing well under pressure."
    )

    decision_narrative = (
        f"The third period delivered the critical sequence that settled the contest. "
        f"{q3_leader} generated the decisive scoring chance and converted, pushing the "
        f"margin to {q3h}-{q3a} with limited time remaining. {q3_trailer} pressed for "
        f"an equalizer but could not beat the goaltender, leaving the outcome clear."
    )

    if mb.has_overtime:
        res_narrative = (
            f"{winner} ended it in overtime for a {hs}-{as_} final, converting the first "
            f"real chance of the extra frame after both teams showed caution in the opening "
            f"minutes. The overtime goal capped a full sixty minutes of regulation play "
            f"that left the two clubs inseparable until {winner} stepped up."
        )
    else:
        res_narrative = (
            f"{winner} skated away with a {hs}-{as_} result and two points in the standings. "
            f"{loser} made a late push and pulled their goaltender in the final minute, "
            f"but {winner} held firm and iced the puck to seal the victory."
        )

    # NHL has 3 regulation periods; blocks span P1, P2, P3, and optionally OT (P4)
    prev = [0, 0]
    blocks: list[dict[str, Any]] = []
    entries = [
        ("SETUP", 0, scores[0], setup_narrative, 1, 1),
        ("MOMENTUM_SHIFT", 1, scores[1], shift_narrative, 2, 2),
        ("DECISION_POINT", 2, scores[2], decision_narrative, 3, 3),
        ("RESOLUTION", 3, (hs, as_), res_narrative, 3, 4 if mb.has_overtime else 3),
    ]
    for role, idx, score_after, narrative, p_start, p_end in entries:
        sh, sa = score_after
        delta_h = sh - prev[0]
        delta_a = sa - prev[1]
        blocks.append({
            "block_index": idx,
            "role": role,
            "moment_indices": moment_chunks[idx],
            "period_start": p_start,
            "period_end": p_end,
            "score_before": list(prev),
            "score_after": [sh, sa],
            "play_ids": moment_chunks[idx],
            "key_play_ids": [],
            "narrative": narrative,
            "mini_box": _mini_box(sh, sa, delta_h, delta_a),
        })
        prev = [sh, sa]

    return blocks
