"""Server-side play tier classification.

Classifies every PBP play into Tier 1 (scoring), Tier 2 (notable non-scoring),
or Tier 3 (routine) so consumers don't duplicate this logic on-device.

All plays that change the score are Tier 1 regardless of game context.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TIER_2_TYPES: dict[str, frozenset[str]] = {
    "NBA": frozenset(
        ["foul", "turnover", "steal", "block", "offensive foul", "offensive_rebound"]
    ),
    "NCAAB": frozenset(
        [
            "personal_foul",
            "shooting_foul",
            "offensive_foul",
            "technical_foul",
            "flagrant_foul",
            "foul",
            "turnover",
            "steal",
            "block",
            "offensive_rebound",
        ]
    ),
    "NHL": frozenset(
        ["penalty", "delayed_penalty"]
    ),
    "MLB": frozenset([
        "strikeout", "walk", "intent_walk", "hit_by_pitch",
        "stolen_base", "caught_stealing", "field_error",
        "wild_pitch", "balk", "double_play", "triple_play",
        "pickoff", "passed_ball",
    ]),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Import here so the module can be used without circular-import issues at
# module level; the actual schema type is only needed for the return value.
from ..routers.sports.schemas import PlayEntry, TieredPlayGroup  # noqa: E402
from ..routers.sports.schemas.common import ScoreObject  # noqa: E402


def classify_all_tiers(
    plays: list[PlayEntry],
    league_code: str,
) -> list[int]:
    """Classify each play in *plays* as Tier 1, 2, or 3.

    Returns a list of ints (1/2/3) parallel to *plays*.

    Tier 1: Any play that changes the score (made shot, goal, free throw, etc.)
    Tier 2: Notable non-scoring plays (fouls, turnovers, blocks, etc.)
    Tier 3: Everything else (routine plays)
    """
    if not plays:
        return []

    tier_2_types = _TIER_2_TYPES.get(league_code.upper(), frozenset())

    # --- backfill scores (carry forward last known) ---
    score_pairs: list[tuple[tuple[int, int], tuple[int, int]]] = []
    last_home, last_away = 0, 0
    for p in plays:
        before = (last_home, last_away)
        h = p.score.home if p.score is not None else last_home
        a = p.score.away if p.score is not None else last_away
        after = (h, a)
        score_pairs.append((before, after))
        last_home, last_away = h, a

    # --- classify ---
    tiers: list[int] = []
    for i, p in enumerate(plays):
        before, after = score_pairs[i]
        home_before, away_before = before
        home_after, away_after = after

        is_scoring = (home_after != home_before) or (away_after != away_before)

        if is_scoring:
            tiers.append(1)
        elif p.play_type and p.play_type.lower() in tier_2_types:
            tiers.append(2)
        else:
            tiers.append(3)

    return tiers


def group_tier3_plays(
    plays: list[PlayEntry],
    tiers: list[int],
) -> list[TieredPlayGroup]:
    """Group consecutive Tier-3 plays into collapsed summaries.

    All index fields (start_index, end_index, play_indices) use the actual
    play_index identifiers from the PBP feed, not list positions.
    """
    groups: list[TieredPlayGroup] = []
    run_plays: list[PlayEntry] = []

    def _flush() -> None:
        if not run_plays:
            return
        types = []
        seen: set[str] = set()
        for p in run_plays:
            pt = (p.play_type or "unknown").lower()
            if pt not in seen:
                seen.add(pt)
                types.append(pt)
        play_ids = [p.play_index for p in run_plays]
        label = f"{len(run_plays)} plays: {', '.join(types)}"
        groups.append(
            TieredPlayGroup(
                start_index=play_ids[0],
                end_index=play_ids[-1],
                play_indices=play_ids,
                summary_label=label,
            )
        )

    for i, tier in enumerate(tiers):
        if tier == 3:
            run_plays.append(plays[i])
        else:
            _flush()
            run_plays = []

    _flush()
    return groups


# ---------------------------------------------------------------------------
# Timeline enrichment
# ---------------------------------------------------------------------------

# Phase classification by league and period
_PHASE_MAP: dict[str, dict[int, str]] = {
    "NBA": {1: "early", 2: "early", 3: "mid", 4: "late"},
    "NCAAB": {1: "early", 2: "late"},
    "NHL": {1: "early", 2: "mid", 3: "late"},
    "MLB": {1: "early", 2: "early", 3: "early", 4: "mid", 5: "mid", 6: "mid", 7: "late", 8: "late", 9: "late"},
}

# Regular-time period counts (periods above this are OT)
_REGULAR_PERIODS: dict[str, int] = {"NBA": 4, "NCAAB": 2, "NHL": 3, "MLB": 9}


def _classify_phase(period: int | None, league_code: str) -> str | None:
    """Classify a period into a game phase."""
    if period is None:
        return None
    code = league_code.upper()
    regular_max = _REGULAR_PERIODS.get(code, 4)
    if period > regular_max:
        return "ot"
    phase_map = _PHASE_MAP.get(code, {})
    return phase_map.get(period)


def enrich_play_entries(
    plays: list[PlayEntry],
    league_code: str,
    home_abbr: str,
    away_abbr: str,
) -> None:
    """Enrich play entries in-place with score deltas and phase info.

    Adds scoreChanged, scoringTeamAbbr, pointsScored, scoreBefore, and
    phase to each PlayEntry.

    Args:
        plays: List of PlayEntry objects (mutated in-place).
        league_code: League code (e.g., "NBA", "NHL").
        home_abbr: Home team abbreviation.
        away_abbr: Away team abbreviation.
    """
    if not plays:
        return

    last_home = 0
    last_away = 0

    for play in plays:
        cur_home = play.score.home if play.score is not None else last_home
        cur_away = play.score.away if play.score is not None else last_away

        play.score_before = ScoreObject(home=last_home, away=last_away)

        home_diff = cur_home - last_home
        away_diff = cur_away - last_away
        changed = home_diff != 0 or away_diff != 0
        play.score_changed = changed

        if changed:
            if home_diff > 0 and away_diff == 0:
                play.scoring_team_abbr = home_abbr
                play.points_scored = home_diff
            elif away_diff > 0 and home_diff == 0:
                play.scoring_team_abbr = away_abbr
                play.points_scored = away_diff
            else:
                # Both changed (unusual) — attribute to larger change
                if home_diff >= away_diff:
                    play.scoring_team_abbr = home_abbr
                    play.points_scored = home_diff
                else:
                    play.scoring_team_abbr = away_abbr
                    play.points_scored = away_diff

        play.phase = _classify_phase(play.quarter, league_code)

        last_home = cur_home
        last_away = cur_away
