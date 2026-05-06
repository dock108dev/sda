"""V3 segment classification — tag blocks with the gameflow contract fields.

Runs after ``group_roles.assign_roles`` so existing structural roles
(SETUP/MOMENTUM_SHIFT/RESPONSE/DECISION_POINT/RESOLUTION) are present
when the v3 classifier picks the narrative beat.

Outputs per block:
    - ``story_role`` ∈ {opening, first_separation, response, lead_change,
      turning_point, closeout, blowout_compression}
    - ``leverage`` ∈ {low, medium, high}
    - ``period_range`` formatted for the sport (Q4 6:39–0:00 / Inning 8–9 /
      P1 14:36)
    - ``score_context`` carrying lead_change flag and largest_lead_delta
      inside the block. Block-level ``score_before`` / ``score_after``
      remain the SSOT for segment endpoints; this layer carries only the
      derived per-segment signals.

A second pass merges adjacent low-leverage blocks in blowout games into a
single ``blowout_compression`` block — addressing the brief's complaint
that "Inning 1 → Inning 1–7 → Inning 8–9" reads as the engine giving up.
"""

from __future__ import annotations

from typing import Any

from .block_types import NarrativeBlock, SemanticRole
from .group_roles import calculate_swing_metrics
from .league_config import LEAGUE_CONFIG

VALID_STORY_ROLES: frozenset[str] = frozenset(
    [
        "opening",
        "first_separation",
        "response",
        "lead_change",
        "turning_point",
        "closeout",
        "blowout_compression",
    ]
)

VALID_LEVERAGE: frozenset[str] = frozenset(["low", "medium", "high"])

# A score swing at or above this fraction of the league's `momentum_swing`
# threshold counts as a real beat. Below it, the block is structural padding.
_BEAT_SWING_FRACTION = 0.5


def _format_clock(clock: str | None) -> str | None:
    """Strip whitespace and return None for empty strings."""
    if clock is None:
        return None
    cleaned = str(clock).strip()
    return cleaned or None


def _period_label_prefix(league_code: str, period: int) -> str:
    """Sport-aware period prefix. NBA/NFL/NCAAB use Q, NHL uses P, MLB uses Inning."""
    code = (league_code or "").upper()
    if code == "MLB":
        return f"Inning {period}"
    if code == "NHL":
        # OT gets a special label rather than P4/P5/...
        cfg = LEAGUE_CONFIG.get("NHL", {})
        regulation = int(cfg.get("regulation_periods", 3))
        if period > regulation:
            ot_index = period - regulation
            return "OT" if ot_index == 1 else f"OT{ot_index}"
        return f"P{period}"
    if code == "NCAAB":
        return f"H{period}"  # halves
    return f"Q{period}"


def format_period_range(
    league_code: str,
    period_start: int,
    period_end: int,
    start_clock: str | None,
    end_clock: str | None,
) -> str:
    """Render a human-readable period range. Examples:

        NBA  Q4 6:39–0:00     (single period with clock window)
        NBA  Q3–Q4            (multi-period, clocks unavailable)
        NHL  P1 14:36–08:12   (single period, clock window)
        MLB  Inning 8–9       (clock-less)
        MLB  Inning 1         (single-inning span)
    """
    start_prefix = _period_label_prefix(league_code, period_start)
    end_prefix = _period_label_prefix(league_code, period_end)
    sc = _format_clock(start_clock)
    ec = _format_clock(end_clock)

    if period_start == period_end:
        if sc and ec:
            return f"{start_prefix} {sc}–{ec}"
        if sc:
            return f"{start_prefix} {sc}"
        return start_prefix

    # Multi-period span. Show clocks only when both ends have one — partial
    # clocks across a period boundary look noisy and rarely add information.
    if sc and ec:
        return f"{start_prefix} {sc}–{end_prefix} {ec}"
    return f"{start_prefix}–{end_prefix}"


def _largest_lead_delta(block: NarrativeBlock) -> int:
    """Largest single-direction margin swing inside the block.

    Uses the block's recorded ``peak_margin`` when available (group_helpers
    populates it from per-moment scoring). Falls back to the difference
    between the start and end margins.
    """
    start_margin = abs(block.score_before[0] - block.score_before[1])
    end_margin = abs(block.score_after[0] - block.score_after[1])
    swing = abs(end_margin - start_margin)
    if block.peak_margin and block.peak_margin > swing:
        return int(block.peak_margin)
    return int(swing)


