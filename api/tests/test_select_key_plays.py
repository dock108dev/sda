"""Tests for the full-game key-play selector (v3-summary pipeline)."""

from __future__ import annotations

from typing import Any


def _play(
    play_index: int,
    home_score: int,
    away_score: int,
    *,
    quarter: int = 1,
    play_type: str | None = "score",
) -> dict[str, Any]:
    return {
        "play_index": play_index,
        "quarter": quarter,
        "home_score": home_score,
        "away_score": away_score,
        "play_type": play_type,
    }


class TestSelectKeyPlaysFullGame:
    def test_empty_input_returns_empty(self):
        from app.services.pipeline.stages.select_key_plays import (
            select_key_plays_full_game,
        )

        assert select_key_plays_full_game([], league_code="NBA") == []

    def test_includes_final_play_always(self):
        from app.services.pipeline.stages.select_key_plays import (
            select_key_plays_full_game,
        )

        events = [
            _play(0, 0, 0, play_type=None),
            _play(1, 2, 0),
            _play(2, 4, 0),
            _play(3, 6, 0),
            _play(4, 8, 0, quarter=4),
        ]
        selected = select_key_plays_full_game(events, league_code="NBA")
        assert 4 in selected

    def test_lead_changes_outscore_scoring_plays(self):
        from app.services.pipeline.stages.select_key_plays import (
            select_key_plays_full_game,
        )

        # Two lead changes (play 2: home pulls ahead, play 4: away pulls ahead)
        # plus several non-lead-change scoring plays. Lead-change plays must
        # appear in the selection.
        events = [
            _play(0, 0, 0, play_type=None),
            _play(1, 2, 3),  # away leads
            _play(2, 5, 3),  # home takes the lead — lead change
            _play(3, 5, 5),
            _play(4, 5, 7),  # away retakes — lead change
            _play(5, 7, 7),
            _play(6, 9, 7, quarter=4),
        ]
        selected = select_key_plays_full_game(events, league_code="NBA")
        assert 2 in selected
        assert 4 in selected

    def test_chronological_order(self):
        from app.services.pipeline.stages.select_key_plays import (
            select_key_plays_full_game,
        )

        events = [
            _play(0, 0, 0, play_type=None),
            _play(5, 2, 0),
            _play(10, 4, 0),
            _play(15, 4, 2),
            _play(20, 6, 2, quarter=4),
        ]
        selected = select_key_plays_full_game(events, league_code="NBA")
        assert selected == sorted(selected)

    def test_max_keys_respected(self):
        from app.services.pipeline.stages.select_key_plays import (
            MAX_KEY_PLAYS,
            select_key_plays_full_game,
        )

        events = [_play(i, i, 0) for i in range(50)]
        events[-1]["quarter"] = 4
        selected = select_key_plays_full_game(events, league_code="NBA")
        # MAX_KEY_PLAYS plus the final-play guarantee may add at most one more.
        assert len(selected) <= MAX_KEY_PLAYS + 1

    def test_mlb_uses_run_thresholds(self):
        from app.services.pipeline.stages.select_key_plays import (
            select_key_plays_full_game,
        )

        # MLB scoring_run_min is 3 — a 4-run inning should mark the run-ender.
        events = [
            _play(0, 0, 0, play_type=None),
            _play(1, 1, 0, quarter=1),
            _play(2, 2, 0, quarter=1),
            _play(3, 3, 0, quarter=1),
            _play(4, 4, 0, quarter=1),  # run ends here
            _play(5, 4, 1, quarter=2),
            _play(6, 4, 2, quarter=9),
        ]
        selected = select_key_plays_full_game(events, league_code="MLB")
        # Final play and the run-ender should both be in the selection.
        assert 6 in selected
        assert 4 in selected
