"""Tests for the score_timeline helper.

Covers blowout, back-and-forth lead changes, tied games, and no-score games,
plus determinism and league_config threshold lookup.
"""

from __future__ import annotations

from typing import Any


def _play(
    play_index: int,
    home_score: int,
    away_score: int,
    *,
    quarter: int = 1,
    team: str | None = None,
) -> dict[str, Any]:
    """Build a minimal normalized PBP event dict."""
    return {
        "play_index": play_index,
        "quarter": quarter,
        "home_score": home_score,
        "away_score": away_score,
        "team_abbreviation": team,
    }


class TestBuildScoreTimelineBasics:
    def test_empty_input_returns_empty_timeline(self):
        from app.services.pipeline.helpers.score_timeline import (
            ScoreTimeline,
            build_score_timeline,
        )

        result = build_score_timeline([])

        assert isinstance(result, ScoreTimeline)
        assert result.per_play == []
        assert result.lead_change_events == []
        assert result.scoring_droughts == []
        assert result.tied_intervals == []
        assert result.peak_lead == 0
        assert result.peak_lead_idx is None
        assert result.first_meaningful_lead_idx is None

    def test_per_play_state_includes_signed_lead(self):
        from app.services.pipeline.helpers.score_timeline import build_score_timeline

        events = [
            _play(0, 0, 0),
            _play(1, 2, 0, team="HOME"),
            _play(2, 2, 3, team="AWAY"),
        ]

        result = build_score_timeline(events)

        assert result.per_play[0].lead == 0
        assert result.per_play[1].lead == 2  # home leading
        assert result.per_play[2].lead == -1  # away leading
        # Tuple shape sanity
        assert result.per_play[1].home_score == 2
        assert result.per_play[1].away_score == 0


class TestBlowout:
    """Wire-to-wire blowout: home team builds and holds a large lead."""

    def _events(self) -> list[dict[str, Any]]:
        # Home team scores steadily; away team never scores meaningfully.
        return [
            _play(0, 0, 0),
            _play(1, 6, 0, team="HOME"),
            _play(2, 12, 0, team="HOME"),
            _play(3, 12, 2, team="AWAY"),
            _play(4, 18, 2, team="HOME", quarter=2),
            _play(5, 25, 2, team="HOME", quarter=2),
            _play(6, 30, 4, team="HOME", quarter=3),
            _play(7, 30, 4, quarter=4),
            _play(8, 35, 4, team="HOME", quarter=4),
        ]

    def test_peak_lead_is_largest_margin(self):
        from app.services.pipeline.helpers.score_timeline import build_score_timeline

        result = build_score_timeline(self._events())

        # Final lead 35-4 = 31; that's the peak.
        assert result.peak_lead == 31
        assert result.peak_lead_idx == 8

    def test_no_lead_changes_in_wire_to_wire(self):
        from app.services.pipeline.helpers.score_timeline import build_score_timeline

        result = build_score_timeline(self._events())

        # Home leads from play 1 onward; opening tie -> home lead is not a lead
        # change (matches score_detection.is_lead_change semantics).
        assert result.lead_change_events == []

    def test_first_meaningful_lead_uses_nba_threshold(self):
        from app.services.pipeline.helpers.score_timeline import build_score_timeline

        result = build_score_timeline(self._events(), league_code="NBA")

        # NBA meaningful_lead = 10; first crossed at play 2 (12-0).
        assert result.first_meaningful_lead_idx == 2

    def test_tied_interval_only_at_open(self):
        from app.services.pipeline.helpers.score_timeline import build_score_timeline

        result = build_score_timeline(self._events())

        assert len(result.tied_intervals) == 1
        assert result.tied_intervals[0].start_idx == 0
        assert result.tied_intervals[0].end_idx == 0


