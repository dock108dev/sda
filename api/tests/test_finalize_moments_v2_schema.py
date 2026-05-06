"""Tests for the v2 game-flow schema written by FINALIZE_MOMENTS.

Verifies that the persistence stage:
- backfills per-block v2 fields (reason / label / lead_before / lead_after / evidence)
  with safe defaults while preserving any values upstream stages already set;
- derives signed leads from existing score_before / score_after when missing;
- computes top-level archetype, winner_team_id, source_counts and validation
  blocks from the accumulated pipeline output;
- stamps the schema version literal "game-flow-v2" on the row;
- preserves UPSERT behavior so re-running a game overwrites every v2 field.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_game(home_score=110, away_score=98, home_abbr="LAL", away_abbr="BOS"):
    game = MagicMock()
    game.home_score = home_score
    game.away_score = away_score
    game.league.code = "NBA"
    game.home_team.abbreviation = home_abbr
    game.away_team.abbreviation = away_abbr
    return game


def _make_blocks(flow_home=110, flow_away=98):
    return [
        {
            "block_index": 0,
            "role": "SETUP",
            "narrative": "Tip-off and early offense set the tone.",
            "score_before": [0, 0],
            "score_after": [flow_home // 2, flow_away // 2],
            "moment_indices": [0],
            "play_ids": [1],
            "key_play_ids": [1],
        },
        {
            "block_index": 1,
            "role": "RESOLUTION",
            "narrative": "Closing run sealed the win.",
            "score_before": [flow_home // 2, flow_away // 2],
            "score_after": [flow_home, flow_away],
            "moment_indices": [1],
            "play_ids": [2],
            "key_play_ids": [2],
        },
    ]


def _pbp_events_minimal():
    """Three plays: scoring, scoring (lead flip), no-op."""
    return [
        {"play_index": 1, "home_score": 2, "away_score": 0, "quarter": 1, "team_abbreviation": "LAL"},
        {"play_index": 2, "home_score": 2, "away_score": 3, "quarter": 1, "team_abbreviation": "BOS"},
        {"play_index": 3, "home_score": 2, "away_score": 3, "quarter": 2, "team_abbreviation": None},
    ]


def _stage_input(blocks, *, archetype="comeback", pbp_events=None, validated=True,
                 blocks_validated=True, fallback_used=False, warnings=None):
    from app.services.pipeline.models import StageInput

    return StageInput(
        game_id=42,
        run_id=1,
        previous_output={
            "validated": validated,
            "blocks_validated": blocks_validated,
            "moments": [{"idx": i} for i in range(len(blocks))],
            "blocks": blocks,
            "openai_calls": 1,
            "total_words": 50,
            "archetype": archetype,
            "pbp_events": pbp_events or [],
            "fallback_used": fallback_used,
            "warnings": warnings or [],
        },
        game_context={"sport": "NBA"},
    )


def _session_returning(*objs):
    """Build an AsyncMock session whose ``execute`` returns the given objects
    in order for the pre-write lookups, then a benign MagicMock for any
    additional calls (e.g. the post-persist ``pg_notify``).

    Using an iterator-style ``side_effect`` would raise ``StopAsyncIteration``
    on the trailing pg_notify call; the production code's narrowed catch
    lets that propagate as it should, so the test must supply a real value.
    """
    session = AsyncMock()
    results = []
    for obj in objs:
        r = MagicMock()
        r.scalar_one_or_none.return_value = obj
        results.append(r)

    iterator = iter(results)

    async def _execute(*_args, **_kwargs):
        try:
            return next(iterator)
        except StopIteration:
            # Trailing calls (pg_notify, etc.) that don't need a typed result.
            return MagicMock()

    session.execute = AsyncMock(side_effect=_execute)
    return session


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
# Pure helper unit tests
# ---------------------------------------------------------------------------


class TestResolveWinnerTeamId:
    def test_home_wins(self):
        from app.services.pipeline.stages.finalize_moments import _resolve_winner_team_id

        game = _make_game(home_score=110, away_score=98, home_abbr="LAL", away_abbr="BOS")
        assert _resolve_winner_team_id(game, 110, 98) == "LAL"

    def test_away_wins(self):
        from app.services.pipeline.stages.finalize_moments import _resolve_winner_team_id

        game = _make_game(home_score=98, away_score=110, home_abbr="LAL", away_abbr="BOS")
        assert _resolve_winner_team_id(game, 98, 110) == "BOS"

    def test_tie_returns_none(self):
        from app.services.pipeline.stages.finalize_moments import _resolve_winner_team_id

        game = _make_game(home_score=100, away_score=100)
        assert _resolve_winner_team_id(game, 100, 100) is None

    def test_falls_back_to_db_score_when_flow_missing(self):
        from app.services.pipeline.stages.finalize_moments import _resolve_winner_team_id

        game = _make_game(home_score=110, away_score=98, home_abbr="LAL", away_abbr="BOS")
        assert _resolve_winner_team_id(game, None, None) == "LAL"


class TestComputeSourceCounts:
    def test_aggregates_counts(self):
        from app.services.pipeline.stages.finalize_moments import _compute_source_counts

        counts = _compute_source_counts(_pbp_events_minimal(), "NBA")
        assert counts["plays"] == 3
        # Two scoring transitions: 0->2 and 2->3 (away)
        assert counts["scoring_events"] == 2
        # One lead change (LAL leading 2-0 → BOS leading 2-3)
        assert counts["lead_changes"] == 1
        # No tied per-play state in this fixture
        assert counts["ties"] == 0

    def test_empty_events(self):
        from app.services.pipeline.stages.finalize_moments import _compute_source_counts

        counts = _compute_source_counts([], "NBA")
        assert counts == {"plays": 0, "scoring_events": 0, "lead_changes": 0, "ties": 0}


class TestBuildValidationBlock:
    def test_passed(self):
        from app.services.pipeline.stages.finalize_moments import _build_validation_block

        result = _build_validation_block(
            {"validated": True, "blocks_validated": True, "warnings": []}, False
        )
        assert result == {"status": "passed", "warnings": []}

    def test_fallback_overrides_passed(self):
        from app.services.pipeline.stages.finalize_moments import _build_validation_block

        result = _build_validation_block(
            {"validated": True, "blocks_validated": True, "warnings": ["w1"]},
            fallback_used=True,
        )
        assert result["status"] == "fallback"
        assert result["warnings"] == ["w1"]

    def test_failed_when_validation_missing(self):
        from app.services.pipeline.stages.finalize_moments import _build_validation_block

        result = _build_validation_block(
            {"validated": True, "blocks_validated": False, "warnings": ["w"]}, False
        )
        assert result["status"] == "failed"
        assert result["warnings"] == ["w"]


# ---------------------------------------------------------------------------
# End-to-end FINALIZE_MOMENTS integration with v2 schema
# ---------------------------------------------------------------------------


class TestFinalizeMomentsWritesV2Fields:
    def test_writes_v2_fields_on_new_flow(self):
        """New flow record persists archetype, winner_team_id, source_counts, validation, version."""
        blocks = _make_blocks(110, 98)
        game = _make_game(110, 98)
        # First execute = game lookup; second = existing flow lookup (None → new record).
        session = _session_returning(game, None)

        captured: dict = {}

        def _capture_add(obj):
            captured["flow"] = obj

        session.add = MagicMock(side_effect=_capture_add)

        with patch(
            "app.services.pipeline.stages.finalize_moments.validate_embedded_tweet_ids",
            new=AsyncMock(return_value=blocks),
        ):
            result = _run(
                session,
                _stage_input(blocks, archetype="comeback", pbp_events=_pbp_events_minimal()),
            )

        assert result.data["finalized"] is True
        flow = captured["flow"]
        assert flow.version == "game-flow-v2"
        assert flow.archetype == "comeback"
        assert flow.winner_team_id == "LAL"
        assert flow.source_counts["plays"] == 3
        assert flow.source_counts["lead_changes"] == 1
        assert flow.validation == {"status": "passed", "warnings": []}
        assert result.data["version"] == "game-flow-v2"
        assert result.data["archetype"] == "comeback"
        assert result.data["winner_team_id"] == "LAL"

    def test_upsert_overwrites_v2_fields(self):
        """Existing flow rows have all v2 columns rewritten — no stale values."""
        blocks = _make_blocks(110, 98)
        game = _make_game(110, 98)

        existing = MagicMock()
        existing.id = 99
        existing.version = "stale"
        existing.archetype = "stale"
        existing.winner_team_id = "STL"
        existing.source_counts = {"plays": 0, "scoring_events": 0, "lead_changes": 0, "ties": 0}
        existing.validation = {"status": "failed", "warnings": ["old"]}

        session = _session_returning(game, existing)

        with patch(
            "app.services.pipeline.stages.finalize_moments.validate_embedded_tweet_ids",
            new=AsyncMock(return_value=blocks),
        ):
            result = _run(
                session,
                _stage_input(
                    blocks,
                    archetype="back_and_forth",
                    pbp_events=_pbp_events_minimal(),
                ),
            )

        assert result.data["finalized"] is True
        assert existing.version == "game-flow-v2"
        assert existing.archetype == "back_and_forth"
        assert existing.winner_team_id == "LAL"
        assert existing.source_counts["plays"] == 3
        assert existing.validation["status"] == "passed"
        assert existing.validation["warnings"] == []

    def test_fallback_marks_validation_status(self):
        """fallback_used=True from VALIDATE_BLOCKS yields validation.status == 'fallback'."""
        blocks = _make_blocks(110, 98)
        game = _make_game(110, 98)
        session = _session_returning(game, None)

        captured: dict = {}
        session.add = MagicMock(side_effect=lambda o: captured.setdefault("flow", o))

        with patch(
            "app.services.pipeline.stages.finalize_moments.validate_embedded_tweet_ids",
            new=AsyncMock(return_value=blocks),
        ):
            _run(
                session,
                _stage_input(blocks, fallback_used=True, warnings=["coverage_warn"]),
            )

        assert captured["flow"].validation == {
            "status": "fallback",
            "warnings": ["coverage_warn"],
        }
        # flow_source set by the existing fallback codepath should also flip
        assert captured["flow"].flow_source == "TEMPLATE"


# Per-block v2 backfill (`reason`, `label`, `lead_before`, `lead_after`,
# `evidence`) was deleted in the SSOT cleanup. Tests for it are gone with
# it; the v3 contract's story_role / featured_players / score_context
# are exercised by test_segment_classification.py and
# test_featured_players_v3.py.
