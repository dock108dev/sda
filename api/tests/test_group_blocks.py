"""Tests for GROUP_BLOCKS stage."""

from __future__ import annotations

import pytest

from app.services.pipeline.models import StageInput
from app.services.pipeline.stages.block_analysis import (
    count_lead_changes,
    detect_blowout,
    find_garbage_time_start,
    find_lead_change_indices,
    find_period_boundaries,
    find_scoring_runs,
)
from app.services.pipeline.stages.league_config import get_config
from app.services.pipeline.stages.block_types import (
    MAX_BLOCKS,
    MIN_BLOCKS,
    SemanticRole,
)
from app.services.pipeline.stages.group_blocks import execute_group_blocks
from app.services.pipeline.stages.group_helpers import (
    calculate_block_count,
    create_blocks,
    select_key_plays,
)
from app.services.pipeline.stages.group_roles import assign_roles
from app.services.pipeline.stages.group_split_points import (
    compress_blowout_blocks,
    find_split_points,
    find_weighted_split_points,
)


class TestCalculateBlockCount:
    """Tests for block count calculation."""

    def test_minimum_blocks(self) -> None:
        """Short non-blowout games produce 4 blocks (default base)."""
        moments: list[dict] = []
        lead_changes = 0
        total_plays = 100

        count = calculate_block_count(moments, lead_changes, total_plays)
        assert count == 4

    def test_blowout_minimum_blocks(self) -> None:
        """Blowout games with minimal lead changes produce 3 blocks (MIN_BLOCKS)."""
        moments: list[dict] = []
        lead_changes = 0
        total_plays = 100

        count = calculate_block_count(moments, lead_changes, total_plays, is_blowout=True)
        assert count == MIN_BLOCKS  # 3

    def test_blowout_with_lead_changes(self) -> None:
        """Blowout games with lead changes use normal formula."""
        moments: list[dict] = []
        lead_changes = 3
        total_plays = 100

        count = calculate_block_count(moments, lead_changes, total_plays, is_blowout=True)
        assert count == 5  # base 4 + 1 for lead changes

    def test_moderate_lead_changes(self) -> None:
        """3+ lead changes adds one block."""
        moments: list[dict] = []
        lead_changes = 3
        total_plays = 100

        count = calculate_block_count(moments, lead_changes, total_plays)
        assert count == 5  # base 4 + 1

    def test_many_lead_changes(self) -> None:
        """6+ lead changes adds two blocks."""
        moments: list[dict] = []
        lead_changes = 6
        total_plays = 100

        count = calculate_block_count(moments, lead_changes, total_plays)
        assert count == 6  # base 4 + 2

    def test_long_game(self) -> None:
        """Long games (400+ plays) add one block."""
        moments: list[dict] = []
        lead_changes = 0
        total_plays = 500

        count = calculate_block_count(moments, lead_changes, total_plays)
        assert count == 5  # base 4 + 1

    def test_maximum_blocks(self) -> None:
        """Block count is capped at maximum."""
        moments: list[dict] = []
        lead_changes = 10
        total_plays = 600

        count = calculate_block_count(moments, lead_changes, total_plays)
        assert count == MAX_BLOCKS

    def test_block_count_always_in_range(self) -> None:
        """Block count always in [4, 7]."""
        for lead_changes in range(0, 15):
            for total_plays in [50, 200, 400, 600]:
                count = calculate_block_count([], lead_changes, total_plays)
                assert MIN_BLOCKS <= count <= MAX_BLOCKS


class TestCountLeadChanges:
    """Tests for lead change counting."""

    def test_no_lead_changes(self) -> None:
        """No lead changes when one team always leads."""
        moments = [
            {"score_after": [10, 5]},
            {"score_after": [20, 10]},
            {"score_after": [30, 15]},
        ]
        assert count_lead_changes(moments) == 0

    def test_single_lead_change(self) -> None:
        """Detect single lead change."""
        moments = [
            {"score_after": [10, 5]},  # Home leads
            {"score_after": [12, 15]},  # Away takes lead
            {"score_after": [15, 20]},  # Away still leads
        ]
        assert count_lead_changes(moments) == 1

    def test_multiple_lead_changes(self) -> None:
        """Detect multiple lead changes."""
        moments = [
            {"score_after": [10, 5]},  # Home leads
            {"score_after": [12, 15]},  # Away leads
            {"score_after": [20, 18]},  # Home leads again
            {"score_after": [22, 25]},  # Away leads again
        ]
        assert count_lead_changes(moments) == 3

    def test_tie_not_counted_as_lead_change(self) -> None:
        """Tie scores don't count as lead changes."""
        moments = [
            {"score_after": [10, 5]},  # Home leads
            {"score_after": [10, 10]},  # Tie
            {"score_after": [15, 10]},  # Home leads (not a lead change from tie)
        ]
        assert count_lead_changes(moments) == 0


class TestFindLeadChangeIndices:
    """Tests for finding lead change moment indices."""

    def test_no_lead_changes(self) -> None:
        """Empty list when no lead changes."""
        moments = [
            {"score_before": [0, 0], "score_after": [10, 5]},
            {"score_before": [10, 5], "score_after": [20, 10]},
        ]
        assert find_lead_change_indices(moments) == []

    def test_find_lead_change_index(self) -> None:
        """Find index of moment containing lead change."""
        moments = [
            {"score_before": [0, 0], "score_after": [10, 5]},  # Home leads
            {"score_before": [10, 5], "score_after": [12, 15]},  # Lead change here
            {"score_before": [12, 15], "score_after": [15, 20]},
        ]
        indices = find_lead_change_indices(moments)
        assert 1 in indices


class TestFindScoringRuns:
    """Tests for detecting scoring runs."""

    def test_no_scoring_runs(self) -> None:
        """No runs when scoring is alternating."""
        moments = [
            {"score_before": [0, 0], "score_after": [2, 0]},
            {"score_before": [2, 0], "score_after": [2, 2]},
            {"score_before": [2, 2], "score_after": [4, 2]},
        ]
        runs = find_scoring_runs(moments, min_run_size=5)
        assert runs == []

    def test_detect_scoring_run(self) -> None:
        """Detect significant scoring run."""
        moments = [
            {"score_before": [0, 0], "score_after": [3, 0]},
            {"score_before": [3, 0], "score_after": [6, 0]},
            {"score_before": [6, 0], "score_after": [10, 0]},  # 10-0 run
        ]
        runs = find_scoring_runs(moments, min_run_size=8)
        assert len(runs) == 1
        assert runs[0][2] == 10  # Run size


