"""Tests for segment_classification — v3 segment tagging + blowout merge."""

from __future__ import annotations

from app.services.pipeline.stages.block_types import NarrativeBlock, SemanticRole
from app.services.pipeline.stages.segment_classification import (
    VALID_LEVERAGE,
    VALID_STORY_ROLES,
    classify_blocks,
    format_period_range,
    merge_blowout_compression,
)


def _block(
    *,
    block_index: int,
    role: SemanticRole = SemanticRole.RESPONSE,
    period_start: int = 1,
    period_end: int = 1,
    score_before: tuple[int, int] = (0, 0),
    score_after: tuple[int, int] = (0, 0),
    moment_indices: list[int] | None = None,
    play_ids: list[int] | None = None,
    start_clock: str | None = None,
    end_clock: str | None = None,
    peak_margin: int = 0,
    peak_leader: int = 0,
) -> NarrativeBlock:
    return NarrativeBlock(
        block_index=block_index,
        role=role,
        moment_indices=moment_indices or [block_index],
        period_start=period_start,
        period_end=period_end,
        score_before=score_before,
        score_after=score_after,
        play_ids=play_ids or [block_index * 10],
        key_play_ids=[],
        start_clock=start_clock,
        end_clock=end_clock,
        peak_margin=peak_margin,
        peak_leader=peak_leader,
    )


class TestFormatPeriodRange:
    """The period_range string is sport-aware and renders clock windows when present."""

    def test_nba_single_period_with_clock_window(self) -> None:
        assert format_period_range("NBA", 4, 4, "6:39", "0:00") == "Q4 6:39–0:00"

    def test_nba_multi_period_without_clocks(self) -> None:
        assert format_period_range("NBA", 3, 4, None, None) == "Q3–Q4"

    def test_nba_multi_period_with_clocks(self) -> None:
        assert format_period_range("NBA", 3, 4, "12:00", "0:00") == "Q3 12:00–Q4 0:00"

    def test_mlb_single_inning(self) -> None:
        assert format_period_range("MLB", 1, 1, None, None) == "Inning 1"

    def test_mlb_inning_range(self) -> None:
        assert format_period_range("MLB", 8, 9, None, None) == "Inning 8–Inning 9"

    def test_nhl_period(self) -> None:
        assert format_period_range("NHL", 1, 1, "20:00", "08:12") == "P1 20:00–08:12"

    def test_nhl_overtime_label(self) -> None:
        # NHL period 4 → OT, period 5 → OT2
        assert format_period_range("NHL", 4, 4, None, None) == "OT"
        assert format_period_range("NHL", 5, 5, None, None) == "OT2"

    def test_ncaab_uses_halves(self) -> None:
        assert format_period_range("NCAAB", 2, 2, "2:14", "0:00") == "H2 2:14–0:00"

    def test_unknown_league_falls_back_to_quarters(self) -> None:
        assert format_period_range("UNKNOWN", 4, 4, None, None) == "Q4"


