"""MLB narrative fallback template blocks.

Produces 4 blocks: SETUP → MOMENTUM_SHIFT → DECISION_POINT → RESOLUTION.
All narratives use MLB-specific voice (innings, at-bats, bullpen, baserunners).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from . import GameMiniBox


def _mini_box(h_runs: int, a_runs: int, h_delta: int, a_delta: int) -> dict[str, Any]:
    return {
        "cumulative": {
            "home": {"runs": h_runs, "hits": max(1, h_runs * 2), "errors": 0},
            "away": {"runs": a_runs, "hits": max(1, a_runs * 2), "errors": 0},
        },
        "delta": {"runs_home": h_delta, "runs_away": a_delta},
    }


def render_blocks(
    mb: GameMiniBox,
    moment_chunks: list[list[int]],
    scores: list[tuple[int, int]],
) -> list[dict[str, Any]]:
    """Return 4 MLB template blocks."""
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
        f"{away} and {home} opened with sharp starting pitching from both sides, "
        f"limiting baserunners and keeping early scoring opportunities to a minimum. "
        f"{q1_leader} broke through first in the early innings to take a {q1_score} lead, "
        f"capitalizing on a timely hit after working the count."
    )

    shift_narrative = (
        f"The middle innings swung toward {half_leader}, who strung together a productive "
        f"stretch of at-bats and made the opposing bullpen pay for a lapse in command. "
        f"A multi-run frame extended the advantage to {q2h}-{q2a} through six innings, "
        f"putting the home bench in a position of needing a rally."
    )

    decision_narrative = (
        f"The seventh and eighth innings provided the critical late-game moments. "
        f"{q3_leader} protected their lead with strong bullpen work, stranding baserunners "
        f"and keeping {q3_trailer} from closing the gap. The score reached {q3h}-{q3a} "
        f"heading into the final inning, with {q3_trailer}'s lineup needing to produce a "
        f"decisive response against a fresh arm."
    )

    if mb.has_overtime:
        res_narrative = (
            f"{winner} claimed the {hs}-{as_} result in overtime after regulation could not "
            f"separate the clubs. The extra innings stretched the game past the standard nine "
            f"frames, with {winner} ultimately delivering the winning hit to end the overtime "
            f"session and secure the result."
        )
    else:
        res_narrative = (
            f"{winner} closed it out in the ninth for a {hs}-{as_} final. "
            f"{loser}'s last-inning effort came up short, as {winner}'s closer finished "
            f"with authority to send the home crowd home satisfied with the result."
        )

    prev = [0, 0]
    blocks: list[dict[str, Any]] = []
    entries = [
        ("SETUP", 0, scores[0], setup_narrative, 1, 3),
        ("MOMENTUM_SHIFT", 1, scores[1], shift_narrative, 4, 6),
        ("DECISION_POINT", 2, scores[2], decision_narrative, 7, 8),
        ("RESOLUTION", 3, (hs, as_), res_narrative, 9, 9 + (1 if mb.has_overtime else 0)),
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
