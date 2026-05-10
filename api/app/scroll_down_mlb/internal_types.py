"""Internal Python types used by the deck builder pipeline.

These dataclasses carry richer state than the public DTO. They include
fields like `score_after` and `runner_names_after` that the pipeline uses
internally but that the spoiler-safe `ScrollDownMlbDeckCard` DTO
intentionally omits.

Conversion to the DTO happens at the persistence/response boundary in
`service.py` — that boundary is the spoiler-safety guarantee.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

BaseName = Literal["home", "first", "second", "third"]
AdvanceTo = Literal["first", "second", "third", "home", "out"]
InningHalf = Literal["top", "bottom"]


@dataclass(frozen=True)
class RunnerAdvance:
    """One runner's movement on a play."""

    from_base: BaseName
    to: AdvanceTo
    out_at: BaseName | None = None


@dataclass
class TimelineEntry:
    """Per-play reconstructed game state. Mirror of the TS TimelineEntry."""

    play_index: int
    inning: int
    half: InningHalf
    outs_before: int
    outs_after: int
    score_before_home: int
    score_before_away: int
    score_after_home: int
    score_after_away: int
    base_state_before: dict[str, bool]
    base_state_after: dict[str, bool]
    runner_names_before: dict[str, str]  # keys: "first" / "second" / "third"
    runner_names_after: dict[str, str]
    advances: list[RunnerAdvance]
    event_type: str
    runs_scored: int
    is_scoring_play: bool
    is_tying_play: bool
    is_lead_change_play: bool
    is_late_leverage: bool
    half_from_upstream: bool


@dataclass
class BuiltPlayCard:
    """Internal play card. Parallel to the TS PlayCardData but used only
    inside the pipeline. The DTO conversion strips score_after and other
    spoiler-sensitive fields."""

    game_id: int
    play_index: int
    sort_order: int
    inning: int
    inning_half: InningHalf
    inning_label: str
    batting_team_abbr: str | None
    description: str
    score_before_home: int
    score_before_away: int
    score_after_home: int
    score_after_away: int
    outs_before: int
    outs_after: int
    base_state_before: dict[str, bool]
    base_state_after: dict[str, bool]
    runner_names_before: dict[str, str]
    runner_names_after: dict[str, str]
    advances: list[RunnerAdvance]
    event_type: str | None
    ball_path: str | None = None
    animation_profile: str | None = None
    visual_intensity: str | None = None
    batter_name: str | None = None
    pitcher_name: str | None = None
    balls_before: int | None = None
    strikes_before: int | None = None
    narrative: str | None = None
    chip_primary: str | None = None
    chip_secondary: str | None = None
    leverage_tier: int | None = None
    # Pitcher's running stat line at this play, in the form
    # "4.1 IP · 6 K · 1 BB · 2 R". Populated by the pipeline only when a
    # per-play matchup pitcher was resolved. None on plays where the
    # pitcher is unknown — the renderer hides the line in that case.
    pitcher_stat_line: str | None = None


@dataclass
class HalfInningMeta:
    scored_runs: int = 0
    had_activity: bool = False
    had_lead_change: bool = False
    had_tying: bool = False


__all__ = [
    "AdvanceTo",
    "BaseName",
    "BuiltPlayCard",
    "HalfInningMeta",
    "InningHalf",
    "RunnerAdvance",
    "TimelineEntry",
]