class TestClassifyBlocksStoryRole:
    """story_role is deterministic given block position + game-state."""

    def test_first_block_is_opening(self) -> None:
        blocks = [
            _block(block_index=0, role=SemanticRole.SETUP, period_end=1),
            _block(block_index=1, role=SemanticRole.RESPONSE, period_end=2),
            _block(block_index=2, role=SemanticRole.RESOLUTION, period_end=4),
        ]
        classify_blocks(blocks, "NBA")
        assert blocks[0].story_role == "opening"

    def test_last_block_is_closeout(self) -> None:
        blocks = [
            _block(block_index=0, role=SemanticRole.SETUP, period_end=1),
            _block(block_index=1, role=SemanticRole.RESPONSE, period_end=2),
            _block(block_index=2, role=SemanticRole.RESOLUTION, period_end=4),
        ]
        classify_blocks(blocks, "NBA")
        assert blocks[-1].story_role == "closeout"

    def test_lead_change_block_tagged_lead_change(self) -> None:
        # Away led 50-55, home flips to 60-58 → lead change.
        blocks = [
            _block(
                block_index=0,
                role=SemanticRole.SETUP,
                period_end=1,
                score_before=(0, 0),
                score_after=(50, 55),
            ),
            _block(
                block_index=1,
                role=SemanticRole.MOMENTUM_SHIFT,
                period_end=3,
                score_before=(50, 55),
                score_after=(60, 58),
            ),
            _block(
                block_index=2,
                role=SemanticRole.RESOLUTION,
                period_end=4,
                score_before=(60, 58),
                score_after=(62, 60),
            ),
        ]
        classify_blocks(blocks, "NBA")
        assert blocks[1].story_role == "lead_change"

    def test_first_separation_when_tie_becomes_lead(self) -> None:
        # Block 1 takes a tied 0-0 game to a 5-0 home lead.
        blocks = [
            _block(
                block_index=0,
                role=SemanticRole.SETUP,
                period_end=1,
                score_before=(0, 0),
                score_after=(0, 0),
            ),
            _block(
                block_index=1,
                role=SemanticRole.MOMENTUM_SHIFT,
                period_end=2,
                score_before=(0, 0),
                score_after=(5, 0),
                peak_margin=5,
                peak_leader=1,
            ),
            _block(
                block_index=2,
                role=SemanticRole.DECISION_POINT,
                period_end=3,
                score_before=(5, 0),
                score_after=(8, 2),
            ),
            _block(
                block_index=3,
                role=SemanticRole.RESOLUTION,
                period_end=4,
                score_before=(8, 2),
                score_after=(12, 4),
            ),
        ]
        classify_blocks(blocks, "NBA")
        assert blocks[1].story_role == "first_separation"
        # Subsequent meaningful-margin blocks are not first_separation again.
        assert blocks[2].story_role != "first_separation"

    def test_late_decision_point_is_turning_point(self) -> None:
        blocks = [
            _block(
                block_index=0,
                role=SemanticRole.SETUP,
                period_end=1,
                score_before=(0, 0),
                score_after=(20, 18),
            ),
            _block(
                block_index=1,
                role=SemanticRole.RESPONSE,
                period_end=2,
                score_before=(20, 18),
                score_after=(48, 50),
            ),
            _block(
                block_index=2,
                role=SemanticRole.DECISION_POINT,
                period_end=4,
                score_before=(80, 78),
                score_after=(95, 84),
                peak_margin=11,
                peak_leader=1,
            ),
            _block(
                block_index=3,
                role=SemanticRole.RESOLUTION,
                period_end=4,
                score_before=(95, 84),
                score_after=(104, 92),
            ),
        ]
        classify_blocks(blocks, "NBA")
        assert blocks[2].story_role == "turning_point"

    def test_blowout_middle_is_blowout_compression(self) -> None:
        # MLB-shape blowout: opening separation, low-leverage middle, late insurance.
        blocks = [
            _block(
                block_index=0,
                role=SemanticRole.SETUP,
                period_end=1,
                score_before=(0, 0),
                score_after=(3, 0),
                peak_margin=3,
                peak_leader=1,
            ),
            _block(
                block_index=1,
                role=SemanticRole.RESPONSE,
                period_start=2,
                period_end=5,
                score_before=(3, 0),
                score_after=(4, 0),
            ),
            _block(
                block_index=2,
                role=SemanticRole.DECISION_POINT,
                period_start=6,
                period_end=7,
                score_before=(4, 0),
                score_after=(5, 0),
            ),
            _block(
                block_index=3,
                role=SemanticRole.RESOLUTION,
                period_start=8,
                period_end=9,
                score_before=(5, 0),
                score_after=(12, 1),
            ),
        ]
        classify_blocks(blocks, "MLB", is_blowout=True)
        assert blocks[1].story_role == "blowout_compression"
        assert blocks[2].story_role == "blowout_compression"


