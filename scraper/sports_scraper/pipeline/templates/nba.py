"""NBA narrative fallback template blocks.

Produces 4 blocks: SETUP → MOMENTUM_SHIFT → DECISION_POINT → RESOLUTION.
All narratives use NBA-specific voice (quarters, paint, three-pointers, runs).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from . import GameMiniBox


def _mini_box(h_pts: int, a_pts: int, h_delta: int, a_delta: int) -> dict[str, Any]:
    return {
        "cumulative": {
            "home": {"points": h_pts, "rebounds": max(1, h_pts * 4 // 10), "assists": max(1, h_pts * 2 // 10)},
            "away": {"points": a_pts, "rebounds": max(1, a_pts * 4 // 10), "assists": max(1, a_pts * 2 // 10)},
        },
        "delta": {"points_home": h_delta, "points_away": a_delta},
    }


def render_blocks(
    mb: GameMiniBox,
    moment_chunks: list[list[int]],
    scores: list[tuple[int, int]],
) -> list[dict[str, Any]]:
    """Return 4 NBA template blocks."""
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
        f"{away} opened their road game against {home} with an energetic start, "
        f"pushing the pace and testing the home defense in the first twelve minutes. "
        f"{q1_leader} held the first-quarter edge at {q1_score}, establishing early momentum "
        f"through strong interior play and ball movement on the offensive end."
    )

    shift_narrative = (
        f"The second quarter belonged to {half_leader}, who used an extended bench run to "
        f"build on their early lead and control the game's tempo heading into halftime. "
        f"Efficient shot selection and a stingy half-court defense pushed the score to "
        f"{q2h}-{q2a} at the break, handing {half_leader} a clear advantage to protect."
    )

    decision_narrative = (
        f"The third quarter delivered the run that shaped the final outcome. {q3_leader} "
        f"strung together consecutive stops and baskets to push their advantage to {q3h}-{q3a}, "
        f"placing {q3_trailer} in the difficult position of chasing the game entering the fourth. "
        f"Clutch shooting and defensive rotations defined the stretch that decided the contest."
    )

    if mb.has_overtime:
        res_narrative = (
            f"{winner} completed the win in overtime to earn a {hs}-{as_} final, "
            f"converting the decisive possession after the teams were locked in regulation. "
            f"{loser} had chances to end it but {winner} made the extra-period plays to "
            f"walk away with the victory in an overtime thriller."
        )
    else:
        res_narrative = (
            f"{winner} closed out the {hs}-{as_} win with composed fourth-quarter execution. "
            f"{loser} made a push late but {winner} responded to every run, "
            f"securing the victory through free throws and defensive stops in the final minutes."
        )

    prev = [0, 0]
    blocks: list[dict[str, Any]] = []
    entries = [
        ("SETUP", 0, scores[0], setup_narrative, 1, 1),
        ("MOMENTUM_SHIFT", 1, scores[1], shift_narrative, 2, 2),
        ("DECISION_POINT", 2, scores[2], decision_narrative, 3, 3),
        ("RESOLUTION", 3, (hs, as_), res_narrative, 4, 4 + (1 if mb.has_overtime else 0)),
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
