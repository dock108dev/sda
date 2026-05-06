"""Sport-specific narrative fallback template engine (API package copy).

Mirrors scraper/sports_scraper/pipeline/templates/ for use within the API
pipeline, which cannot import the scraper package at runtime.

No LLM calls are made during rendering. Output is guaranteed to pass
validate_blocks.py structural constraints.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class GameMiniBox:
    """Structured game data consumed by template rendering."""

    home_team: str
    away_team: str
    home_score: int
    away_score: int
    sport: str
    has_overtime: bool = False
    total_moments: int = 0


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _distribute_moments(total: int, n_blocks: int) -> list[list[int]]:
    if total == 0:
        return [[] for _ in range(n_blocks)]
    sizes = [total // n_blocks] * n_blocks
    for i in range(total % n_blocks):
        sizes[i] += 1
    result: list[list[int]] = []
    start = 0
    for size in sizes:
        result.append(list(range(start, start + size)))
        start += size
    return result


def _block_scores(home: int, away: int) -> list[tuple[int, int]]:
    fractions = (0.20, 0.50, 0.75, 1.00)
    return [(int(home * f), int(away * f)) for f in fractions]


def _winner_loser(home: str, away: str, hs: int, as_: int) -> tuple[str, str]:
    return (home, away) if hs >= as_ else (away, home)


# ---------------------------------------------------------------------------
# NFL
# ---------------------------------------------------------------------------


def _nfl_mini_box(h: int, a: int, dh: int, da: int) -> dict[str, Any]:
    return {
        "cumulative": {
            "home": {"yards": h * 12, "first_downs": max(1, h * 3 // 2), "turnovers": 0},
            "away": {"yards": a * 12, "first_downs": max(1, a * 3 // 2), "turnovers": 0},
        },
        "delta": {"yards_home": dh * 12, "yards_away": da * 12},
    }


def _nfl_blocks(
    mb: GameMiniBox,
    chunks: list[list[int]],
    scores: list[tuple[int, int]],
) -> list[dict[str, Any]]:
    home, away = mb.home_team, mb.away_team
    hs, as_ = mb.home_score, mb.away_score
    winner, loser = _winner_loser(home, away, hs, as_)
    q1h, q1a = scores[0]
    q2h, q2a = scores[1]
    q3h, q3a = scores[2]

    q1_leader = home if q1h >= q1a else away
    q1_score = f"{q1h}-{q1a}"
    half_leader = home if q2h >= q2a else away
    q3_leader = home if q3h >= q3a else away
    q3_trailer = away if q3h >= q3a else home

    narratives = [
        (
            f"{away} and {home} opened their contest with both offenses testing the opposing "
            f"defense on the first possessions of the afternoon. {home} controlled field position "
            f"early, and by the end of the first quarter {q1_leader} led {q1_score}, signaling "
            f"an afternoon of sustained competition."
        ),
        (
            f"The second quarter saw {half_leader} impose their will through ball control and "
            f"red-zone efficiency, converting possessions into points. Sustained drives and a "
            f"stout defensive stand gave {half_leader} the better of the half, pushing the "
            f"score to {q2h}-{q2a} at intermission and setting up a critical second half."
        ),
        (
            f"The third quarter delivered the decisive stretch of play. {q3_leader} converted "
            f"on the opportunities that mattered most, keeping the chains moving while forcing "
            f"{q3_trailer} into a series of three-and-outs. The margin stood at {q3h}-{q3a} "
            f"entering the final quarter, leaving {q3_trailer} needing a sustained response."
        ),
        (
            f"{winner} prevailed in overtime to complete a {hs}-{as_} victory. "
            f"The overtime period capped a back-and-forth contest that neither team could "
            f"settle in regulation, with {winner} executing the game-winning drive when it mattered most."
        ) if mb.has_overtime else (
            f"{winner} closed out the contest with a {hs}-{as_} final. "
            f"{loser} applied pressure late but could not generate the stops or scoring needed "
            f"to alter the outcome, as {winner} ran out the clock and secured the victory."
        ),
    ]

    periods = [(1, 1), (2, 2), (3, 3), (4, 4 + (1 if mb.has_overtime else 0))]
    return _build_blocks(mb, chunks, scores, narratives, periods, _nfl_mini_box)


# ---------------------------------------------------------------------------
# NBA
# ---------------------------------------------------------------------------


def _nba_mini_box(h: int, a: int, dh: int, da: int) -> dict[str, Any]:
    return {
        "cumulative": {
            "home": {"points": h, "rebounds": max(1, h * 4 // 10), "assists": max(1, h * 2 // 10)},
            "away": {"points": a, "rebounds": max(1, a * 4 // 10), "assists": max(1, a * 2 // 10)},
        },
        "delta": {"points_home": dh, "points_away": da},
    }


def _nba_blocks(
    mb: GameMiniBox,
    chunks: list[list[int]],
    scores: list[tuple[int, int]],
) -> list[dict[str, Any]]:
    home, away = mb.home_team, mb.away_team
    hs, as_ = mb.home_score, mb.away_score
    winner, loser = _winner_loser(home, away, hs, as_)
    q1h, q1a = scores[0]
    q2h, q2a = scores[1]
    q3h, q3a = scores[2]

    q1_leader = home if q1h >= q1a else away
    q1_score = f"{q1h}-{q1a}"
    half_leader = home if q2h >= q2a else away
    q3_leader = home if q3h >= q3a else away
    q3_trailer = away if q3h >= q3a else home

    narratives = [
        (
            f"{away} opened their road game against {home} with an energetic start, "
            f"pushing the pace and testing the home defense in the first twelve minutes. "
            f"{q1_leader} held the first-quarter edge at {q1_score}, establishing early "
            f"momentum through strong interior play and ball movement on the offensive end."
        ),
        (
            f"The second quarter belonged to {half_leader}, who used an extended bench run "
            f"to build on their early lead and control the game's tempo heading into halftime. "
            f"Efficient shot selection and a stingy half-court defense pushed the score to "
            f"{q2h}-{q2a} at the break, handing {half_leader} a clear advantage to protect."
        ),
        (
            f"The third quarter delivered the run that shaped the final outcome. {q3_leader} "
            f"strung together consecutive stops and baskets to push their advantage to "
            f"{q3h}-{q3a}, placing {q3_trailer} in the difficult position of chasing the "
            f"game entering the fourth. Clutch shooting and defensive rotations defined "
            f"the stretch that decided the contest."
        ),
        (
            f"{winner} completed the win in overtime to earn a {hs}-{as_} final, "
            f"converting the decisive possession after the teams were locked in regulation. "
            f"{loser} had chances to end it but {winner} made the extra-period plays "
            f"to walk away with the victory in an overtime thriller."
        ) if mb.has_overtime else (
            f"{winner} closed out the {hs}-{as_} win with composed fourth-quarter execution. "
            f"{loser} made a push late but {winner} responded to every run, "
            f"securing the victory through free throws and defensive stops in the final minutes."
        ),
    ]

    periods = [(1, 1), (2, 2), (3, 3), (4, 4 + (1 if mb.has_overtime else 0))]
    return _build_blocks(mb, chunks, scores, narratives, periods, _nba_mini_box)


# ---------------------------------------------------------------------------
# MLB
# ---------------------------------------------------------------------------


def _mlb_mini_box(h: int, a: int, dh: int, da: int) -> dict[str, Any]:
    return {
        "cumulative": {
            "home": {"runs": h, "hits": max(1, h * 2), "errors": 0},
            "away": {"runs": a, "hits": max(1, a * 2), "errors": 0},
        },
        "delta": {"runs_home": dh, "runs_away": da},
    }


def _mlb_blocks(
    mb: GameMiniBox,
    chunks: list[list[int]],
    scores: list[tuple[int, int]],
) -> list[dict[str, Any]]:
    home, away = mb.home_team, mb.away_team
    hs, as_ = mb.home_score, mb.away_score
    winner, loser = _winner_loser(home, away, hs, as_)
    q1h, q1a = scores[0]
    q2h, q2a = scores[1]
    q3h, q3a = scores[2]

    q1_leader = home if q1h >= q1a else away
    q1_score = f"{q1h}-{q1a}"
    half_leader = home if q2h >= q2a else away
    q3_leader = home if q3h >= q3a else away
    q3_trailer = away if q3h >= q3a else home

    narratives = [
        (
            f"{away} and {home} opened with sharp starting pitching from both sides, "
            f"limiting baserunners and keeping early scoring opportunities to a minimum. "
            f"{q1_leader} broke through first to take a {q1_score} lead, "
            f"capitalizing on a timely hit after working the count deep in the early innings."
        ),
        (
            f"The middle innings swung toward {half_leader}, who strung together a productive "
            f"stretch of at-bats and made the opposing bullpen pay for a lapse in command. "
            f"A multi-run frame extended the advantage to {q2h}-{q2a} through six innings, "
            f"forcing the trailing team into a position of needing a rally."
        ),
        (
            f"The seventh and eighth innings provided the critical late-game moments. "
            f"{q3_leader} protected their lead with strong bullpen work, stranding baserunners "
            f"and keeping {q3_trailer} from closing the gap. The score reached {q3h}-{q3a} "
            f"heading into the final inning, with {q3_trailer}'s lineup facing a fresh arm."
        ),
        (
            f"{winner} claimed the {hs}-{as_} result in overtime after regulation could not "
            f"separate the clubs. The extra innings required {winner} to outlast {loser} "
            f"beyond the standard nine frames, ultimately delivering the winning blow "
            f"to end the overtime session on their terms."
        ) if mb.has_overtime else (
            f"{winner} closed it out in the ninth for a {hs}-{as_} final. "
            f"{loser}'s last-inning effort came up short, as {winner}'s closer finished "
            f"with authority to send the home crowd home satisfied with the result."
        ),
    ]

    periods = [(1, 3), (4, 6), (7, 8), (9, 9 + (1 if mb.has_overtime else 0))]
    return _build_blocks(mb, chunks, scores, narratives, periods, _mlb_mini_box)


# ---------------------------------------------------------------------------
# NHL
# ---------------------------------------------------------------------------


def _nhl_mini_box(h: int, a: int, dh: int, da: int) -> dict[str, Any]:
    return {
        "cumulative": {
            "home": {"goals": h, "shots": max(10, h * 8), "saves": max(5, a * 5)},
            "away": {"goals": a, "shots": max(10, a * 8), "saves": max(5, h * 5)},
        },
        "delta": {"goals_home": dh, "goals_away": da},
    }


def _nhl_blocks(
    mb: GameMiniBox,
    chunks: list[list[int]],
    scores: list[tuple[int, int]],
) -> list[dict[str, Any]]:
    home, away = mb.home_team, mb.away_team
    hs, as_ = mb.home_score, mb.away_score
    winner, loser = _winner_loser(home, away, hs, as_)
    q1h, q1a = scores[0]
    q2h, q2a = scores[1]
    q3h, q3a = scores[2]

    q1_leader = home if q1h >= q1a else away
    q1_score = f"{q1h}-{q1a}"
    half_leader = home if q2h >= q2a else away
    q3_leader = home if q3h >= q3a else away
    q3_trailer = away if q3h >= q3a else home

    narratives = [
        (
            f"{away} and {home} opened with a structured first period marked by tight defensive "
            f"coverage and limited odd-man opportunities. Both goaltenders were sharp when called "
            f"upon, and {q1_leader} broke through to take a {q1_score} lead on a well-worked "
            f"zone entry that ended with a clean finish past the blocker."
        ),
        (
            f"The second period saw {half_leader} assert control through sustained puck "
            f"possession and effective defensive-zone clears. A power-play conversion added "
            f"to their total, and {half_leader} carried a {q2h}-{q2a} advantage into the "
            f"second intermission with their penalty kill and goaltender both performing "
            f"well under pressure."
        ),
        (
            f"The third period delivered the critical sequence that settled the contest. "
            f"{q3_leader} generated the decisive scoring chance and converted, pushing the "
            f"margin to {q3h}-{q3a} with limited time remaining. {q3_trailer} pressed for "
            f"an equalizer but could not beat the goaltender, leaving the outcome clear."
        ),
        (
            f"{winner} ended it in overtime for a {hs}-{as_} final, converting the first "
            f"real chance of the extra frame after both teams showed caution in the opening "
            f"minutes. The overtime goal capped a full sixty minutes of regulation play "
            f"that left the two clubs inseparable until {winner} stepped up."
        ) if mb.has_overtime else (
            f"{winner} skated away with a {hs}-{as_} result and two points in the standings. "
            f"{loser} made a late push and pulled their goaltender in the final minute, "
            f"but {winner} held firm and iced the puck to seal the victory."
        ),
    ]

    periods = [(1, 1), (2, 2), (3, 3), (3, 4 if mb.has_overtime else 3)]
    return _build_blocks(mb, chunks, scores, narratives, periods, _nhl_mini_box)


# ---------------------------------------------------------------------------
# Shared builder
# ---------------------------------------------------------------------------


# Story-role tags emitted by the v3 fallback template — positional, so the
# 4 deterministic blocks still surface as opening / first_separation /
# turning_point / closeout regardless of sport.
_FALLBACK_STORY_ROLES: tuple[str, ...] = (
    "opening",
    "first_separation",
    "turning_point",
    "closeout",
)


def _build_blocks(
    mb: GameMiniBox,
    chunks: list[list[int]],
    scores: list[tuple[int, int]],
    narratives: list[str],
    periods: list[tuple[int, int]],
    mini_box_fn: Any,
) -> list[dict[str, Any]]:
    roles = ["SETUP", "MOMENTUM_SHIFT", "DECISION_POINT", "RESOLUTION"]
    prev = [0, 0]
    blocks: list[dict[str, Any]] = []
    final = (mb.home_score, mb.away_score)
    score_seq = list(scores[:3]) + [final]

    for idx in range(4):
        sh, sa = score_seq[idx]
        dh = sh - prev[0]
        da = sa - prev[1]
        p_start, p_end = periods[idx]
        blocks.append({
            "block_index": idx,
            "role": roles[idx],
            "moment_indices": chunks[idx],
            "period_start": p_start,
            "period_end": p_end,
            "score_before": list(prev),
            "score_after": [sh, sa],
            "play_ids": chunks[idx],
            "key_play_ids": [],
            "narrative": narratives[idx],
            "mini_box": mini_box_fn(sh, sa, dh, da),
            # v3 contract — fallback has no segment evidence, so featured_players
            # stays unset and the score_context carries only the derived
            # signals downstream consumers need.
            "story_role": _FALLBACK_STORY_ROLES[idx],
            "leverage": "low",
            "score_context": {
                "lead_change": False,
                "largest_lead_delta": abs(sh - sa),
            },
        })
        prev = [sh, sa]

    return blocks


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class TemplateEngine:
    """Renders deterministic fallback narrative blocks from structured game data."""

    @classmethod
    def render(cls, sport: str, mini_box: GameMiniBox) -> list[dict[str, Any]]:
        """Render 4 narrative blocks for the given sport and game.

        Args:
            sport:    League code (NFL, NBA, MLB, NHL).  Case-insensitive.
            mini_box: Structured game data; no LLM calls required.

        Returns:
            List of 4 block dicts compatible with validate_blocks.py.
        """
        chunks = _distribute_moments(mini_box.total_moments, 4)
        scores = _block_scores(mini_box.home_score, mini_box.away_score)
        s = sport.upper()
        if s == "NFL":
            return _nfl_blocks(mini_box, chunks, scores)
        if s == "NBA":
            return _nba_blocks(mini_box, chunks, scores)
        if s == "MLB":
            return _mlb_blocks(mini_box, chunks, scores)
        if s == "NHL":
            return _nhl_blocks(mini_box, chunks, scores)
        return _nba_blocks(mini_box, chunks, scores)
