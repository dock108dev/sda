"""Unit tests for ISSUE-036: score mismatch detection in FINALIZE_MOMENTS stage.

Tests verify that:
- Pre-write check returns REGENERATE when flow score ≠ DB boxscore score
- Pre-write check passes through (no early return) when scores match
- Post-write safety net increments pipeline.score_mismatch counter on race-condition slip
- _extract_flow_score helper handles edge cases
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_game(home_score: int | None, away_score: int | None, sport: str = "NBA"):
    game = MagicMock()
    game.home_score = home_score
    game.away_score = away_score
    game.league.code = sport
    return game


def _make_blocks(flow_home: int, flow_away: int):
    """Three-block flow whose last block reports the given final score."""
    return [
        {
            "block_index": 0,
            "role": "SETUP",
            "narrative": "Game started well.",
            "score_before": [0, 0],
            "score_after": [flow_home // 2, flow_away // 2],
            "moment_indices": [0],
            "play_ids": [1],
            "key_play_ids": [1],
        },
        {
            "block_index": 1,
            "role": "DECISION_POINT",
            "narrative": "Momentum shifted.",
            "score_before": [flow_home // 2, flow_away // 2],
            "score_after": [flow_home * 3 // 4, flow_away * 3 // 4],
            "moment_indices": [1],
            "play_ids": [2],
            "key_play_ids": [2],
        },
        {
            "block_index": 2,
            "role": "RESOLUTION",
            "narrative": "Final buzzer.",
            "score_before": [flow_home * 3 // 4, flow_away * 3 // 4],
            "score_after": [flow_home, flow_away],
            "moment_indices": [2],
            "play_ids": [3],
            "key_play_ids": [3],
        },
    ]


def _make_stage_input(blocks, validated=True, blocks_validated=True):
    from app.services.pipeline.models import StageInput

    return StageInput(
        game_id=42,
        run_id=1,
        previous_output={
            "validated": validated,
            "blocks_validated": blocks_validated,
            "moments": [{"idx": i} for i in range(len(blocks))],
            "blocks": blocks,
            "openai_calls": 2,
            "total_words": 150,
        },
        game_context={"sport": "NBA"},
    )


def _run(session, stage_input):
    from app.services.pipeline.stages.finalize_moments import execute_finalize_moments

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(
            execute_finalize_moments(session, stage_input, run_uuid="test-uuid")
        )
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# _extract_flow_score
# ---------------------------------------------------------------------------

class TestExtractFlowScore:
    def test_returns_last_block_score(self):
        from app.services.pipeline.stages.finalize_moments import _extract_flow_score

        blocks = _make_blocks(110, 98)
        home, away = _extract_flow_score(blocks)
        assert home == 110
        assert away == 98

    def test_empty_blocks_returns_none(self):
        from app.services.pipeline.stages.finalize_moments import _extract_flow_score

        assert _extract_flow_score([]) == (None, None)

    def test_missing_score_after_returns_none(self):
        from app.services.pipeline.stages.finalize_moments import _extract_flow_score

        blocks = [{"block_index": 0, "role": "RESOLUTION", "score_after": []}]
        assert _extract_flow_score(blocks) == (None, None)

    def test_single_element_score_after_returns_none(self):
        from app.services.pipeline.stages.finalize_moments import _extract_flow_score

        blocks = [{"block_index": 0, "score_after": [110]}]
        assert _extract_flow_score(blocks) == (None, None)


# ---------------------------------------------------------------------------
# Pre-write mismatch → REGENERATE (no DB write)
# ---------------------------------------------------------------------------

def _session_returning(*games):
    """Build an AsyncMock session where successive execute calls return the given game objects.

    Uses MagicMock for the result objects so that scalar_one_or_none() is a normal
    synchronous call (children of AsyncMock are themselves AsyncMock, which would
    make scalar_one_or_none() return a coroutine instead of the game).
    """
    session = AsyncMock()
    results = []
    for g in games:
        r = MagicMock()
        r.scalar_one_or_none.return_value = g
        results.append(r)
    session.execute.side_effect = results
    return session


class TestPreWriteScoreMismatch:
    def test_mismatch_returns_regenerate(self):
        """Flow says 90-80 but DB says 110-98 → REGENERATE, no flush."""
        blocks = _make_blocks(90, 80)
        game = _make_mock_game(home_score=110, away_score=98)
        session = _session_returning(game)

        result = _run(session, _make_stage_input(blocks))

        assert result.data["decision"] == "REGENERATE"
        assert result.data["score_mismatch"] is True
        assert result.data["finalized"] is False
        assert result.data["flow_score"] == [90, 80]
        assert result.data["boxscore_score"] == [110, 98]
        # Session flush must not have been called (no write occurred)
        session.flush.assert_not_called()

    def test_mismatch_away_score_only(self):
        """Home score matches but away differs → still REGENERATE."""
        blocks = _make_blocks(110, 90)
        game = _make_mock_game(home_score=110, away_score=98)
        session = _session_returning(game)

        result = _run(session, _make_stage_input(blocks))

        assert result.data["decision"] == "REGENERATE"
        assert result.data["score_mismatch"] is True

    def test_no_mismatch_proceeds_to_write(self):
        """Scores match → no early return; flush is called."""
        blocks = _make_blocks(110, 98)
        game = _make_mock_game(home_score=110, away_score=98)
        # Second execute: no existing flow record
        session = _session_returning(game, None)

        with patch(
            "app.services.pipeline.stages.finalize_moments.validate_embedded_tweet_ids",
            new=AsyncMock(return_value=blocks),
        ):
            result = _run(session, _make_stage_input(blocks))

        assert result.data.get("score_mismatch") is not True
        assert result.data.get("finalized") is True
        session.flush.assert_called()

    def test_none_db_score_skips_prewrite_check(self):
        """When game.home_score is None, pre-write check is skipped → write proceeds."""
        blocks = _make_blocks(110, 98)
        game = _make_mock_game(home_score=None, away_score=None)
        session = _session_returning(game, None)

        with patch(
            "app.services.pipeline.stages.finalize_moments.validate_embedded_tweet_ids",
            new=AsyncMock(return_value=blocks),
        ):
            result = _run(session, _make_stage_input(blocks))

        # Should not be a mismatch-triggered early return
        assert result.data.get("score_mismatch") is not True
        assert result.data.get("finalized") is True


# ---------------------------------------------------------------------------
# Post-write safety-net counter
# ---------------------------------------------------------------------------

class TestPostWriteScoreMismatch:
    """
    Simulates the rare race-condition path: pre-write check was skipped
    (game.home_score was None at pre-write) but immediately after the flush the
    game object reflects updated scores (we update it directly on the mock to
    simulate what a refresh would reveal).

    To trigger the post-write branch we need:
    - Pre-write: flow_home not None AND game.home_score not None AND mismatch
      → but that would return early (REGENERATE).

    The only realistic post-write-only path is when the pre-write check was
    skipped (None db score) and then the game is refreshed.  Since we don't
    actually refresh in the implementation (same object), the post-write counter
    fires when db scores were None at pre-write but are mutated on the object
    before we reach the post-write check.

    We test this by monkeypatching `game.home_score` mid-execution using
    a side_effect on flush.
    """

    def test_post_write_increments_counter_when_slip_detected(self):
        flow_home, flow_away = 110, 98

        game = MagicMock()
        game.league.code = "NBA"
        # Scores None at first → pre-write check is skipped
        game.home_score = None
        game.away_score = None

        blocks = _make_blocks(flow_home, flow_away)
        session = _session_returning(game, None)

        # Simulate scores appearing on the game object after flush (race condition)
        async def _set_scores_then_flush():
            game.home_score = 90   # different from flow's 110
            game.away_score = 80

        session.flush.side_effect = _set_scores_then_flush

        mock_counter = MagicMock()

        with patch(
            "app.services.pipeline.stages.finalize_moments.validate_embedded_tweet_ids",
            new=AsyncMock(return_value=blocks),
        ), patch(
            "app.services.pipeline.stages.finalize_moments.increment_score_mismatch",
            side_effect=lambda sport: mock_counter.add(1, attributes={"sport": sport}),
        ):
            result = _run(session, _make_stage_input(blocks))

        # Flow was written (no pre-write early return since scores were None)
        assert result.data.get("finalized") is True
        # Post-write counter incremented
        mock_counter.add.assert_called_once_with(1, attributes={"sport": "NBA"})