class TestBackAndForth:
    """Multiple lead changes; peak lead modest."""

    def _events(self) -> list[dict[str, Any]]:
        return [
            _play(0, 0, 0),
            _play(1, 2, 0, team="HOME"),  # HOME leads
            _play(2, 2, 3, team="AWAY"),  # lead change -> AWAY
            _play(3, 5, 3, team="HOME"),  # lead change -> HOME
            _play(4, 5, 5, team="AWAY"),  # tie (no lead change)
            _play(5, 5, 8, team="AWAY"),  # AWAY leads (no lead change, was tied)
            _play(6, 10, 8, team="HOME"),  # lead change -> HOME
        ]

    def test_lead_changes_are_recorded_with_metadata(self):
        from app.services.pipeline.helpers.score_timeline import build_score_timeline

        result = build_score_timeline(self._events())

        idxs = [evt.play_index for evt in result.lead_change_events]
        teams = [evt.scoring_team for evt in result.lead_change_events]

        assert idxs == [2, 3, 6]
        assert teams == ["AWAY", "HOME", "HOME"]
        # Sign of new_lead reflects winner side.
        evt_at_2 = result.lead_change_events[0]
        assert evt_at_2.previous_lead == 2
        assert evt_at_2.new_lead == -1

    def test_tied_intervals_capture_open_and_mid_game_ties(self):
        from app.services.pipeline.helpers.score_timeline import build_score_timeline

        result = build_score_timeline(self._events())

        ranges = [(t.start_idx, t.end_idx) for t in result.tied_intervals]
        # Tied at play 0 (0-0) and play 4 (5-5).
        assert (0, 0) in ranges
        assert (4, 4) in ranges

    def test_peak_lead_reflects_back_and_forth(self):
        from app.services.pipeline.helpers.score_timeline import build_score_timeline

        result = build_score_timeline(self._events())

        # Final play 6: 10-8 -> margin 2; peak across game = 3 (away up 5-8).
        assert result.peak_lead == 3
        assert result.peak_lead_idx == 5


class TestComebackPeakLead:
    """Team that wins was once down — peak_lead reflects opponent's max."""

    def test_peak_lead_idx_marks_opposing_max(self):
        from app.services.pipeline.helpers.score_timeline import build_score_timeline

        events = [
            _play(0, 0, 0),
            _play(1, 0, 12, team="AWAY"),
            _play(2, 0, 18, team="AWAY"),  # away peak: -18
            _play(3, 6, 18, team="HOME"),
            _play(4, 14, 18, team="HOME"),
            _play(5, 20, 18, team="HOME"),  # home wins by 2
        ]

        result = build_score_timeline(events)

        assert result.peak_lead == 18
        assert result.peak_lead_idx == 2


class TestTiedGame:
    """Game ends tied (e.g., regulation tie before OT)."""

    def test_tied_intervals_span_runs_of_zero_lead(self):
        from app.services.pipeline.helpers.score_timeline import build_score_timeline

        events = [
            _play(0, 0, 0),
            _play(1, 0, 2, team="AWAY"),
            _play(2, 2, 2, team="HOME"),  # tie
            _play(3, 2, 2),  # still tied
            _play(4, 4, 2, team="HOME"),
            _play(5, 4, 4, team="AWAY"),  # tied again
        ]

        result = build_score_timeline(events)

        ranges = [(t.start_idx, t.end_idx) for t in result.tied_intervals]
        assert (0, 0) in ranges
        assert (2, 3) in ranges
        # Final tie at play 5 stays open until end-of-game.
        assert (5, 5) in ranges

    def test_no_lead_changes_when_only_tied_or_one_team_leads(self):
        from app.services.pipeline.helpers.score_timeline import build_score_timeline

        events = [
            _play(0, 0, 0),
            _play(1, 0, 2, team="AWAY"),
            _play(2, 2, 2, team="HOME"),
            _play(3, 4, 2, team="HOME"),
        ]

        # AWAY -> tied -> HOME: tied state breaks the chain, so no lead change.
        result = build_score_timeline(events)
        assert result.lead_change_events == []


class TestNoScoreGame:
    """No team ever scores — entire game is one drought, all tied."""

    def test_entire_game_is_one_drought_and_one_tied_interval(self):
        from app.services.pipeline.helpers.score_timeline import build_score_timeline

        events = [_play(i, 0, 0, quarter=1) for i in range(5)]

        result = build_score_timeline(events)

        assert result.peak_lead == 0
        assert result.peak_lead_idx is None
        assert result.first_meaningful_lead_idx is None
        assert result.lead_change_events == []
        assert result.tied_intervals == [(0, 4)]
        assert len(result.scoring_droughts) == 1
        assert result.scoring_droughts[0].start_idx == 0
        assert result.scoring_droughts[0].end_idx == 4
        assert result.scoring_droughts[0].period == 1


