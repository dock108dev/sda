"""NFL narrative fallback template blocks.

Produces 4 blocks: SETUP → MOMENTUM_SHIFT → DECISION_POINT → RESOLUTION.
All narratives use NFL-specific voice (downs, yards, turnovers, quarters).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from . import GameMiniBox


def _lead_desc(team_a: str, score_a: int, team_b: str, score_b: int) -> str:
    """Return a short phrase describing who leads or if tied."""
    if score_a > score_b:
        return f"{team_a} led {score_a}-{score_b}"
    if score_b > score_a:
        return f"{team_b} led {score_b}-{score_a}"
    return f"both teams were knotted at {score_a}"


def _mini_box(
    h_cum: int,
    a_cum: int,
    h_delta: int,
    a_delta: int,
) -> dict[str, Any]:
    return {
        "cumulative": {
            "home": {"yards": h_cum * 12, "first_downs": max(1, h_cum * 3 // 2), "turnovers": 0},
            "away": {"yards": a_cum * 12, "first_downs": max(1, a_cum * 3 // 2), "turnovers": 0},
        },
        "delta": {"yards_home": h_delta * 12, "yards_away": a_delta * 12},
    }


def render_blocks(
    mb: GameMiniBox,
    moment_chunks: list[list[int]],
    scores: list[tuple[int, int]],
) -> list[dict[str, Any]]:
    """Return 4 NFL template blocks."""
    home, away = mb.home_team, mb.away_team
    hs, as_ = mb.home_score, mb.away_score
    winner, loser = (home, away) if hs >= as_ else (away, home)

    q1h, q1a = scores[0]
    q2h, q2a = scores[1]
    q3h, q3a = scores[2]

    # Narrative: SETUP
    q1_state = _lead_desc(home, q1h, away, q1a)
    setup_narrative = (
        f"{away} and {home} opened their contest with both offenses testing the opposing defense "
        f"on the first possessions of the afternoon. {home} controlled field position early, "
        f"and by the end of the first quarter {q1_state}, signaling an afternoon of sustained competition."
    )

    # Narrative: MOMENTUM_SHIFT
    half_leader = home if q2h >= q2a else away
    shift_narrative = (
        f"The second quarter saw {half_leader} impose their will through ball control and red-zone "
        f"efficiency, converting possessions into points. Sustained drives and a stout defensive "
        f"stand gave {half_leader} the better of the half, pushing the score to {q2h}-{q2a} at "
        f"intermission and setting up a critical second half."
    )

    # Narrative: DECISION_POINT
    q3_leader = home if q3h >= q3a else away
    q3_trailer = away if q3h >= q3a else home
    decision_narrative = (
        f"The third quarter delivered the decisive stretch of play. {q3_leader} converted on "
        f"the opportunities that mattered most, keeping the chains moving while forcing "
        f"{q3_trailer} into a series of three-and-outs. The margin stood at {q3h}-{q3a} entering "
        f"the final quarter, leaving {q3_trailer} needing a sustained response."
    )

    # Narrative: RESOLUTION
    if mb.has_overtime:
        res_narrative = (
            f"{winner} prevailed in overtime to complete a {hs}-{as_} victory. "
            f"The overtime period capped a back-and-forth contest that neither team could "
            f"settle in regulation, with {winner} executing the game-winning drive when it mattered most."
        )
    else:
        res_narrative = (
            f"{winner} closed out the contest with a {hs}-{as_} final. "
            f"{loser} applied pressure late but could not generate the stops or scoring needed "
            f"to alter the outcome, as {winner} ran out the clock and secured the victory."
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