class TestClassifyBlocksLeverage:
    """leverage tier follows score-state and game context."""

    def test_lead_change_is_high_leverage(self) -> None:
        blocks = [
            _block(
                block_index=0,
                role=SemanticRole.SETUP,
                score_before=(0, 0),
                score_after=(50, 55),
            ),
            _block(
                block_index=1,
                role=SemanticRole.MOMENTUM_SHIFT,
                period_end=4,
                score_before=(50, 55),
                score_after=(60, 58),
            ),
        ]
        classify_blocks(blocks, "NBA")
        assert blocks[1].leverage == "high"

    def test_blowout_middle_is_low_leverage(self) -> None:
        blocks = [
            _block(
                block_index=0,
                role=SemanticRole.SETUP,
                score_before=(0, 0),
                score_after=(3, 0),
            ),
            _block(
                block_index=1,
                role=SemanticRole.RESPONSE,
                period_end=5,
                score_before=(3, 0),
                score_after=(4, 0),
            ),
            _block(
                block_index=2,
                role=SemanticRole.RESOLUTION,
                period_end=9,
                score_before=(4, 0),
                score_after=(12, 1),
            ),
        ]
        classify_blocks(blocks, "MLB", is_blowout=True)
        assert blocks[1].leverage == "low"

    def test_garbage_time_block_is_low_leverage(self) -> None:
        blocks = [
            _block(
                block_index=0,
                role=SemanticRole.SETUP,
                score_before=(0, 0),
                score_after=(20, 5),
            ),
            _block(
                block_index=1,
                role=SemanticRole.RESPONSE,
                moment_indices=[10, 11, 12],
                period_end=4,
                score_before=(80, 30),
                score_after=(110, 60),
            ),
        ]
        classify_blocks(
            blocks,
            "NBA",
            is_blowout=True,
            garbage_time_idx=8,
        )
        assert blocks[1].leverage == "low"

    def test_late_close_margin_with_swing_is_high_leverage(self) -> None:
        # 4Q swing of 3 points keeping the margin at 2 → late + close → high.
        blocks = [
            _block(block_index=0, score_before=(0, 0), score_after=(50, 50)),
            _block(
                block_index=1,
                period_end=4,
                score_before=(80, 78),
                score_after=(85, 83),
            ),
            _block(
                block_index=2,
                period_end=4,
                score_before=(85, 83),
                score_after=(95, 93),
            ),
        ]
        classify_blocks(blocks, "NBA")
        assert blocks[1].leverage == "high"


class TestScoreContextPopulation:
    def test_score_context_carries_lead_change_and_largest_delta(self) -> None:
        block = _block(
            block_index=1,
            score_before=(50, 55),
            score_after=(60, 58),
            peak_margin=2,
            peak_leader=1,
        )
        blocks = [
            _block(block_index=0, score_before=(0, 0), score_after=(50, 55)),
            block,
            _block(block_index=2, period_end=4, score_before=(60, 58), score_after=(70, 68)),
        ]
        classify_blocks(blocks, "NBA")
        ctx = blocks[1].score_context
        assert ctx is not None
        assert ctx["start_score"] == [50, 55]
        assert ctx["end_score"] == [60, 58]
        assert ctx["lead_change"] is True
        # Pre-margin 5 → post-margin 2 → swing 3, peak_margin 2; takes the
        # larger of the two.
        assert ctx["largest_lead_delta"] >= 3


class TestStoryRoleAndLeverageDomains:
    def test_every_classified_block_has_valid_tags(self) -> None:
        blocks = [
            _block(block_index=0, role=SemanticRole.SETUP, score_before=(0, 0), score_after=(3, 0)),
            _block(
                block_index=1,
                role=SemanticRole.RESPONSE,
                period_end=5,
                score_before=(3, 0),
                score_after=(4, 0),
            ),
            _block(
                block_index=2,
                role=SemanticRole.RESOLUTION,
                period_end=9,
                score_before=(4, 0),
                score_after=(12, 1),
            ),
        ]
        classify_blocks(blocks, "MLB", is_blowout=True)
        for block in blocks:
            assert block.story_role in VALID_STORY_ROLES
            assert block.leverage in VALID_LEVERAGE
            assert block.period_range
            assert block.score_context is not None