class TestScoringDroughts:
    def test_drought_between_scoring_plays(self):
        from app.services.pipeline.helpers.score_timeline import build_score_timeline

        events = [
            _play(0, 2, 0, team="HOME"),  # scoring (first play, non-zero)
            _play(1, 2, 0, quarter=1),
            _play(2, 2, 0, quarter=1),
            _play(3, 2, 3, team="AWAY", quarter=2),  # scoring
            _play(4, 2, 3, quarter=2),
            _play(5, 5, 3, team="HOME", quarter=2),  # scoring
        ]

        result = build_score_timeline(events)

        ranges = [(d.start_idx, d.end_idx, d.period) for d in result.scoring_droughts]
        assert (1, 2, 1) in ranges
        assert (4, 4, 2) in ranges

    def test_trailing_drought_after_last_score(self):
        from app.services.pipeline.helpers.score_timeline import build_score_timeline

        events = [
            _play(0, 2, 0, team="HOME"),
            _play(1, 2, 0),
            _play(2, 2, 0, quarter=2),
        ]

        result = build_score_timeline(events)
        # Trailing non-scoring plays form a drought ending at the final play.
        assert any(
            d.start_idx == 1 and d.end_idx == 2 for d in result.scoring_droughts
        )


class TestLeagueThresholds:
    def test_mlb_threshold_overrides_nba(self):
        from app.services.pipeline.helpers.score_timeline import build_score_timeline

        events = [
            _play(0, 0, 0),
            _play(1, 2, 0, team="HOME"),  # MLB meaningful_lead = 3
            _play(2, 3, 0, team="HOME"),  # crosses MLB threshold
            _play(3, 4, 0, team="HOME"),
        ]

        nba_result = build_score_timeline(events, league_code="NBA")
        mlb_result = build_score_timeline(events, league_code="MLB")

        # NBA threshold = 10, never reached -> None
        assert nba_result.first_meaningful_lead_idx is None
        # MLB threshold = 3, reached at play 2
        assert mlb_result.first_meaningful_lead_idx == 2

    def test_nhl_threshold_two_goals(self):
        from app.services.pipeline.helpers.score_timeline import build_score_timeline

        events = [
            _play(0, 0, 0),
            _play(1, 1, 0, team="HOME"),
            _play(2, 2, 0, team="HOME"),  # NHL meaningful_lead = 2
        ]

        result = build_score_timeline(events, league_code="NHL")
        assert result.first_meaningful_lead_idx == 2

    def test_unknown_league_falls_back_to_nba(self):
        from app.services.pipeline.helpers.score_timeline import build_score_timeline

        events = [
            _play(0, 0, 0),
            _play(1, 10, 0, team="HOME"),
        ]

        result = build_score_timeline(events, league_code="WNBA")
        # NBA threshold (10) reached at play 1.
        assert result.first_meaningful_lead_idx == 1


class TestCrossValidationWithIsLeadChange:
    """Lead-change events from build_score_timeline must agree with the
    primitive ``is_lead_change_play`` helper used by boundary detection."""

    def test_lead_change_events_match_pairwise_check(self):
        from app.services.pipeline.helpers.score_timeline import build_score_timeline
        from app.services.pipeline.stages.score_detection import is_lead_change_play

        events = [
            _play(0, 0, 0),
            _play(1, 2, 0, team="HOME"),
            _play(2, 2, 5, team="AWAY"),  # lead change
            _play(3, 2, 5),
            _play(4, 7, 5, team="HOME"),  # lead change
            _play(5, 7, 7, team="AWAY"),
            _play(6, 9, 7, team="HOME"),
        ]

        result = build_score_timeline(events)
        timeline_idxs = {evt.play_index for evt in result.lead_change_events}

        primitive_idxs: set[int] = set()
        for i in range(1, len(events)):
            if is_lead_change_play(events[i], events[i - 1]):
                primitive_idxs.add(events[i]["play_index"])

        assert timeline_idxs == primitive_idxs


class TestDeterminism:
    def test_same_input_yields_identical_output(self):
        from app.services.pipeline.helpers.score_timeline import build_score_timeline

        events = [
            _play(0, 0, 0),
            _play(1, 2, 0, team="HOME"),
            _play(2, 2, 3, team="AWAY"),
            _play(3, 5, 3, team="HOME"),
            _play(4, 5, 5, team="AWAY"),
            _play(5, 10, 5, team="HOME"),
        ]

        first = build_score_timeline(events, league_code="NBA")
        second = build_score_timeline(events, league_code="NBA")

        assert first == second
