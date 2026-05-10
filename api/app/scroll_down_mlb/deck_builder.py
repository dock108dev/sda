"""Deck card selection and assembly.

Ports from `scroll-down-web/web/src/lib/catchup-cards.ts`:

  * `selectPlays`           — tier 1 + scoring + tying + lead-change
                              + late-leverage force-include
  * `sampleTier2`           — deterministic tier-2 fill via mulberry32
  * `toPlayCard`            — assembles BuiltPlayCard from raw play + frame
  * `buildSceneSetter`      — builds the opening scene card
  * `humanizeDescription`   — cleans upstream description text

Selection is deterministic (gameId-seeded RNG); the same fixture always
produces the same deck.
"""

from __future__ import annotations

import re
from typing import Any

from .internal_types import BuiltPlayCard, TimelineEntry
from .visual_mapper import (
    ball_path_from_event,
    classify_animation_profile,
    visual_intensity,
)

TIER1 = 1
TIER2 = 2

CATCHUP_TARGET_TOTAL = 12
CATCHUP_SOFT_MIN = 5
CATCHUP_HARD_MAX = 18


# ---------------------------------------------------------------------------
# Tier helpers
# ---------------------------------------------------------------------------


def _name_string(value: Any) -> str | None:
    """Return a non-empty trimmed string, or None for any other input."""
    if isinstance(value, str):
        s = value.strip()
        return s or None
    return None


def _name_from_player_dict(value: Any) -> str | None:
    """The MLB scraper writes batter/pitcher to raw_data as
    `{"id": int|None, "name": str|None}`. Pull the name field out when
    the value is that dict shape; tolerate any other shape (legacy
    upstream payloads occasionally ship a bare string)."""
    if isinstance(value, dict):
        return _name_string(value.get("name"))
    return _name_string(value)


_DESCRIPTION_LEADING_VERBS = frozenset(
    {
        "singles", "doubles", "triples", "homers", "walks", "strikes",
        "grounds", "flies", "lines", "pops", "reaches", "is", "scores",
        "hits", "out", "advances", "steals", "caught", "called",
        "intentionally",
    }
)


def _name_from_description(description: Any) -> str | None:
    """Last-resort batter recovery from the play description. MLB play
    descriptions always start with the batter's name followed by a
    lowercase verb ("Aaron Judge homers on …"). Return the leading
    proper-noun phrase, or None if the description doesn't fit the
    pattern. Mirrors the same heuristic the scraper uses."""
    if not isinstance(description, str):
        return None
    text = description.strip()
    if not text:
        return None
    out: list[str] = []
    for tok in text.split():
        bare = tok.rstrip(".,;:")
        if bare.lower() in _DESCRIPTION_LEADING_VERBS:
            break
        if not bare or not bare[0].isupper():
            break
        out.append(bare)
        if len(out) >= 4:
            break
    return " ".join(out) if out else None


def _tier_of(play: dict[str, Any]) -> int:
    t = play.get("tier")
    return int(t) if isinstance(t, int | float) and not isinstance(t, bool) else TIER2


# ---------------------------------------------------------------------------
# Inning labels + description cleaner
# ---------------------------------------------------------------------------


def ordinal(n: int) -> str:
    v = abs(n)
    if 11 <= v % 100 <= 13:
        return f"{n}th"
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(v % 10, "th")
    return f"{n}{suffix}"


def build_inning_label(inning: int, half: str) -> str:
    return f"{'Top' if half == 'top' else 'Bottom'} {ordinal(inning)}"


_DESC_NUMBER_PREFIX = re.compile(r"^\d+[.:]\s*")
_DESC_REVIEW_PREAMBLE = re.compile(
    r"^.*?challenge(?:d)?(?:[^:]*?)(?:overturned|confirmed|upheld|stands)\s*:\s*",
    re.IGNORECASE,
)
_DESC_PARENS = re.compile(r"\s*\([^)]*\)\s*")
_DESC_BRACKETS = re.compile(r"\s*\[[^\]]*\]\s*")
_DESC_REPEATED_TERMINATORS = re.compile(r"([.!?])[.!?\s]*$")


def humanize_description(raw: str) -> str:
    """Light polish on the upstream description: strip parentheticals, trim
    review preambles, normalize whitespace, ensure terminating punctuation."""
    s = (raw or "").strip()
    if not s:
        return s
    s = _DESC_NUMBER_PREFIX.sub("", s)
    s = _DESC_REVIEW_PREAMBLE.sub("", s)
    s = _DESC_PARENS.sub(" ", s)
    s = _DESC_BRACKETS.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return s
    s = s[0].upper() + s[1:]
    s = _DESC_REPEATED_TERMINATORS.sub(r"\1", s)
    if not re.search(r"[.!?]$", s):
        s += "."
    return s


