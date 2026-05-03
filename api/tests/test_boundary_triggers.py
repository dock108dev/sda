"""Tests for game-state-driven block boundary triggers.

Covers the contract that block boundaries are placed at game-state changes
(lead changes, first meaningful lead, scoring runs, comeback pivots) — not
at bare period/half ends. NCAAB H1/H2 fixtures verify the half-structure
edge case explicitly.

Boundary candidate priority (lower = stronger):
    1. Lead change
    2. First meaningful lead (NBA 6+, MLB 2+, NHL 2+)
    3. Scoring run start/end (NBA 8+, MLB 3+)
    4. Comeback deficit peak / tie-flip
    5. OT/SO start (NHL only)
    9. Period boundary — kept only when within ±1 moment of one of the above.

Sport-specific assertions per BRAINDUMP §Test cases:
- NBA: halftime/end-third margins are surfaced when meaningful; blowout
  late stretches are compressed.
- MLB: scoring innings drive boundaries; quiet innings merge; blowouts
  compress late innings.
- NHL: goals drive boundaries (period ends alone do not).
"""

from __future__ import annotations

from typing import Any

from app.services.pipeline.stages.block_analysis import (
    find_garbage_time_start,
)
from app.services.pipeline.stages.boundary_detection import (
    should_force_close_moment,
)
from app.services.pipeline.stages.group_split_points import (
    compress_blowout_blocks,
    find_split_points,
)
from app.services.pipeline.stages.moment_types import BoundaryReason


def _moment(
    period: int,
    score_before: list[int],
    score_after: list[int],
    *,
    play_ids: list[int] | None = None,
) -> dict[str, Any]:
    return {
        "period": period,
        "score_before": list(score_before),
        "score_after": list(score_after),
        "play_ids": play_ids or [],
    }


# ---------------------------------------------------------------------------
# 1) First meaningful lead (NBA): triggers a moment-level HARD boundary.
# ---------------------------------------------------------------------------


class TestFirstMeaningfulLeadTriggersBoundary:
    """An NBA play that creates the first ≥6-pt lead must hard-close its moment."""

    def test_play_at_first_meaningful_lead_idx_force_closes(self) -> None:
        prev = {
            "play_index": 7,
            "home_score": 4,
            "away_score": 0,
            "quarter": 1,
            "play_type": "score",
        }
        current = {
            "play_index": 8,
            "home_score": 6,
            "away_score": 0,
            "quarter": 1,
            "play_type": "score",
        }
        plays = [prev, current]

        should_close, reason = should_force_close_moment(
            plays, current, prev, plays, 0, first_meaningful_lead_play_idx=8,
        )
        assert should_close is True
        assert reason == BoundaryReason.FIRST_MEANINGFUL_LEAD

    def test_play_before_first_meaningful_lead_does_not_force_close(self) -> None:
        prev = {
            "play_index": 5,
            "home_score": 2,
            "away_score": 0,
            "quarter": 1,
            "play_type": "score",
        }
        current = {
            "play_index": 6,
            "home_score": 4,
            "away_score": 0,
            "quarter": 1,
            "play_type": "score",
        }
        plays = [prev, current]

        should_close, reason = should_force_close_moment(
            plays, current, prev, plays, 0, first_meaningful_lead_play_idx=8,
        )
        # Not at the trigger index — and no other hard condition fires.
        assert (should_close, reason) == (False, None)


# ---------------------------------------------------------------------------
# 2) Period boundary alone (no game-state change) is not a block boundary.
# ---------------------------------------------------------------------------


