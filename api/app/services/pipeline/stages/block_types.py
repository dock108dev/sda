"""Block types and data structures for narrative block system.

This module defines the core types for the block-based narrative system:
- SemanticRole: Enum for block roles (SETUP, MOMENTUM_SHIFT, etc.)
- NarrativeBlock: Dataclass for block data

BLOCK SYSTEM OVERVIEW
=====================
Blocks replace moment-level narratives. Instead of 15-25 moments with 6-10
sentences each, we produce 3-7 blocks with 1-5 sentences each (~65 words).

This ensures the collapsed game flow is consumable in 60-90 seconds.

SEMANTIC ROLES
==============
Each block has exactly one semantic role:
- SETUP: Early context, how game began (always first block)
- MOMENTUM_SHIFT: First meaningful swing
- RESPONSE: Counter-run, stabilization
- DECISION_POINT: Sequence that decided outcome
- RESOLUTION: How game ended (always last block)

Constraints:
- No role appears more than twice
- SETUP always first
- RESOLUTION always last
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class SemanticRole(str, Enum):
    """Semantic role for a narrative block.

    Each block has exactly one role that describes its function
    in the game's narrative arc.
    """

    SETUP = "SETUP"  # Early context, how game began
    MOMENTUM_SHIFT = "MOMENTUM_SHIFT"  # First meaningful swing
    RESPONSE = "RESPONSE"  # Counter-run, stabilization
    DECISION_POINT = "DECISION_POINT"  # Sequence that decided outcome
    RESOLUTION = "RESOLUTION"  # How game ended

    @classmethod
    def get_description(cls, role: SemanticRole) -> str:
        """Get a description of the role for prompt context."""
        descriptions = {
            cls.SETUP: "Sets the stage - how the game began and early context",
            cls.MOMENTUM_SHIFT: "First meaningful swing in the game's direction",
            cls.RESPONSE: "Counter-run or stabilization after a swing",
            cls.DECISION_POINT: "The sequence that decided the game's outcome",
            cls.RESOLUTION: "How the game concluded",
        }
        return descriptions.get(role, "")


@dataclass
class NarrativeBlock:
    """A narrative block grouping multiple moments.

    Blocks are the consumer-facing narrative output, replacing moment
    narratives. Each block represents a stretch of play that should
    be described in 1-5 sentences (~65 words).

    Attributes:
        block_index: 0-indexed position in the flow (0-6)
        role: Semantic role describing the block's function
        moment_indices: Which moments are grouped into this block
        period_start: First period covered by this block
        period_end: Last period covered by this block
        score_before: Score at the start of this block [home, away]
        score_after: Score at the end of this block [home, away]
        play_ids: All play_indices in this block
        key_play_ids: 1-3 most important plays for narrative focus
        narrative: Generated narrative text (1-5 sentences, ~65 words)
        mini_box: Cumulative box score at end of block with segment deltas
    """

    # --- Identity / structural fields (kept for all schema versions) ---
    block_index: int
    role: SemanticRole
    moment_indices: list[int]
    period_start: int
    period_end: int
    score_before: tuple[int, int]
    score_after: tuple[int, int]
    play_ids: list[int]
    key_play_ids: list[int]
    narrative: str | None = None
    mini_box: dict[str, Any] | None = None
    start_clock: str | None = None  # Game clock at block start (from first moment)
    end_clock: str | None = None  # Game clock at block end (from last moment)
    # `peak_margin` / `peak_leader` survive v2→v3 because they are read by
    # the structural role assigner (assign_roles → calculate_swing_metrics)
    # to detect lead swings. They are NOT consumer-facing — they live only
    # on the internal NarrativeBlock dataclass and never reach the schema.
    peak_margin: int = 0  # Largest absolute margin within this block
    peak_leader: int = 0  # 1=home led at peak, -1=away led at peak
    # --- v3 fields per the gameflow brief ---
    # Distinct from `role` (the SemanticRole enum used by structural validators):
    # `story_role` is the narrative beat the segmenter chose, drawn from
    # {opening, first_separation, response, lead_change, turning_point,
    # closeout, blowout_compression}. `leverage` and `featured_players`
    # carry the segment's evidence so player callouts can act as proof
    # rather than decoration.
    story_role: str | None = None
    leverage: str | None = None  # "low" | "medium" | "high"
    period_range: str | None = None  # e.g. "Q4 6:39–0:00", "Inning 8–9"
    featured_players: list[dict[str, Any]] | None = None
    score_context: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        result = {
            "block_index": self.block_index,
            "role": self.role.value,
            "moment_indices": self.moment_indices,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "score_before": list(self.score_before),
            "score_after": list(self.score_after),
            "play_ids": self.play_ids,
            "key_play_ids": self.key_play_ids,
            "narrative": self.narrative,
        }
        if self.mini_box is not None:
            result["mini_box"] = self.mini_box
        if self.peak_margin:
            result["peak_margin"] = self.peak_margin
            result["peak_leader"] = self.peak_leader
        if self.start_clock is not None:
            result["start_clock"] = self.start_clock
        if self.end_clock is not None:
            result["end_clock"] = self.end_clock
        if self.story_role is not None:
            result["story_role"] = self.story_role
        if self.leverage is not None:
            result["leverage"] = self.leverage
        if self.period_range is not None:
            result["period_range"] = self.period_range
        if self.featured_players is not None:
            result["featured_players"] = self.featured_players
        if self.score_context is not None:
            result["score_context"] = self.score_context
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NarrativeBlock:
        """Create from dict (e.g., from JSON)."""
        return cls(
            block_index=data["block_index"],
            role=SemanticRole(data["role"]),
            moment_indices=data["moment_indices"],
            period_start=data["period_start"],
            period_end=data["period_end"],
            score_before=tuple(data["score_before"]),
            score_after=tuple(data["score_after"]),
            play_ids=data["play_ids"],
            key_play_ids=data["key_play_ids"],
            narrative=data.get("narrative"),
            mini_box=data.get("mini_box"),
            peak_margin=data.get("peak_margin", 0),
            peak_leader=data.get("peak_leader", 0),
            start_clock=data.get("start_clock"),
            end_clock=data.get("end_clock"),
            story_role=data.get("story_role"),
            leverage=data.get("leverage"),
            period_range=data.get("period_range"),
            featured_players=data.get("featured_players"),
            score_context=data.get("score_context"),
        )

    @property
    def point_swing(self) -> int:
        """Calculate the net point swing in this block.

        Positive = home team gained ground
        Negative = away team gained ground
        """
        home_delta = self.score_after[0] - self.score_before[0]
        away_delta = self.score_after[1] - self.score_before[1]
        return home_delta - away_delta

    @property
    def total_points(self) -> int:
        """Total points scored in this block."""
        return (
            (self.score_after[0] - self.score_before[0])
            + (self.score_after[1] - self.score_before[1])
        )

    @property
    def word_count(self) -> int:
        """Word count of the narrative."""
        if not self.narrative:
            return 0
        return len(self.narrative.split())


@dataclass
class BlocksOutput:
    """Output schema for GROUP_BLOCKS stage.

    Contains the grouped blocks with metadata for validation.
    """

    blocks: list[NarrativeBlock]
    block_count: int
    total_moments: int
    lead_changes: int
    largest_run: int

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "blocks": [b.to_dict() for b in self.blocks],
            "block_count": self.block_count,
            "total_moments": self.total_moments,
            "lead_changes": self.lead_changes,
            "largest_run": self.largest_run,
        }


# Block count limits
MIN_BLOCKS = 3  # Allow 3-block flows for blowouts
MAX_BLOCKS = 7

# Narrative constraints — per BRAINDUMP §Narrative generation rules:
# 1-2 sentences per block, 25-55 words normally.
MIN_WORDS_PER_BLOCK = 25
MAX_WORDS_PER_BLOCK = 55
TARGET_WORDS_PER_BLOCK = 40
MAX_TOTAL_WORDS = 400

# Key play constraints
MIN_KEY_PLAYS = 1
MAX_KEY_PLAYS = 3