# ---------------------------------------------------------------------------
# Deterministic tier-2 sampling (mulberry32 PRNG)
# ---------------------------------------------------------------------------


def _mulberry32(seed: int):
    """Return a function that emits deterministic float in [0, 1)."""
    a = seed & 0xFFFFFFFF

    def next_float() -> float:
        nonlocal a
        a = (a + 0x6D2B79F5) & 0xFFFFFFFF
        t = (a ^ (a >> 15)) & 0xFFFFFFFF
        t = (t * (1 | a)) & 0xFFFFFFFF
        t = (t + ((t ^ (t >> 7)) * (61 | t)) & 0xFFFFFFFF) ^ t
        t = t & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296.0

    return next_float


def sample_tier_2(
    pool: list[dict[str, Any]], quota: int, game_id: int
) -> list[dict[str, Any]]:
    """Deterministic shuffle-and-take. Same gameId always picks the same set."""
    if quota <= 0:
        return []
    if quota >= len(pool):
        return list(pool)
    rng = _mulberry32(game_id)
    indices = list(range(len(pool)))
    # Mirror the TS Fisher-Yates partial shuffle: only swap the last `quota`
    # positions.
    for i in range(len(indices) - 1, len(indices) - 1 - quota, -1):
        j = int(rng() * (i + 1))
        indices[i], indices[j] = indices[j], indices[i]
    picked = sorted(indices[len(indices) - quota :])
    return [pool[i] for i in picked]


# ---------------------------------------------------------------------------
# Selection (with audit reasons)
# ---------------------------------------------------------------------------


SelectionReason = str  # "tier-1" | "scoring" | "tying" | "lead-change" | "late-leverage" | …


def select_plays(
    plays: list[dict[str, Any]],
    timeline: dict[int, TimelineEntry],
    game_id: int,
) -> tuple[set[int], dict[int, list[SelectionReason]]]:
    """Return (selected_play_indices, reasons_per_play).

    Pass 1: must-include (tier 1 + scoring + tying + lead-change + late-leverage)
    Pass 2: deterministic tier-2 fill scaled by must-include count
    Pass 3: record reasons for plays that never had a chance
    """
    reasons: dict[int, list[SelectionReason]] = {}

    def add_reason(pid: int, r: SelectionReason) -> None:
        lst = reasons.setdefault(pid, [])
        if r not in lst:
            lst.append(r)

    must: set[int] = set()
    for play in plays:
        pid = int(play.get("playIndex", 0))
        t = timeline.get(pid)
        if not t:
            add_reason(pid, "missing-data")
            continue
        if _tier_of(play) == TIER1:
            must.add(pid)
            add_reason(pid, "tier-1")
        if t.is_scoring_play:
            must.add(pid)
            add_reason(pid, "scoring")
        if t.is_tying_play:
            must.add(pid)
            add_reason(pid, "tying")
        if t.is_lead_change_play:
            must.add(pid)
            add_reason(pid, "lead-change")
        if t.is_late_leverage:
            must.add(pid)
            add_reason(pid, "late-leverage")

    optional = [
        p
        for p in plays
        if int(p.get("playIndex", 0)) not in must and _tier_of(p) <= TIER2
    ]
    natural_pad = max(2, round(len(must) * 0.4))
    desired = min(CATCHUP_HARD_MAX, max(CATCHUP_SOFT_MIN, len(must) + natural_pad))
    cap = max(len(must), CATCHUP_HARD_MAX)
    final_desired = min(desired, cap)
    quota = max(0, final_desired - len(must))
    sampled = sample_tier_2(optional, quota, game_id)
    sampled_ids = {int(p.get("playIndex", 0)) for p in sampled}

    for p in optional:
        pid = int(p.get("playIndex", 0))
        if pid in sampled_ids:
            add_reason(pid, "tier-2-sampled")
        else:
            add_reason(pid, "tier-2-not-sampled")

    for p in plays:
        pid = int(p.get("playIndex", 0))
        if pid in must or pid in sampled_ids:
            continue
        if _tier_of(p) > TIER2:
            add_reason(pid, "tier-3-skipped")
        elif pid not in reasons:
            add_reason(pid, "no-tier-not-sampled")

    selected = must | sampled_ids
    return selected, reasons


# ---------------------------------------------------------------------------
# Card assembly
# ---------------------------------------------------------------------------