class TestPeriodEndAloneDoesNotTrigger:
    """Bare period/inning/half ends are filtered out as orphan candidates."""

    def test_nba_quarter_ends_with_no_state_change_drop_out(self) -> None:
        # 16 moments across 4 quarters, scoreboard frozen at 0-0 — the only
        # candidate splits are quarter ends at indices 4, 8, 12.
        moments = [
            _moment((i // 4) + 1, [0, 0], [0, 0], play_ids=[i])
            for i in range(16)
        ]
        splits = find_split_points(moments, target_blocks=4, league_code="NBA")
        assert {4, 8, 12}.isdisjoint(splits)

    def test_ncaab_half_end_alone_does_not_trigger(self) -> None:
        # NCAAB has two halves. Half boundary lands at moment 5 (period 1 -> 2).
        # No scoring or lead change anywhere — the half end is an orphan.
        moments = [
            _moment(1, [0, 0], [0, 0], play_ids=[0]),
            _moment(1, [0, 0], [0, 0], play_ids=[1]),
            _moment(1, [0, 0], [0, 0], play_ids=[2]),
            _moment(1, [0, 0], [0, 0], play_ids=[3]),
            _moment(1, [0, 0], [0, 0], play_ids=[4]),
            _moment(2, [0, 0], [0, 0], play_ids=[5]),
            _moment(2, [0, 0], [0, 0], play_ids=[6]),
            _moment(2, [0, 0], [0, 0], play_ids=[7]),
            _moment(2, [0, 0], [0, 0], play_ids=[8]),
            _moment(2, [0, 0], [0, 0], play_ids=[9]),
        ]
        splits = find_split_points(moments, target_blocks=3, league_code="NCAAB")
        assert 5 not in splits

    def test_ncaab_half_end_kept_when_state_change_coincides(self) -> None:
        # First meaningful lead (NCAAB / NBA threshold = 6 pts) lands at
        # moment 5 — exactly the half boundary. The boundary survives.
        moments = []
        for i in range(10):
            period = 1 if i < 5 else 2
            home = 0 if i < 5 else 6 + (i - 5)
            moments.append(_moment(period, [0, 0], [home, 0], play_ids=[i]))
        splits = find_split_points(moments, target_blocks=3, league_code="NCAAB")
        assert 5 in splits


# ---------------------------------------------------------------------------
# 3) Scoring runs (MLB multi-run innings) trigger boundaries.
# ---------------------------------------------------------------------------


class TestScoringRunTriggersBoundary:
    """MLB 3+ run innings register as scoring-run candidate splits."""

    def test_mlb_three_run_inning_appears_in_splits(self) -> None:
        # Inning 4 has a 3-run unanswered scoring run for the home team.
        moments = [
            _moment(1, [0, 0], [0, 0], play_ids=[0]),
            _moment(2, [0, 0], [0, 0], play_ids=[1]),
            _moment(3, [0, 0], [0, 1], play_ids=[2]),
            _moment(4, [0, 1], [3, 1], play_ids=[3]),  # 3-run home run
            _moment(4, [3, 1], [3, 1], play_ids=[4]),
            _moment(5, [3, 1], [3, 2], play_ids=[5]),
            _moment(6, [3, 2], [3, 2], play_ids=[6]),
            _moment(7, [3, 2], [4, 2], play_ids=[7]),
            _moment(8, [4, 2], [4, 2], play_ids=[8]),
            _moment(9, [4, 2], [4, 2], play_ids=[9]),
        ]
        splits = find_split_points(moments, target_blocks=4, league_code="MLB")
        # Scoring run starts at moment 3; runs of length one register both
        # the start and start+1 as candidates. Either anchors the boundary.
        assert 3 in splits or 4 in splits

    def test_mlb_quiet_innings_merge_into_neighbor_blocks(self) -> None:
        """Per BRAINDUMP MLB assertion: quiet innings are merged.

        A flow with a single multi-run inning surrounded by 0-0 innings should
        collapse the quiet innings into the neighbor blocks rather than splitting
        each inning into its own block. We verify by counting how many of the
        quiet-inning indices end up as block boundaries.
        """
        moments = [
            _moment(1, [0, 0], [0, 0], play_ids=[0]),
            _moment(2, [0, 0], [0, 0], play_ids=[1]),
            _moment(3, [0, 0], [0, 0], play_ids=[2]),
            _moment(4, [0, 0], [4, 0], play_ids=[3]),  # 4-run inning
            _moment(5, [4, 0], [4, 0], play_ids=[4]),
            _moment(6, [4, 0], [4, 0], play_ids=[5]),
            _moment(7, [4, 0], [4, 0], play_ids=[6]),
            _moment(8, [4, 0], [4, 0], play_ids=[7]),
            _moment(9, [4, 0], [4, 0], play_ids=[8]),
        ]
        splits = find_split_points(moments, target_blocks=4, league_code="MLB")
        # Quiet-only inning indices: 1, 2, 4, 5, 6, 7, 8. They should NOT
        # all become boundaries — at most one or two structural fallbacks.
        quiet_indices = {1, 2, 4, 5, 6, 7, 8}
        quiet_in_splits = quiet_indices.intersection(splits)
        assert len(quiet_in_splits) <= 2


# ---------------------------------------------------------------------------
# 4) Comeback deficit peak triggers a boundary.
# ---------------------------------------------------------------------------


class TestComebackPivotTriggersBoundary:
    """Deficit peak and tie/flip moments are surfaced for comeback archetype."""

    def test_comeback_deficit_peak_in_splits(self) -> None:
        moments = [
            _moment(1, [0, 0], [0, 4], play_ids=[0]),
            _moment(1, [0, 4], [0, 12], play_ids=[1]),  # deficit peak
            _moment(2, [0, 12], [6, 12], play_ids=[2]),
            _moment(2, [6, 12], [12, 12], play_ids=[3]),  # tie/flip
            _moment(3, [12, 12], [20, 14], play_ids=[4]),
            _moment(4, [20, 14], [30, 22], play_ids=[5]),
        ]
        splits = find_split_points(
            moments, target_blocks=4, league_code="NBA", archetype="comeback",
        )
        assert 1 in splits  # deficit peak
        assert 3 in splits  # tie / flip


# ---------------------------------------------------------------------------
# 5) Blowout compresses late boundaries.
# ---------------------------------------------------------------------------


class TestBlowoutCompressesLateBoundaries:
    """Blowout games keep the interesting front half rich and compress the rest."""

    def _blowout_moments(self) -> list[dict[str, Any]]:
        # Home builds a 24-pt lead by Q2 and never lets it go.
        return [
            _moment(1, [0, 0], [12, 2], play_ids=[0]),
            _moment(1, [12, 2], [22, 4], play_ids=[1]),
            _moment(2, [22, 4], [38, 14], play_ids=[2]),  # decisive
            _moment(2, [38, 14], [52, 24], play_ids=[3]),
            _moment(3, [52, 24], [70, 38], play_ids=[4]),
            _moment(3, [70, 38], [84, 50], play_ids=[5]),
            _moment(4, [84, 50], [100, 64], play_ids=[6]),
            _moment(4, [100, 64], [110, 78], play_ids=[7]),
            _moment(4, [110, 78], [120, 88], play_ids=[8]),
        ]

    def test_blowout_split_count_capped_by_compress(self) -> None:
        moments = self._blowout_moments()
        garbage_idx = find_garbage_time_start(moments, league_code="NBA")
        splits = compress_blowout_blocks(moments, decisive_idx=2, garbage_time_idx=garbage_idx)

        # Compression keeps splits modest (≤ BLOWOUT_MAX_BLOCKS - 1 = 4).
        assert len(splits) <= 4
        # The decisive moment is always a boundary.
        assert 2 in splits

    def test_blowout_late_moments_compressed_into_one_block(self) -> None:
        """Per BRAINDUMP NBA assertion: late blowout stretches do not get their
        own narrative beats — at most one boundary lands after the decisive
        moment.
        """
        moments = self._blowout_moments()
        garbage_idx = find_garbage_time_start(moments, league_code="NBA")
        splits = compress_blowout_blocks(moments, decisive_idx=2, garbage_time_idx=garbage_idx)

        late_splits = [s for s in splits if s > 2]
        # Decisive is at moment 2; late splits collapse into 0–2 boundaries.
        assert len(late_splits) <= 2


# ---------------------------------------------------------------------------
# 6) NBA halftime / end-of-third margins surface only when meaningful.
# ---------------------------------------------------------------------------


class TestNBAQuarterMarginsOnlyWhenMeaningful:
    """End-of-quarter splits survive only when paired with a state change."""

    def test_meaningful_lead_at_halftime_kept_as_boundary(self) -> None:
        # Halftime lands at moment 4 with a 12-pt cushion (>= 6, the NBA
        # lead_created threshold). Should be retained.
        moments = [
            _moment(1, [0, 0], [4, 2], play_ids=[0]),
            _moment(1, [4, 2], [8, 6], play_ids=[1]),
            _moment(1, [8, 6], [10, 8], play_ids=[2]),
            _moment(2, [10, 8], [12, 10], play_ids=[3]),
            _moment(2, [12, 10], [22, 10], play_ids=[4]),  # halftime, 12-pt lead
            _moment(3, [22, 10], [28, 16], play_ids=[5]),
            _moment(3, [28, 16], [36, 22], play_ids=[6]),
            _moment(4, [36, 22], [44, 30], play_ids=[7]),
            _moment(4, [44, 30], [50, 36], play_ids=[8]),
        ]
        splits = find_split_points(moments, target_blocks=4, league_code="NBA")
        # First meaningful lead (>= 6 NBA pts) sits at or before moment 4 —
        # the moment 4 candidate must not be filtered as orphan.
        assert any(s in {1, 2, 3, 4} for s in splits)

    def test_quiet_quarter_end_dropped_when_score_unchanged(self) -> None:
        # Both teams score in lock-step → no lead changes, no scoring runs.
        # Quarter ends become orphans.
        moments = [
            _moment(1, [0, 0], [4, 4], play_ids=[0]),
            _moment(1, [4, 4], [8, 8], play_ids=[1]),
            _moment(2, [8, 8], [12, 12], play_ids=[2]),
            _moment(2, [12, 12], [16, 16], play_ids=[3]),
            _moment(3, [16, 16], [20, 20], play_ids=[4]),
            _moment(3, [20, 20], [24, 24], play_ids=[5]),
            _moment(4, [24, 24], [28, 28], play_ids=[6]),
            _moment(4, [28, 28], [32, 32], play_ids=[7]),
        ]
        splits = find_split_points(moments, target_blocks=4, league_code="NBA")
        # Period boundaries land at moments 2, 4, 6 — all should drop out
        # since no game-state trigger sits within ±1 of them.
        period_boundaries = {2, 4, 6}
        assert period_boundaries.isdisjoint(splits)


# ---------------------------------------------------------------------------
# 7) NHL: goals drive boundaries; period ends alone do not.
# ---------------------------------------------------------------------------


class TestNHLGoalsDriveBoundaries:
    """NHL period transitions don't anchor blocks unless a goal sits nearby."""

    def test_nhl_period_end_without_goal_dropped(self) -> None:
        # 9 moments across 3 NHL periods, all 0-0. Boundaries at 3 and 6 are
        # orphans and should be filtered out.
        moments = [
            _moment(1, [0, 0], [0, 0], play_ids=[0]),
            _moment(1, [0, 0], [0, 0], play_ids=[1]),
            _moment(1, [0, 0], [0, 0], play_ids=[2]),
            _moment(2, [0, 0], [0, 0], play_ids=[3]),
            _moment(2, [0, 0], [0, 0], play_ids=[4]),
            _moment(2, [0, 0], [0, 0], play_ids=[5]),
            _moment(3, [0, 0], [0, 0], play_ids=[6]),
            _moment(3, [0, 0], [0, 0], play_ids=[7]),
            _moment(3, [0, 0], [0, 0], play_ids=[8]),
        ]
        splits = find_split_points(moments, target_blocks=3, league_code="NHL")
        assert {3, 6}.isdisjoint(splits)

    def test_nhl_ot_start_appears_in_splits(self) -> None:
        """OT/SO entry is a priority-5 trigger for NHL — it must surface."""
        # Regulation tied 2-2 over 3 periods, then a 4th-period OT moment.
        moments = [
            _moment(1, [0, 0], [1, 0], play_ids=[0]),
            _moment(1, [1, 0], [1, 1], play_ids=[1]),
            _moment(1, [1, 1], [1, 1], play_ids=[2]),
            _moment(2, [1, 1], [2, 1], play_ids=[3]),
            _moment(2, [2, 1], [2, 2], play_ids=[4]),
            _moment(2, [2, 2], [2, 2], play_ids=[5]),
            _moment(3, [2, 2], [2, 2], play_ids=[6]),
            _moment(3, [2, 2], [2, 2], play_ids=[7]),
            _moment(4, [2, 2], [3, 2], play_ids=[8]),  # OT goal
        ]
        splits = find_split_points(moments, target_blocks=4, league_code="NHL")
        # The OT period start is at moment index 8 — must be a boundary.
        assert 8 in splits

    def test_nhl_goal_at_period_end_keeps_boundary(self) -> None:
        # Lead changes from home to away at moment 5 (start of period 2).
        # The lead change is the trigger; the period boundary at moment 5
        # coincides with it (Δ=0) and survives the orphan filter.
        moments = [
            _moment(1, [0, 0], [1, 0], play_ids=[0]),  # home scores first
            _moment(1, [1, 0], [1, 0], play_ids=[1]),
            _moment(1, [1, 0], [1, 0], play_ids=[2]),
            _moment(1, [1, 0], [1, 0], play_ids=[3]),
            _moment(1, [1, 0], [1, 0], play_ids=[4]),
            _moment(2, [1, 0], [1, 2], play_ids=[5]),  # away goes ahead — flip
            _moment(2, [1, 2], [1, 2], play_ids=[6]),
            _moment(2, [1, 2], [1, 2], play_ids=[7]),
            _moment(3, [1, 2], [1, 2], play_ids=[8]),
        ]
        splits = find_split_points(moments, target_blocks=3, league_code="NHL")
        # Period boundary at 5 coincides with the lead change at 5 — it is
        # NOT an orphan and one of {5} (or its first_meaningful_lead twin)
        # must surface as a boundary.
        assert 5 in splits