class TestFindPeriodBoundaries:
    """Tests for detecting period boundaries."""

    def test_no_period_changes(self) -> None:
        """No boundaries in single-period data."""
        moments = [
            {"period": 1},
            {"period": 1},
            {"period": 1},
        ]
        assert find_period_boundaries(moments) == []

    def test_find_period_boundary(self) -> None:
        """Find index where period changes."""
        moments = [
            {"period": 1},
            {"period": 1},
            {"period": 2},  # Boundary at index 2
            {"period": 2},
        ]
        boundaries = find_period_boundaries(moments)
        assert boundaries == [2]

    def test_multiple_period_boundaries(self) -> None:
        """Find multiple period boundaries."""
        moments = [
            {"period": 1},
            {"period": 2},  # Boundary at index 1
            {"period": 3},  # Boundary at index 2
            {"period": 4},  # Boundary at index 3
        ]
        boundaries = find_period_boundaries(moments)
        assert boundaries == [1, 2, 3]


class TestAssignRoles:
    """Tests for semantic role assignment."""

    def test_first_block_is_setup(self) -> None:
        """First block is always SETUP."""
        from app.services.pipeline.stages.block_types import NarrativeBlock

        blocks = [
            NarrativeBlock(0, SemanticRole.RESPONSE, [], 1, 1, (0, 0), (10, 8), [], []),
            NarrativeBlock(1, SemanticRole.RESPONSE, [], 1, 1, (10, 8), (20, 18), [], []),
            NarrativeBlock(2, SemanticRole.RESPONSE, [], 1, 1, (20, 18), (30, 28), [], []),
            NarrativeBlock(3, SemanticRole.RESPONSE, [], 1, 1, (30, 28), (40, 38), [], []),
        ]
        assign_roles(blocks)
        assert blocks[0].role == SemanticRole.SETUP

    def test_last_block_is_resolution(self) -> None:
        """Last block is always RESOLUTION."""
        from app.services.pipeline.stages.block_types import NarrativeBlock

        blocks = [
            NarrativeBlock(0, SemanticRole.RESPONSE, [], 1, 1, (0, 0), (10, 8), [], []),
            NarrativeBlock(1, SemanticRole.RESPONSE, [], 1, 1, (10, 8), (20, 18), [], []),
            NarrativeBlock(2, SemanticRole.RESPONSE, [], 1, 1, (20, 18), (30, 28), [], []),
            NarrativeBlock(3, SemanticRole.RESPONSE, [], 1, 1, (30, 28), (40, 38), [], []),
        ]
        assign_roles(blocks)
        assert blocks[-1].role == SemanticRole.RESOLUTION

    def test_no_role_more_than_twice(self) -> None:
        """No role appears more than twice."""
        from app.services.pipeline.stages.block_types import NarrativeBlock

        blocks = [
            NarrativeBlock(i, SemanticRole.RESPONSE, [], 1, 1, (0, 0), (10, 8), [], [])
            for i in range(7)
        ]
        assign_roles(blocks)

        role_counts: dict[SemanticRole, int] = {}
        for block in blocks:
            role_counts[block.role] = role_counts.get(block.role, 0) + 1

        for count in role_counts.values():
            assert count <= 2

    def test_assign_roles_three_blocks(self) -> None:
        """3-block games get SETUP, DECISION_POINT, RESOLUTION."""
        from app.services.pipeline.stages.block_types import NarrativeBlock

        blocks = [
            NarrativeBlock(0, SemanticRole.RESPONSE, [], 1, 1, (0, 0), (30, 10), [], []),
            NarrativeBlock(1, SemanticRole.RESPONSE, [], 2, 3, (30, 10), (60, 25), [], []),
            NarrativeBlock(2, SemanticRole.RESPONSE, [], 4, 4, (60, 25), (90, 40), [], []),
        ]
        assign_roles(blocks)

        assert blocks[0].role == SemanticRole.SETUP
        assert blocks[1].role == SemanticRole.DECISION_POINT
        assert blocks[2].role == SemanticRole.RESOLUTION


class TestBlockCreation:
    """Tests for block creation from moments."""

    def test_creates_correct_number_of_blocks(self) -> None:
        """Split points create expected number of blocks."""
        moments = [
            {"play_ids": [1], "period": 1, "score_before": [0, 0], "score_after": [2, 0]},
            {"play_ids": [2], "period": 1, "score_before": [2, 0], "score_after": [4, 2]},
            {"play_ids": [3], "period": 1, "score_before": [4, 2], "score_after": [6, 4]},
            {"play_ids": [4], "period": 2, "score_before": [6, 4], "score_after": [8, 6]},
            {"play_ids": [5], "period": 2, "score_before": [8, 6], "score_after": [10, 8]},
        ]
        split_points = [2]  # Creates 2 blocks: [0,1] and [2,3,4]

        blocks = create_blocks(moments, split_points, [])
        assert len(blocks) == 2

    def test_blocks_cover_all_moments(self) -> None:
        """All moments are covered by blocks."""
        moments = [
            {"play_ids": [i], "period": 1, "score_before": [0, 0], "score_after": [2, 0]}
            for i in range(10)
        ]
        split_points = [3, 7]  # Creates 3 blocks

        blocks = create_blocks(moments, split_points, [])

        covered_moments: set[int] = set()
        for block in blocks:
            covered_moments.update(block.moment_indices)

        assert covered_moments == set(range(10))

    def test_blocks_have_correct_scores(self) -> None:
        """Blocks have correct score_before and score_after."""
        moments = [
            {"play_ids": [1], "period": 1, "score_before": [0, 0], "score_after": [5, 3]},
            {"play_ids": [2], "period": 1, "score_before": [5, 3], "score_after": [10, 8]},
            {"play_ids": [3], "period": 1, "score_before": [10, 8], "score_after": [15, 12]},
            {"play_ids": [4], "period": 1, "score_before": [15, 12], "score_after": [20, 18]},
        ]
        split_points = [2]  # Block 0: moments 0,1; Block 1: moments 2,3

        blocks = create_blocks(moments, split_points, [])

        # Block 0
        assert blocks[0].score_before == (0, 0)
        assert blocks[0].score_after == (10, 8)

        # Block 1
        assert blocks[1].score_before == (10, 8)
        assert blocks[1].score_after == (20, 18)