class TestMergeBlowoutCompression:
    """Adjacent blowout_compression blocks collapse into one."""

    def test_two_adjacent_blowout_compression_blocks_merge(self) -> None:
        b0 = _block(block_index=0, role=SemanticRole.SETUP, score_before=(0, 0), score_after=(3, 0))
        b0.story_role = "opening"
        b0.leverage = "medium"

        b1 = _block(
            block_index=1,
            role=SemanticRole.RESPONSE,
            period_start=2,
            period_end=4,
            score_before=(3, 0),
            score_after=(4, 0),
        )
        b1.story_role = "blowout_compression"
        b1.leverage = "low"

        b2 = _block(
            block_index=2,
            role=SemanticRole.DECISION_POINT,
            period_start=5,
            period_end=7,
            score_before=(4, 0),
            score_after=(5, 0),
        )
        b2.story_role = "blowout_compression"
        b2.leverage = "low"

        b3 = _block(
            block_index=3,
            role=SemanticRole.RESOLUTION,
            period_start=8,
            period_end=9,
            score_before=(5, 0),
            score_after=(12, 1),
        )
        b3.story_role = "closeout"
        b3.leverage = "low"

        merged = merge_blowout_compression([b0, b1, b2, b3])
        assert len(merged) == 3
        # Block 1 is the merged compression. Block indices renumbered.
        assert [b.block_index for b in merged] == [0, 1, 2]
        compressed = merged[1]
        assert compressed.story_role == "blowout_compression"
        assert compressed.leverage == "low"
        assert compressed.period_start == 2
        assert compressed.period_end == 7
        assert compressed.score_before == (3, 0)
        assert compressed.score_after == (5, 0)
        assert compressed.narrative is None  # invalidated for re-render

    def test_non_compression_blocks_pass_through_unchanged(self) -> None:
        b0 = _block(block_index=0, role=SemanticRole.SETUP)
        b0.story_role = "opening"
        b1 = _block(block_index=1, role=SemanticRole.MOMENTUM_SHIFT)
        b1.story_role = "lead_change"
        b2 = _block(block_index=2, role=SemanticRole.RESOLUTION)
        b2.story_role = "closeout"

        merged = merge_blowout_compression([b0, b1, b2])
        assert len(merged) == 3
        assert [b.story_role for b in merged] == ["opening", "lead_change", "closeout"]

    def test_single_compression_block_does_not_merge(self) -> None:
        b0 = _block(block_index=0, role=SemanticRole.SETUP)
        b0.story_role = "opening"
        b1 = _block(block_index=1, role=SemanticRole.RESPONSE)
        b1.story_role = "blowout_compression"
        b1.leverage = "low"
        b2 = _block(block_index=2, role=SemanticRole.RESOLUTION)
        b2.story_role = "closeout"

        merged = merge_blowout_compression([b0, b1, b2])
        assert len(merged) == 3
        assert merged[1].story_role == "blowout_compression"


class TestClassifyBlocksIdempotent:
    def test_running_classifier_twice_produces_same_tags(self) -> None:
        blocks = [
            _block(block_index=0, role=SemanticRole.SETUP, score_before=(0, 0), score_after=(20, 18)),
            _block(
                block_index=1,
                role=SemanticRole.MOMENTUM_SHIFT,
                period_end=4,
                score_before=(20, 18),
                score_after=(40, 35),
            ),
            _block(
                block_index=2,
                role=SemanticRole.RESOLUTION,
                period_end=4,
                score_before=(40, 35),
                score_after=(50, 45),
            ),
        ]
        classify_blocks(blocks, "NBA")
        first = [(b.story_role, b.leverage, b.period_range) for b in blocks]
        classify_blocks(blocks, "NBA")
        second = [(b.story_role, b.leverage, b.period_range) for b in blocks]
        assert first == second
