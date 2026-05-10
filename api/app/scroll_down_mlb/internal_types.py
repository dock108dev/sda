"""Internal Python types used by the deck builder pipeline.

These dataclasses carry richer state than the public DTO. They include
fields like `score_after` and `runner_names_after` that the pipeline uses
internally but that the spoiler-safe `ScrollDownMlbDeckCard` DTO
intentionally omits.

Conversion to the DTO happens at the persistence/response boundary in
`service.py` — that boundary is the spoiler-safety guarantee.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional


BaseName = Literal["home", "first", "second", "third"]
AdvanceTo = Literal["first", "second", "third", "home", "out"]
InningHalf = Literal["top", "bottom"]


@dataclass(frozen=True)
class RunnerAdvance:
    """One runner's movement on a play."""

    from_base: BaseName
    to: AdvanceTo
    out_at: Optional[BaseName] = None


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
    batting_team_abbr: Optional[str]
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
    event_type: Optional[str]
    ball_path: Optional[str] = None
    animation_profile: Optional[str] = None
    visual_intensity: Optional[str] = None
    batter_name: Optional[str] = None
    pitcher_name: Optional[str] = None
    balls_before: Optional[int] = None
    strikes_before: Optional[int] = None
    narrative: Optional[str] = None
    chip_primary: Optional[str] = None
    chip_secondary: Optional[str] = None
    leverage_tier: Optional[int] = None


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