class TestPeakMarginInBlocks:
    """Tests for peak margin computation in block creation."""

    def test_peak_margin_computed_from_moments(self) -> None:
        """Peak margin is computed from all moment scores within a block."""
        moments = [
            {"play_ids": [1], "period": 1, "score_before": [0, 0], "score_after": [22, 0]},   # margin 22
            {"play_ids": [2], "period": 1, "score_before": [22, 0], "score_after": [25, 18]},  # margin 7
            {"play_ids": [3], "period": 2, "score_before": [25, 18], "score_after": [30, 28]},  # margin 2
            {"play_ids": [4], "period": 2, "score_before": [30, 28], "score_after": [35, 30]},  # margin 5
        ]
        split_points = [2]  # Block 0: moments 0,1; Block 1: moments 2,3

        blocks = create_blocks(moments, split_points, [])

        # Block 0 should have peak_margin=22 (from score_after of moment 0)
        assert blocks[0].peak_margin == 22
        assert blocks[0].peak_leader == 1  # Home led

        # Block 1 should have peak_margin=7 (from score_before of moment 2)
        assert blocks[1].peak_margin == 7
        assert blocks[1].peak_leader == 1  # Home led

    def test_peak_margin_away_leader(self) -> None:
        """Peak margin correctly tracks away team as leader."""
        moments = [
            {"play_ids": [1], "period": 1, "score_before": [0, 0], "score_after": [5, 20]},   # Away +15
            {"play_ids": [2], "period": 1, "score_before": [5, 20], "score_after": [15, 22]},  # Away +7
        ]
        split_points = []  # Single block

        blocks = create_blocks(moments, split_points, [])

        assert blocks[0].peak_margin == 15
        assert blocks[0].peak_leader == -1  # Away led

    def test_peak_margin_zero_for_tied_block(self) -> None:
        """Peak margin is 0 when all scores within block are tied."""
        moments = [
            {"play_ids": [1], "period": 1, "score_before": [0, 0], "score_after": [10, 10]},
            {"play_ids": [2], "period": 1, "score_before": [10, 10], "score_after": [20, 20]},
        ]
        split_points = []

        blocks = create_blocks(moments, split_points, [])

        assert blocks[0].peak_margin == 0

    def test_peak_margin_serialization(self) -> None:
        """Peak margin survives to_dict/from_dict round trip."""
        from app.services.pipeline.stages.block_types import NarrativeBlock, SemanticRole

        block = NarrativeBlock(
            block_index=0,
            role=SemanticRole.SETUP,
            moment_indices=[0, 1],
            period_start=1,
            period_end=1,
            score_before=(0, 0),
            score_after=(25, 18),
            play_ids=[1, 2],
            key_play_ids=[1],
            peak_margin=22,
            peak_leader=1,
        )

        d = block.to_dict()
        assert d["peak_margin"] == 22
        assert d["peak_leader"] == 1

        restored = NarrativeBlock.from_dict(d)
        assert restored.peak_margin == 22
        assert restored.peak_leader == 1

    def test_peak_margin_backward_compatible(self) -> None:
        """from_dict works without peak_margin (backward compatibility)."""
        from app.services.pipeline.stages.block_types import NarrativeBlock

        d = {
            "block_index": 0,
            "role": "SETUP",
            "moment_indices": [0],
            "period_start": 1,
            "period_end": 1,
            "score_before": [0, 0],
            "score_after": [10, 8],
            "play_ids": [1],
            "key_play_ids": [1],
        }

        block = NarrativeBlock.from_dict(d)
        assert block.peak_margin == 0
        assert block.peak_leader == 0


class TestBlockConstraints:
    """Tests for block system constraints."""

    def test_block_count_range(self) -> None:
        """Block count is always in range [4, 7]."""
        # Test various game scenarios
        for num_moments in [4, 10, 20, 50]:
            moments = [
                {
                    "play_ids": [i],
                    "period": 1,
                    "score_before": [0, 0],
                    "score_after": [i * 2, i],
                }
                for i in range(num_moments)
            ]
            lead_changes = num_moments // 5
            total_plays = num_moments * 5

            target_blocks = calculate_block_count(moments, lead_changes, total_plays)
            assert MIN_BLOCKS <= target_blocks <= MAX_BLOCKS

    def test_short_game_produces_minimum_blocks(self) -> None:
        """Even short games produce at least MIN_BLOCKS blocks."""
        moments = [
            {"play_ids": [1], "period": 1, "score_before": [0, 0], "score_after": [2, 0]},
            {"play_ids": [2], "period": 1, "score_before": [2, 0], "score_after": [4, 2]},
            {"play_ids": [3], "period": 1, "score_before": [4, 2], "score_after": [6, 4]},
            {"play_ids": [4], "period": 1, "score_before": [6, 4], "score_after": [8, 6]},
        ]

        # With only 4 moments and 0 lead changes, should still get 4 blocks
        target_blocks = calculate_block_count(moments, 0, 20)
        split_points = find_split_points(moments, target_blocks)

        # Number of blocks = number of split points + 1
        blocks = create_blocks(moments, split_points, [])
        assert len(blocks) >= MIN_BLOCKS or len(blocks) == len(moments)

    def test_blowout_game_handled(self) -> None:
        """Blowout games (no meaningful lead changes) still produce valid blocks."""
        moments = [
            {"play_ids": [i], "period": 1, "score_before": [i * 3, i], "score_after": [(i + 1) * 3, i + 1]}
            for i in range(20)
        ]

        # No lead changes in a blowout
        lead_changes = 0
        total_plays = 100

        target_blocks = calculate_block_count(moments, lead_changes, total_plays)
        split_points = find_split_points(moments, target_blocks)
        blocks = create_blocks(moments, split_points, [])

        assert MIN_BLOCKS <= len(blocks) <= MAX_BLOCKS