def _score_context(block: NarrativeBlock) -> dict[str, Any]:
    """Derived signals only. Block-level ``score_before`` / ``score_after``
    remain the SSOT for segment endpoints — duplicating them here would
    create a sync hazard."""
    metrics = calculate_swing_metrics(block)
    return {
        "lead_change": bool(metrics["has_lead_change"]),
        "largest_lead_delta": _largest_lead_delta(block),
    }


def _classify_leverage(
    block: NarrativeBlock,
    cfg: dict[str, Any],
    is_blowout: bool,
    is_garbage_time: bool,
    is_late_game: bool,
) -> str:
    """Map a block to a leverage tier.

    high — lead change, or close-margin late-game beat.
    medium — meaningful swing without lead change, or any scoring beat in a
             non-blowout game.
    low — blowout middle, garbage time, or no-score structural blocks.
    """
    metrics = calculate_swing_metrics(block)
    swing = int(metrics["net_swing"])
    has_lead_change = bool(metrics["has_lead_change"])

    if is_garbage_time:
        return "low"

    if has_lead_change:
        return "high"

    close_margin = int(cfg.get("close_game_margin", 7))
    end_margin = abs(block.score_after[0] - block.score_after[1])
    home_delta = block.score_after[0] - block.score_before[0]
    away_delta = block.score_after[1] - block.score_before[1]
    scoring_activity = home_delta + away_delta

    # Late + close: any scoring activity in the segment keeps leverage high,
    # even when the lead doesn't change. Clutch-time stretches where both
    # teams trade buckets to keep a 2-point game tight should not get
    # demoted to low just because the net swing is zero.
    if is_late_game and end_margin <= close_margin and scoring_activity > 0:
        return "high"

    momentum_swing = int(cfg.get("momentum_swing", 8))

    # Blowout middle blocks default to low. The opening separation block
    # carries swing >= momentum_swing (1st-inning HR, opening 8-0 run, etc.)
    # so it correctly earns medium below; small piling-on swings stay low.
    if is_blowout:
        if swing >= momentum_swing:
            return "medium"
        return "low"

    if swing >= momentum_swing:
        return "medium"

    if swing > 0:
        return "medium"
    return "low"