def to_play_card(
    game_id: int,
    sort_order: int,
    play: dict[str, Any],
    frame: TimelineEntry,
    home_probable_pitcher: str | None = None,
    away_probable_pitcher: str | None = None,
    pitcher_of_record: str | None = None,
    pitcher_stat_line: str | None = None,
) -> BuiltPlayCard:
    """Assemble a BuiltPlayCard from a raw play + reconstructed frame."""
    description = humanize_description(play.get("description") or "")
    ball_path = ball_path_from_event(frame.event_type, play.get("description") or "")
    profile = classify_animation_profile(frame.event_type, play.get("description") or "")

    # Batter name resolution. `play["batter"]` is the dict the scraper
    # wrote to raw_data — `{"id": ..., "name": ...}` — so the previous
    # `play.get("batter") or play.get("playerName")` chain returned the
    # dict, failed the `isinstance(str)` guard, and silently nulled the
    # name. Pull `["name"]` out of the dict, then fall through to
    # `playerName` (normalized column), then to the play description
    # (always batter-led for MLB), so live games never render the
    # generic "The batter…" placeholder.
    batter_name = (
        _name_string(play.get("batterName"))
        or _name_from_player_dict(play.get("batter"))
        or _name_string(play.get("playerName"))
        or _name_from_description(play.get("description"))
    )

    # Pitcher name resolution. Order:
    #   1. `pitcher_of_record` from MLBPitcherGameStats. Only populated
    #      after the boxscore is ingested → null on every live game.
    #   2. Per-play pitcher from the scraper's raw_data (`pitcher.name`).
    #      The live scraper writes this for every play, so it carries
    #      through during live games when (1) is empty.
    #   3. Probable starter from the schedule. Currently always None
    #      because `data_source._serialize_game` hardcodes it; remains
    #      here as the documented fallback for when that gets wired up.
    pitcher_name = pitcher_of_record
    if not pitcher_name:
        pitcher_name = _name_from_player_dict(play.get("pitcher"))
    if not pitcher_name:
        pitcher_name = (
            home_probable_pitcher if frame.half == "top" else away_probable_pitcher
        )
    if isinstance(pitcher_name, str):
        pitcher_name = pitcher_name.strip() or None

    balls_before = (
        play.get("ballsBefore")
        or play.get("balls")
        or (play.get("countBefore") or {}).get("balls")
        or (play.get("count") or {}).get("balls")
    )
    strikes_before = (
        play.get("strikesBefore")
        or play.get("strikes")
        or (play.get("countBefore") or {}).get("strikes")
        or (play.get("count") or {}).get("strikes")
    )
    balls_before = int(balls_before) if isinstance(balls_before, int | float) and not isinstance(balls_before, bool) else None
    strikes_before = (
        int(strikes_before)
        if isinstance(strikes_before, int | float) and not isinstance(strikes_before, bool)
        else None
    )

    return BuiltPlayCard(
        game_id=game_id,
        play_index=frame.play_index,
        sort_order=sort_order,
        inning=frame.inning,
        inning_half=frame.half,
        inning_label=build_inning_label(frame.inning, frame.half),
        batting_team_abbr=play.get("teamAbbreviation"),
        description=description,
        score_before_home=frame.score_before_home,
        score_before_away=frame.score_before_away,
        score_after_home=frame.score_after_home,
        score_after_away=frame.score_after_away,
        outs_before=frame.outs_before,
        outs_after=frame.outs_after,
        base_state_before=frame.base_state_before,
        base_state_after=frame.base_state_after,
        runner_names_before=frame.runner_names_before,
        runner_names_after=frame.runner_names_after,
        advances=frame.advances,
        event_type=frame.event_type,
        ball_path=ball_path,
        animation_profile=profile,
        visual_intensity=visual_intensity(frame.event_type),
        batter_name=batter_name,
        pitcher_name=pitcher_name,
        balls_before=balls_before,
        strikes_before=strikes_before,
        pitcher_stat_line=pitcher_stat_line,
    )


# ---------------------------------------------------------------------------
# Scene setter
# ---------------------------------------------------------------------------


def build_scene_setter(
    *,
    game_id: int,
    home_team: str,
    away_team: str,
    home_team_abbr: str | None,
    away_team_abbr: str | None,
    game_date: str,
    home_probable_pitcher: str | None = None,
    away_probable_pitcher: str | None = None,
    venue: str | None = None,
) -> dict[str, Any]:
    """Return a dict shaped like the TS SceneSetterCard (for parity)."""
    return {
        "kind": "scene-setter",
        "gameId": game_id,
        "cardId": f"{game_id}-scene",
        "index": 0,
        "homeTeam": home_team,
        "awayTeam": away_team,
        "homeTeamAbbr": home_team_abbr or "HME",
        "awayTeamAbbr": away_team_abbr or "AWY",
        "firstPitch": game_date,
        "homeProbablePitcher": home_probable_pitcher,
        "awayProbablePitcher": away_probable_pitcher,
        "venue": venue,
    }


__all__ = [
    "build_inning_label",
    "build_scene_setter",
    "humanize_description",
    "ordinal",
    "sample_tier_2",
    "select_plays",
    "to_play_card",
    "CATCHUP_HARD_MAX",
    "CATCHUP_SOFT_MIN",
    "CATCHUP_TARGET_TOTAL",
]