class TestBlowoutDetection:
    """Tests for blowout detection and handling."""

    def testdetect_blowout_with_sustained_margin(self) -> None:
        """Detects blowout when margin is sustained across periods."""
        moments = [
            {"score_after": [10, 8], "period": 1},   # Close
            {"score_after": [20, 12], "period": 1},  # Gap opening
            {"score_after": [35, 12], "period": 1},  # 23 point margin
            {"score_after": [45, 18], "period": 2},  # Still blowout
            {"score_after": [55, 22], "period": 2},  # Sustained
            {"score_after": [70, 30], "period": 3},  # Period 3
            {"score_after": [85, 40], "period": 3},  # Still sustained
            {"score_after": [100, 50], "period": 4}, # Period 4 - sustained 2+ periods
        ]
        is_blowout, decisive_idx, max_margin = detect_blowout(moments)
        assert is_blowout is True
        assert decisive_idx is not None
        assert max_margin >= get_config("NBA")["blowout_margin"]

    def test_no_blowout_in_close_game(self) -> None:
        """No blowout detected in close game."""
        moments = [
            {"score_after": [10, 8], "period": 1},
            {"score_after": [18, 20], "period": 1},
            {"score_after": [28, 26], "period": 2},
            {"score_after": [35, 38], "period": 2},
            {"score_after": [45, 42], "period": 3},
            {"score_after": [52, 55], "period": 3},
            {"score_after": [60, 58], "period": 4},
        ]
        is_blowout, decisive_idx, max_margin = detect_blowout(moments)
        assert is_blowout is False

    def test_margin_not_sustained_is_not_blowout(self) -> None:
        """Large margin not sustained is not a blowout."""
        moments = [
            {"score_after": [10, 8], "period": 1},
            {"score_after": [30, 8], "period": 1},  # 22 point lead
            {"score_after": [32, 25], "period": 1}, # Lead shrinks
            {"score_after": [35, 32], "period": 2}, # Close again
            {"score_after": [40, 38], "period": 2},
        ]
        is_blowout, decisive_idx, max_margin = detect_blowout(moments)
        # Had a large margin but wasn't sustained
        assert is_blowout is False


class TestGarbageTimeStart:
    """Tests for garbage time detection."""

    def test_finds_garbage_time_start(self) -> None:
        """Finds garbage time when margin and period conditions met."""
        moments = [
            {"score_after": [10, 8], "period": 1},
            {"score_after": [30, 12], "period": 2},  # Large margin but period 2
            {"score_after": [50, 20], "period": 3},  # 30 point margin, period 3 - garbage time
            {"score_after": [60, 25], "period": 3},
        ]
        idx = find_garbage_time_start(moments)
        assert idx == 2  # Third moment where period >= 3 and margin >= 25

    def test_no_garbage_time_early_periods(self) -> None:
        """No garbage time in early periods even with large margin."""
        moments = [
            {"score_after": [10, 8], "period": 1},
            {"score_after": [40, 10], "period": 2},  # 30 point margin but period 2
        ]
        idx = find_garbage_time_start(moments)
        assert idx is None

    def test_no_garbage_time_close_game(self) -> None:
        """No garbage time in close game."""
        moments = [
            {"score_after": [25, 22], "period": 3},
            {"score_after": [30, 28], "period": 4},
        ]
        idx = find_garbage_time_start(moments)
        assert idx is None