def _classify_story_role(
    block: NarrativeBlock,
    block_index: int,
    block_count: int,
    has_seen_separation: bool,
    is_blowout: bool,
    is_late_game: bool,
    cfg: dict[str, Any],
) -> str:
    """Pick the v3 story_role for a block.

    Heuristic order:
        - First block → opening
        - Last block → closeout
        - lead-change inside the block → lead_change
        - meaningful swing creating a non-zero margin from a tied/<=1 prior
          state, before any prior separation has been seen → first_separation
        - late-game decisive sequence → turning_point
        - low-leverage middle of a blowout → blowout_compression
        - default → response
    """
    metrics = calculate_swing_metrics(block)
    swing = int(metrics["net_swing"])
    has_lead_change = bool(metrics["has_lead_change"])

    if block_index == 0:
        return "opening"

    if block_index == block_count - 1:
        return "closeout"

    if has_lead_change:
        return "lead_change"

    momentum_swing = int(cfg.get("momentum_swing", 8))
    deficit_overcome = int(cfg.get("deficit_overcome", 6))

    start_margin = abs(block.score_before[0] - block.score_before[1])
    end_margin = abs(block.score_after[0] - block.score_after[1])

    is_first_separation = (
        not has_seen_separation
        and start_margin <= 1
        and end_margin >= max(2, deficit_overcome // 2)
        and swing >= int(momentum_swing * _BEAT_SWING_FRACTION)
    )
    if is_first_separation:
        return "first_separation"

    # Inside a blowout, any non-decisive middle block is compression. Run this
    # check BEFORE the late-game turning_point gate so a DECISION_POINT
    # role in the final innings of a 12-1 game isn't mis-promoted: the brief
    # explicitly says "do not pretend a blowout was dramatic". The opening
    # separation already exited above via first_separation, and the closeout
    # block is short-circuited by block_index == block_count-1.
    if is_blowout and swing < momentum_swing:
        return "blowout_compression"

    if is_late_game and (
        swing >= momentum_swing
        or block.role == SemanticRole.DECISION_POINT
    ):
        return "turning_point"

    return "response"


def _is_late_game(block: NarrativeBlock, cfg: dict[str, Any]) -> bool:
    late_period = int(cfg.get("late_game_period", 4))
    return block.period_end >= late_period


def classify_blocks(
    blocks: list[NarrativeBlock],
    league_code: str,
    *,
    is_blowout: bool = False,
    garbage_time_idx: int | None = None,
    decisive_moment_idx: int | None = None,
) -> None:
    """Tag each block with story_role / leverage / period_range / score_context.

    Mutates the block list in place. Idempotent: re-running over an already-
    classified list produces the same values.
    """
    if not blocks:
        return

    cfg = LEAGUE_CONFIG.get((league_code or "").upper(), LEAGUE_CONFIG["NBA"])
    block_count = len(blocks)
    has_seen_separation = False

    for idx, block in enumerate(blocks):
        # A block is in garbage time when its first moment is past the
        # garbage-time index. Falls back to False when the index is missing.
        in_garbage_time = (
            is_blowout
            and garbage_time_idx is not None
            and block.moment_indices
            and min(block.moment_indices) >= garbage_time_idx
        )

        late_game = _is_late_game(block, cfg)

        story_role = _classify_story_role(
            block,
            block_index=idx,
            block_count=block_count,
            has_seen_separation=has_seen_separation,
            is_blowout=is_blowout,
            is_late_game=late_game,
            cfg=cfg,
        )
        if story_role == "first_separation":
            has_seen_separation = True

        leverage = _classify_leverage(
            block,
            cfg=cfg,
            is_blowout=is_blowout,
            is_garbage_time=bool(in_garbage_time),
            is_late_game=late_game,
        )

        block.story_role = story_role
        block.leverage = leverage
        block.period_range = format_period_range(
            league_code,
            block.period_start,
            block.period_end,
            block.start_clock,
            block.end_clock,
        )
        block.score_context = _score_context(block)


def merge_blowout_compression(blocks: list[NarrativeBlock]) -> list[NarrativeBlock]:
    """Merge adjacent ``blowout_compression`` blocks into a single block.

    The brief's "Inning 1 → Inning 1–7 → Inning 8–9" complaint is the
    symptom of two structurally-similar low-leverage middle blocks sitting
    next to each other in a blowout. Once the v3 classifier tags both as
    ``blowout_compression``, this pass collapses them so the flow reads
    as: opening separation → middle innings turned the lead into a rout →
    late insurance. SETUP/RESOLUTION are never merged; only middle runs of
    ``blowout_compression`` are collapsed.

    Returns a NEW list. The caller is responsible for re-running role
    assignment + classification on the merged list if required, but we
    preserve the merged block's ``story_role='blowout_compression'`` and
    set its ``leverage='low'`` so the post-merge classifier is a no-op.
    """
    if not blocks:
        return blocks

    merged: list[NarrativeBlock] = []
    i = 0
    while i < len(blocks):
        block = blocks[i]
        if block.story_role != "blowout_compression":
            merged.append(block)
            i += 1
            continue

        # Walk forward collecting consecutive blowout_compression blocks.
        run_end = i
        while (
            run_end + 1 < len(blocks)
            and blocks[run_end + 1].story_role == "blowout_compression"
        ):
            run_end += 1

        if run_end == i:
            merged.append(block)
            i += 1
            continue

        run = blocks[i : run_end + 1]
        first = run[0]
        last = run[-1]
        merged_moment_indices: list[int] = []
        merged_play_ids: list[int] = []
        merged_key_play_ids: list[int] = []
        peak_margin = 0
        peak_leader = first.peak_leader
        for b in run:
            merged_moment_indices.extend(b.moment_indices)
            merged_play_ids.extend(b.play_ids)
            merged_key_play_ids.extend(b.key_play_ids)
            if abs(b.peak_margin) > abs(peak_margin):
                peak_margin = b.peak_margin
                peak_leader = b.peak_leader

        merged_block = NarrativeBlock(
            block_index=first.block_index,
            role=first.role,
            moment_indices=merged_moment_indices,
            period_start=first.period_start,
            period_end=last.period_end,
            score_before=first.score_before,
            score_after=last.score_after,
            play_ids=merged_play_ids,
            key_play_ids=merged_key_play_ids,
            narrative=None,  # invalidate — will be re-rendered downstream
            mini_box=None,
            peak_margin=peak_margin,
            peak_leader=peak_leader,
            start_clock=first.start_clock,
            end_clock=last.end_clock,
            story_role="blowout_compression",
            leverage="low",
            period_range=None,  # recomputed by caller
            featured_players=None,
            score_context={
                "lead_change": False,
                "largest_lead_delta": max(
                    int(_largest_lead_delta(b)) for b in run
                ),
            },
        )
        merged.append(merged_block)
        i = run_end + 1

    # Renumber block_index so downstream invariants hold.
    for new_idx, b in enumerate(merged):
        b.block_index = new_idx
    return merged