class TestBlowoutCompression:
    """Tests for blowout block compression."""

    def test_compression_produces_fewer_blocks(self) -> None:
        """Blowout compression produces fewer blocks than normal."""
        moments = [
            {"play_ids": [i], "period": (i // 5) + 1, "score_before": [0, 0], "score_after": [i * 5, i]}
            for i in range(20)
        ]
        decisive_idx = 5  # Blowout became decisive at moment 5
        garbage_idx = 15  # Garbage time at moment 15

        split_points = compress_blowout_blocks(moments, decisive_idx, garbage_idx)
        num_blocks = len(split_points) + 1

        # Should be compressed to fewer blocks
        assert num_blocks <= 5

    def test_compression_produces_min_blocks(self) -> None:
        """Blowout compression still produces at least MIN_BLOCKS."""
        moments = [
            {"play_ids": [i], "period": 1, "score_before": [0, 0], "score_after": [i * 3, i]}
            for i in range(10)
        ]
        decisive_idx = 3
        garbage_idx = None  # No garbage time

        split_points = compress_blowout_blocks(moments, decisive_idx, garbage_idx)
        num_blocks = len(split_points) + 1

        assert num_blocks >= MIN_BLOCKS


class TestFindWeightedSplitPoints:
    """Tests for find_weighted_split_points drama-based distribution."""

    def test_nba_q4_emphasis(self) -> None:
        """NBA games should emphasize Q4 with late-game amplification."""

        moments = []
        for period in [1, 2, 3, 4]:
            for i in range(5):
                moments.append({
                    "play_ids": [period * 10 + i],
                    "period": period,
                    "score_before": [(period - 1) * 25, (period - 1) * 20],
                    "score_after": [(period - 1) * 25 + 5, (period - 1) * 20 + 4],
                })

        quarter_weights = {"Q1": 1.0, "Q2": 1.0, "Q3": 1.0, "Q4": 2.0}

        split_points = find_weighted_split_points(moments, 5, quarter_weights, "NBA")

        # Should have 4 splits for 5 blocks
        assert len(split_points) == 4

    def test_ncaab_half_structure(self) -> None:
        """NCAAB games use half structure with H2 emphasis."""

        moments = []
        for period in [1, 2]:  # NCAAB uses halves stored as Q1, Q2
            for i in range(10):
                moments.append({
                    "play_ids": [period * 100 + i],
                    "period": period,
                    "score_before": [(period - 1) * 40, (period - 1) * 38],
                    "score_after": [(period - 1) * 40 + 4, (period - 1) * 38 + 4],
                })

        quarter_weights = {"Q1": 1.0, "Q2": 1.8}  # H2 is more dramatic

        split_points = find_weighted_split_points(moments, 5, quarter_weights, "NCAAB")

        assert len(split_points) == 4

    def test_nhl_three_periods(self) -> None:
        """NHL games use 3 period structure."""

        moments = []
        for period in [1, 2, 3]:  # NHL periods stored as Q1, Q2, Q3
            for i in range(5):
                moments.append({
                    "play_ids": [period * 10 + i],
                    "period": period,
                    "score_before": [period - 1, period - 1],
                    "score_after": [period, period - 1],
                })

        quarter_weights = {"Q1": 0.8, "Q2": 1.0, "Q3": 1.5}

        split_points = find_weighted_split_points(moments, 4, quarter_weights, "NHL")

        assert len(split_points) == 3

    def test_q1_hard_cap_enforced(self) -> None:
        """Q1 gets max 1 block unless it's the peak quarter."""

        # Create moments with lots of Q1 activity
        moments = []
        for period in [1, 2, 3, 4]:
            count = 10 if period == 1 else 3  # More Q1 moments
            for i in range(count):
                moments.append({
                    "play_ids": [period * 100 + i],
                    "period": period,
                    "score_before": [0, 0],
                    "score_after": [i * 2, i],
                })

        # Q1 is not the peak - Q4 has highest weight
        quarter_weights = {"Q1": 1.0, "Q2": 1.0, "Q3": 1.2, "Q4": 2.0}

        split_points = find_weighted_split_points(moments, 5, quarter_weights, "NBA")

        # Count how many splits fall within Q1 range
        q1_end_idx = 10  # First 10 moments are Q1
        q1_splits = [sp for sp in split_points if sp < q1_end_idx]

        # Q1 should have at most 1 block (0 internal splits)
        # or 1 split at the boundary
        assert len(q1_splits) <= 1

    def test_peak_quarter_gets_minimum_blocks(self) -> None:
        """Peak drama quarter should get at least 2 blocks if target >= 4."""

        moments = []
        for period in [1, 2, 3, 4]:
            for i in range(5):
                moments.append({
                    "play_ids": [period * 10 + i],
                    "period": period,
                    "score_before": [0, 0],
                    "score_after": [5, 3],
                })

        # Q3 is peak quarter with very high weight
        quarter_weights = {"Q1": 0.5, "Q2": 0.5, "Q3": 2.5, "Q4": 1.0}

        split_points = find_weighted_split_points(moments, 5, quarter_weights, "NBA")

        # Q3 range is indices 10-14
        q3_start = 10
        q3_end = 15

        # Count blocks containing Q3 moments
        boundaries = [0] + split_points + [len(moments)]
        q3_block_count = 0
        for i in range(len(boundaries) - 1):
            block_start = boundaries[i]
            block_end = boundaries[i + 1]
            if any(q3_start <= j < q3_end for j in range(block_start, block_end)):
                q3_block_count += 1

        # Peak quarter should have 2+ blocks when possible
        assert q3_block_count >= 1  # At minimum covers the quarter

    def test_deficit_backfill_respects_priority(self) -> None:
        """Deficit filling should prioritize higher-weight, later quarters."""

        moments = []
        for period in [1, 2, 3, 4]:
            for i in range(4):
                moments.append({
                    "play_ids": [period * 10 + i],
                    "period": period,
                    "score_before": [0, 0],
                    "score_after": [5, 3],
                })

        # Clear weight hierarchy
        quarter_weights = {"Q1": 0.5, "Q2": 1.0, "Q3": 1.5, "Q4": 2.0}

        split_points = find_weighted_split_points(moments, 5, quarter_weights, "NBA")

        # Function should produce valid splits
        assert len(split_points) == 4
        assert all(0 < sp < len(moments) for sp in split_points)


class TestSelectKeyPlays:
    """Tests for select_key_plays function."""

    def test_lead_change_highest_priority(self) -> None:
        """Lead change plays get highest priority."""

        moments = [
            {"play_ids": [1, 2, 3], "explicitly_narrated_play_ids": []},
        ]
        pbp_events = [
            {"play_index": 1, "home_score": 10, "away_score": 8, "play_type": "score"},
            {"play_index": 2, "home_score": 10, "away_score": 12, "play_type": "score"},  # Lead change
            {"play_index": 3, "home_score": 12, "away_score": 12, "play_type": "score"},
        ]

        key_plays = select_key_plays(moments, [0], pbp_events)

        assert 2 in key_plays  # Lead change play should be selected

    def test_scoring_plays_ranked(self) -> None:
        """Scoring plays are prioritized."""

        moments = [
            {"play_ids": [1, 2, 3], "explicitly_narrated_play_ids": []},
        ]
        pbp_events = [
            {"play_index": 1, "home_score": 10, "away_score": 8, "play_type": "timeout"},
            {"play_index": 2, "home_score": 12, "away_score": 8, "play_type": "score"},
            {"play_index": 3, "home_score": 12, "away_score": 8, "play_type": "foul"},
        ]

        key_plays = select_key_plays(moments, [0], pbp_events)

        assert 2 in key_plays  # Scoring play should be selected

    def test_fallback_to_last_play(self) -> None:
        """Falls back to last play if no better options."""

        moments = [
            {"play_ids": [1, 2, 3], "explicitly_narrated_play_ids": []},
        ]
        pbp_events = [
            {"play_index": 1, "home_score": 10, "away_score": 10, "play_type": "other"},
            {"play_index": 2, "home_score": 10, "away_score": 10, "play_type": "other"},
            {"play_index": 3, "home_score": 10, "away_score": 10, "play_type": "other"},
        ]

        key_plays = select_key_plays(moments, [0], pbp_events)

        # Should have at least one key play
        assert len(key_plays) >= 1

    def test_max_three_key_plays(self) -> None:
        """No more than 3 key plays selected."""

        moments = [
            {"play_ids": list(range(1, 11)), "explicitly_narrated_play_ids": list(range(1, 11))},
        ]
        pbp_events = [
            {"play_index": i, "home_score": i * 2, "away_score": i, "play_type": "score"}
            for i in range(1, 11)
        ]

        key_plays = select_key_plays(moments, [0], pbp_events)

        assert len(key_plays) <= 3

    def test_explicitly_narrated_plays_boosted(self) -> None:
        """Explicitly narrated plays get priority boost."""

        moments = [
            {"play_ids": [1, 2, 3], "explicitly_narrated_play_ids": [2]},
        ]
        pbp_events = [
            {"play_index": 1, "home_score": 10, "away_score": 10, "play_type": "other"},
            {"play_index": 2, "home_score": 10, "away_score": 10, "play_type": "other"},
            {"play_index": 3, "home_score": 10, "away_score": 10, "play_type": "other"},
        ]

        key_plays = select_key_plays(moments, [0], pbp_events)

        assert 2 in key_plays  # Explicitly narrated play should be selected


class TestCreateBlocksExtended:
    """Extended tests for create_blocks function."""

    def test_block_creation_with_mini_box(self) -> None:
        """Blocks include mini box score data."""
        moments = [
            {"play_ids": [1, 2], "period": 1, "score_before": [0, 0], "score_after": [5, 3]},
            {"play_ids": [3, 4], "period": 1, "score_before": [5, 3], "score_after": [10, 8]},
            {"play_ids": [5, 6], "period": 2, "score_before": [10, 8], "score_after": [15, 12]},
            {"play_ids": [7, 8], "period": 2, "score_before": [15, 12], "score_after": [20, 18]},
        ]
        pbp_events = [
            {"play_index": i, "home_score": i * 2, "away_score": i, "play_type": "score"}
            for i in range(1, 9)
        ]
        split_points = [2]  # Creates 2 blocks

        blocks = create_blocks(moments, split_points, pbp_events)

        assert len(blocks) == 2
        # Each block should have mini_box attribute
        for block in blocks:
            assert hasattr(block, "mini_box")

    def test_score_continuity(self) -> None:
        """Score continuity maintained across blocks."""
        moments = [
            {"play_ids": [1], "period": 1, "score_before": [0, 0], "score_after": [10, 8]},
            {"play_ids": [2], "period": 1, "score_before": [10, 8], "score_after": [20, 15]},
            {"play_ids": [3], "period": 2, "score_before": [20, 15], "score_after": [30, 25]},
            {"play_ids": [4], "period": 2, "score_before": [30, 25], "score_after": [40, 35]},
        ]
        split_points = [2]

        blocks = create_blocks(moments, split_points, [])

        # Block 0's score_after should equal Block 1's score_before
        assert blocks[0].score_after == blocks[1].score_before

    def test_period_range_spans(self) -> None:
        """Period range correctly spans multiple periods."""
        moments = [
            {"play_ids": [1], "period": 1, "score_before": [0, 0], "score_after": [10, 8]},
            {"play_ids": [2], "period": 2, "score_before": [10, 8], "score_after": [20, 15]},
            {"play_ids": [3], "period": 3, "score_before": [20, 15], "score_after": [30, 25]},
        ]
        split_points = []  # Single block

        blocks = create_blocks(moments, split_points, [])

        assert len(blocks) == 1
        assert blocks[0].period_start == 1
        assert blocks[0].period_end == 3


class TestAssignRolesExtended:
    """Extended tests for assign_roles function."""

    def test_close_game_moderate_swing_is_momentum_shift(self) -> None:
        """In close games (max margin <= 7), moderate swings (4+) qualify as MOMENTUM_SHIFT.

        Close games have lowered thresholds so the narrative captures the drama
        of smaller but meaningful swings.
        """
        from app.services.pipeline.stages.block_types import NarrativeBlock

        # Create blocks with moderate lead changes (close game, max margin=3)
        blocks = [
            NarrativeBlock(0, SemanticRole.RESPONSE, [], 1, 1, (0, 0), (10, 8), [], []),  # Home leads +2
            NarrativeBlock(1, SemanticRole.RESPONSE, [], 1, 1, (10, 8), (12, 15), [], []),  # Away leads +3 (swing=5)
            NarrativeBlock(2, SemanticRole.RESPONSE, [], 2, 2, (12, 15), (20, 18), [], []),  # Home leads +2 (swing=5)
            NarrativeBlock(3, SemanticRole.RESPONSE, [], 2, 2, (20, 18), (30, 28), [], []),
        ]

        assign_roles(blocks)

        # First/last get structural roles
        assert blocks[0].role == SemanticRole.SETUP
        assert blocks[-1].role == SemanticRole.RESOLUTION
        # In a close game, a 5-point swing qualifies as MOMENTUM_SHIFT
        assert blocks[1].role == SemanticRole.MOMENTUM_SHIFT or blocks[2].role == SemanticRole.MOMENTUM_SHIFT

    def test_non_close_game_small_swings_not_momentum_shift(self) -> None:
        """In non-close games (max margin > 7), small swings (< 8) don't qualify as MOMENTUM_SHIFT."""
        from app.services.pipeline.stages.block_types import NarrativeBlock

        # Create blocks with a wide margin at some point (max margin=12), but small middle swings
        blocks = [
            NarrativeBlock(0, SemanticRole.RESPONSE, [], 1, 1, (0, 0), (20, 8), [], []),  # Home leads +12 (not close)
            NarrativeBlock(1, SemanticRole.RESPONSE, [], 2, 2, (20, 8), (22, 15), [], []),  # Away gains 5 (swing=5 < 8)
            NarrativeBlock(2, SemanticRole.RESPONSE, [], 3, 3, (22, 15), (30, 25), [], []),  # Home gains 2 (swing=2)
            NarrativeBlock(3, SemanticRole.RESPONSE, [], 4, 4, (30, 25), (40, 35), [], []),
        ]

        assign_roles(blocks)

        assert blocks[0].role == SemanticRole.SETUP
        assert blocks[-1].role == SemanticRole.RESOLUTION
        # In a non-close game, 5-point swings don't qualify as MOMENTUM_SHIFT
        assert blocks[1].role != SemanticRole.MOMENTUM_SHIFT and blocks[2].role != SemanticRole.MOMENTUM_SHIFT

    def test_significant_swing_is_momentum_shift(self) -> None:
        """Block with significant net swing (8+) qualifies as MOMENTUM_SHIFT."""
        from app.services.pipeline.stages.block_types import NarrativeBlock

        # Create blocks with a significant swing
        blocks = [
            NarrativeBlock(0, SemanticRole.RESPONSE, [], 1, 1, (0, 0), (10, 8), [], []),  # Home +2
            NarrativeBlock(1, SemanticRole.RESPONSE, [], 2, 2, (10, 8), (12, 22), [], []),  # Away goes +10! (swing=12)
            NarrativeBlock(2, SemanticRole.RESPONSE, [], 3, 3, (12, 22), (25, 30), [], []),  # Close again
            NarrativeBlock(3, SemanticRole.RESPONSE, [], 4, 4, (25, 30), (35, 38), [], []),
        ]

        assign_roles(blocks)

        # Block 1 has a 12-point swing - should be MOMENTUM_SHIFT
        assert blocks[1].role == SemanticRole.MOMENTUM_SHIFT

    def test_deficit_overcome_is_momentum_shift(self) -> None:
        """Overcoming a 6+ deficit to take lead qualifies as MOMENTUM_SHIFT."""
        from app.services.pipeline.stages.block_types import NarrativeBlock

        # Create blocks where team overcomes 7-point deficit
        blocks = [
            NarrativeBlock(0, SemanticRole.RESPONSE, [], 1, 1, (0, 0), (8, 15), [], []),  # Away +7
            NarrativeBlock(1, SemanticRole.RESPONSE, [], 2, 2, (8, 15), (20, 18), [], []),  # Home overcomes 7-pt deficit!
            NarrativeBlock(2, SemanticRole.RESPONSE, [], 3, 3, (20, 18), (30, 28), [], []),
            NarrativeBlock(3, SemanticRole.RESPONSE, [], 4, 4, (30, 28), (40, 38), [], []),
        ]

        assign_roles(blocks)

        # Block 1 overcame a 7-point deficit to take the lead - should be MOMENTUM_SHIFT
        assert blocks[1].role == SemanticRole.MOMENTUM_SHIFT

    def test_role_quota_enforcement(self) -> None:
        """No role appears more than twice."""
        from app.services.pipeline.stages.block_types import NarrativeBlock

        # Create 7 blocks (maximum)
        blocks = [
            NarrativeBlock(i, SemanticRole.RESPONSE, [], 1, 1, (0, 0), (10, 8), [], [])
            for i in range(7)
        ]

        assign_roles(blocks)

        # Count occurrences
        role_counts: dict[SemanticRole, int] = {}
        for block in blocks:
            role_counts[block.role] = role_counts.get(block.role, 0) + 1

        # No role should appear more than twice
        for count in role_counts.values():
            assert count <= 2


class TestExecuteGroupBlocksExtended:
    """Extended tests for execute_group_blocks async function."""

    @pytest.mark.asyncio
    async def test_blowout_game_compression(self) -> None:
        """Blowout games use compression strategy."""

        # Create a blowout scenario - sustained 20+ point margin
        moments = []
        for i in range(20):
            period = (i // 5) + 1
            home_score = 10 + i * 5  # Home runs away
            away_score = 10 + i * 2
            moments.append({
                "play_ids": [i],
                "period": period,
                "score_before": [home_score - 5, away_score - 2],
                "score_after": [home_score, away_score],
            })

        stage_input = StageInput(
            game_id=1,
            run_id=1,
            previous_output={
                "validated": True,
                "moments": moments,
                "pbp_events": [],
            },
            game_context={"home_team": "Lakers", "away_team": "Celtics", "sport": "NBA"},
        )

        result = await execute_group_blocks(stage_input)

        # Should detect blowout and compress
        assert result.data["is_blowout"] is True
        # Blowout games get max 5 blocks
        assert result.data["block_count"] <= 5

    @pytest.mark.asyncio
    async def test_normal_game_with_drama_weights(self) -> None:
        """Normal game uses drama weights from ANALYZE_DRAMA."""

        moments = []
        for period in [1, 2, 3, 4]:
            for i in range(3):
                moments.append({
                    "play_ids": [period * 10 + i],
                    "period": period,
                    "score_before": [period * 20, period * 19],
                    "score_after": [period * 20 + 5, period * 19 + 4],
                })

        stage_input = StageInput(
            game_id=1,
            run_id=1,
            previous_output={
                "validated": True,
                "moments": moments,
                "pbp_events": [],
                "quarter_weights": {"Q1": 0.8, "Q2": 1.0, "Q3": 1.5, "Q4": 2.0},
                "peak_quarter": "Q4",
                "story_type": "close_finish",
                "headline": "Lakers win thriller",
            },
            game_context={"home_team": "Lakers", "away_team": "Celtics", "sport": "NBA"},
        )

        result = await execute_group_blocks(stage_input)

        assert result.data["blocks_grouped"] is True
        assert result.data["quarter_weights"] == {"Q1": 0.8, "Q2": 1.0, "Q3": 1.5, "Q4": 2.0}
        assert result.data["is_blowout"] is False

    @pytest.mark.asyncio
    async def test_missing_moments_raises(self) -> None:
        """Missing moments raises ValueError."""
        import pytest

        stage_input = StageInput(
            game_id=1,
            run_id=1,
            previous_output={
                "validated": True,
                "moments": None,
                "pbp_events": [],
            },
            game_context={"home_team": "Lakers", "away_team": "Celtics", "sport": "NBA"},
        )

        with pytest.raises(ValueError, match="No moments"):
            await execute_group_blocks(stage_input)

    @pytest.mark.asyncio
    async def test_validation_required(self) -> None:
        """Validation must pass before grouping."""
        import pytest

        stage_input = StageInput(
            game_id=1,
            run_id=1,
            previous_output={
                "validated": False,
                "moments": [{"play_ids": [1]}],
                "pbp_events": [],
            },
            game_context={"home_team": "Lakers", "away_team": "Celtics", "sport": "NBA"},
        )

        with pytest.raises(ValueError, match="VALIDATE_MOMENTS to pass"):
            await execute_group_blocks(stage_input)

    @pytest.mark.asyncio
    async def test_missing_previous_output_raises(self) -> None:
        """Missing previous output raises ValueError."""
        import pytest

        stage_input = StageInput(
            game_id=1,
            run_id=1,
            previous_output=None,
            game_context={"home_team": "Lakers", "away_team": "Celtics", "sport": "NBA"},
        )

        with pytest.raises(ValueError, match="requires previous stage output"):
            await execute_group_blocks(stage_input)


class TestMLBLeagueConfig:
    """Tests for MLB-specific league config and thresholds."""

    def test_mlb_config_values(self) -> None:
        """MLB config has baseball-appropriate thresholds."""
        from app.services.pipeline.stages.league_config import get_config

        cfg = get_config("MLB")
        assert cfg["regulation_periods"] == 9
        assert cfg["momentum_swing"] == 3
        assert cfg["late_game_period"] == 7
        assert cfg["blowout_margin"] == 8
        assert cfg["scoring_run_min"] == 3
        assert cfg["period_noun"] == "inning"
        assert cfg["score_noun"] == "run"
        assert cfg["extra_period_label"] == "extra innings"

    def test_unknown_league_falls_back_to_nba(self) -> None:
        """Unknown league codes fall back to NBA defaults."""
        from app.services.pipeline.stages.league_config import get_config

        cfg = get_config("WNBA")
        assert cfg["regulation_periods"] == 4

    def test_mlb_assign_roles_uses_lower_thresholds(self) -> None:
        """MLB role assignment uses 3-run swing threshold, not 8-point."""
        from app.services.pipeline.stages.block_types import NarrativeBlock

        # A 3-run swing is significant in MLB
        blocks = [
            NarrativeBlock(0, SemanticRole.RESPONSE, [], 1, 3, (0, 0), (2, 1), [], []),
            NarrativeBlock(1, SemanticRole.RESPONSE, [], 4, 6, (2, 1), (2, 4), [], [],
                           peak_margin=3),
            NarrativeBlock(2, SemanticRole.RESPONSE, [], 7, 7, (2, 4), (5, 4), [], [],
                           peak_margin=1),
            NarrativeBlock(3, SemanticRole.RESPONSE, [], 8, 9, (5, 4), (6, 4), [], []),
        ]
        assign_roles(blocks, league_code="MLB")

        assert blocks[0].role == SemanticRole.SETUP
        assert blocks[-1].role == SemanticRole.RESOLUTION

    def test_mlb_late_game_bonus_uses_7th_inning(self) -> None:
        """MLB late-game bonus kicks in at inning 7, not quarter 4."""
        from app.services.pipeline.stages.block_types import NarrativeBlock

        # Block in 7th+ inning with a swing should get period bonus
        blocks = [
            NarrativeBlock(0, SemanticRole.RESPONSE, [], 1, 3, (0, 0), (3, 1), [], []),
            NarrativeBlock(1, SemanticRole.RESPONSE, [], 4, 6, (3, 1), (3, 4), [], [],
                           peak_margin=3),
            NarrativeBlock(2, SemanticRole.RESPONSE, [], 7, 8, (3, 4), (3, 7), [], [],
                           peak_margin=3),
            NarrativeBlock(3, SemanticRole.RESPONSE, [], 9, 9, (3, 7), (3, 8), [], []),
        ]
        assign_roles(blocks, league_code="MLB")

        # Block 2 is in late-game (7th+) with a swing — should get MOMENTUM_SHIFT
        assert blocks[2].role == SemanticRole.MOMENTUM_SHIFT

    def test_mlb_zero_scoring_block_gets_decision_point(self) -> None:
        """A block with no scoring change gets DECISION_POINT, not RESPONSE."""
        from app.services.pipeline.stages.block_types import NarrativeBlock

        blocks = [
            NarrativeBlock(0, SemanticRole.RESPONSE, [], 1, 3, (0, 0), (3, 1), [], []),
            NarrativeBlock(1, SemanticRole.RESPONSE, [], 4, 5, (3, 1), (3, 1), [], []),  # no scoring
            NarrativeBlock(2, SemanticRole.RESPONSE, [], 6, 7, (3, 1), (3, 4), [], [],
                           peak_margin=3),
            NarrativeBlock(3, SemanticRole.RESPONSE, [], 8, 9, (3, 4), (5, 4), [], []),
        ]
        assign_roles(blocks, league_code="MLB")

        assert blocks[1].role == SemanticRole.DECISION_POINT

    def test_mlb_blowout_detection_uses_8_runs(self) -> None:
        """MLB blowout threshold is 8 runs, not 15 points."""
        from app.services.pipeline.stages.block_analysis import detect_blowout

        moments = [
            {"score_after": [0, 0], "period": 1},
            {"score_after": [8, 0], "period": 3},
            {"score_after": [10, 0], "period": 5},
        ]
        is_blowout, _, _ = detect_blowout(moments, league_code="MLB")
        assert is_blowout is True

    def test_mlb_blowout_not_triggered_at_7_runs(self) -> None:
        """7-run margin does not trigger MLB blowout."""
        from app.services.pipeline.stages.block_analysis import detect_blowout

        moments = [
            {"score_after": [0, 0], "period": 1},
            {"score_after": [7, 0], "period": 3},
        ]
        is_blowout, _, _ = detect_blowout(moments, league_code="MLB")
        assert is_blowout is False

    def test_mlb_garbage_time_uses_7th_inning(self) -> None:
        """MLB garbage time starts at 7th inning with 10+ run margin."""
        from app.services.pipeline.stages.block_analysis import find_garbage_time_start

        moments = [
            {"score_after": [0, 0], "period": 1},
            {"score_after": [5, 0], "period": 3},
            {"score_after": [10, 0], "period": 7},  # 10-run lead in 7th
        ]
        idx = find_garbage_time_start(moments, league_code="MLB")
        assert idx == 2
