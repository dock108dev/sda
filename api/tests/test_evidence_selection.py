"""Tests for the evidence_selection helper.

Covers segments with scoring activity, no scoring activity, lead changes,
late blowout (LOW leverage), MLB/NHL special markers (home run, power-play,
empty-net), overtime, scoring run detection, and featured-player selection.
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
    player: str | None = None,
    play_type: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Build a minimal normalized PBP event dict."""
    return {
        "play_index": play_index,
        "quarter": quarter,
        "home_score": home_score,
        "away_score": away_score,
        "team_abbreviation": team,
        "player_name": player,
        "play_type": play_type,
        "description": description,
    }


# ---------------------------------------------------------------------------
# Scoring segment
# ---------------------------------------------------------------------------


class TestScoringSegment:
    def _events(self) -> list[dict[str, Any]]:
        return [
            _play(0, 0, 0),
            _play(1, 2, 0, team="HOME", player="Alice", play_type="2pt"),
            _play(2, 2, 3, team="AWAY", player="Bob", play_type="3pt"),
            _play(3, 5, 3, team="HOME", player="Alice", play_type="3pt"),
            _play(4, 5, 3, team="HOME"),  # non-scoring
        ]

    def test_extracts_scoring_plays_with_score_before_and_after(self):
        from app.services.pipeline.helpers.evidence_selection import select_evidence
        from app.services.pipeline.helpers.score_timeline import build_score_timeline

        events = self._events()
        timeline = build_score_timeline(events)

        evidence = select_evidence((0, 4), timeline, events, league_code="NBA")

        assert len(evidence.scoring_plays) == 3
        first = evidence.scoring_plays[0]
        assert first.play_index == 1
        assert first.player == "Alice"
        assert first.team == "HOME"
        assert first.score_before == (0, 0)
        assert first.score_after == (2, 0)

    def test_featured_players_are_top_scorers_within_segment(self):
        from app.services.pipeline.helpers.evidence_selection import select_evidence
        from app.services.pipeline.helpers.score_timeline import build_score_timeline

        events = self._events()
        timeline = build_score_timeline(events)
        evidence = select_evidence((0, 4), timeline, events, league_code="NBA")

        names = [fp.name for fp in evidence.featured_players]
        # Alice scored 5, Bob scored 3 — Alice is top.
        assert names[0] == "Alice"
        assert evidence.featured_players[0].delta_contribution == 5
        # Top 1-2 contributors only.
        assert len(evidence.featured_players) <= 2


# ---------------------------------------------------------------------------
# No-score segment
# ---------------------------------------------------------------------------


class TestNoScoreSegment:
    def test_returns_empty_evidence_without_error(self):
        from app.services.pipeline.helpers.evidence_selection import (
            SegmentEvidence,
            select_evidence,
        )
        from app.services.pipeline.helpers.score_timeline import build_score_timeline

        # Earlier scoring builds a 5-5 baseline; segment plays 5-7 are non-scoring.
        events = [
            _play(0, 0, 0),
            _play(1, 5, 0, quarter=1, team="HOME", player="A", play_type="3pt"),
            _play(2, 5, 5, quarter=1, team="AWAY", player="B", play_type="3pt"),
            _play(3, 5, 5, quarter=2),
            _play(4, 5, 5, quarter=2, play_type="rebound"),
            _play(5, 5, 5, quarter=2, play_type="timeout"),
            _play(6, 5, 5, quarter=2, play_type="rebound"),
            _play(7, 5, 5, quarter=2),
        ]
        timeline = build_score_timeline(events)

        evidence = select_evidence((3, 7), timeline, events, league_code="NBA")

        assert isinstance(evidence, SegmentEvidence)
        assert evidence.scoring_plays == []
        assert evidence.lead_changes == []
        assert evidence.scoring_runs == []
        assert evidence.featured_players == []
        assert evidence.is_scoring_run is False
        assert evidence.is_power_play_goal is False
        assert evidence.is_empty_net is False
        # Tied, mid-game, no events — should resolve to MEDIUM, not error.
        assert evidence.leverage == "MEDIUM"


# ---------------------------------------------------------------------------
# Lead-change segment
# ---------------------------------------------------------------------------


class TestLeadChangeSegment:
    def test_lead_changes_within_segment_drive_high_leverage(self):
        from app.services.pipeline.helpers.evidence_selection import select_evidence
        from app.services.pipeline.helpers.score_timeline import build_score_timeline

        # Game with mid-segment lead flips.
        events = [
            _play(0, 0, 0),
            _play(1, 3, 0, team="HOME", player="A", play_type="3pt"),
            _play(2, 3, 5, team="AWAY", player="B", play_type="2pt"),  # flip -> AWAY
            _play(3, 6, 5, team="HOME", player="A", play_type="3pt"),  # flip -> HOME
            _play(4, 6, 8, team="AWAY", player="B", play_type="3pt"),  # flip -> AWAY
        ]
        timeline = build_score_timeline(events)

        evidence = select_evidence((1, 4), timeline, events, league_code="NBA")

        # All three flips fall within the segment range.
        assert len(evidence.lead_changes) == 3
        play_indices = [lc.play_index for lc in evidence.lead_changes]
        assert play_indices == [2, 3, 4]
        assert evidence.lead_changes[0].from_lead == 3
        assert evidence.lead_changes[0].to_lead == -2
        assert evidence.leverage == "HIGH"

    def test_lead_changes_outside_segment_excluded(self):
        from app.services.pipeline.helpers.evidence_selection import select_evidence
        from app.services.pipeline.helpers.score_timeline import build_score_timeline

        events = [
            _play(0, 0, 0),
            _play(1, 3, 0, team="HOME", player="A", play_type="3pt"),
            _play(2, 3, 5, team="AWAY", player="B", play_type="2pt"),  # flip outside
            _play(3, 6, 5, team="HOME", player="A", play_type="3pt"),  # flip in seg
            _play(4, 6, 8, team="AWAY", player="B", play_type="3pt"),  # flip outside
        ]
        timeline = build_score_timeline(events)

        evidence = select_evidence((3, 3), timeline, events, league_code="NBA")
        assert len(evidence.lead_changes) == 1
        assert evidence.lead_changes[0].play_index == 3


# ---------------------------------------------------------------------------
# Late-blowout segment (LOW leverage)
# ---------------------------------------------------------------------------


class TestLateBlowoutSegment:
    def test_late_period_with_blowout_margin_is_low_leverage(self):
        from app.services.pipeline.helpers.evidence_selection import select_evidence
        from app.services.pipeline.helpers.score_timeline import build_score_timeline

        # NBA garbage_time_margin=15, garbage_time_period=3.
        events = [
            _play(0, 50, 30, quarter=3, player="A"),
            _play(1, 52, 30, quarter=3, team="HOME", player="A", play_type="2pt"),
            _play(2, 54, 30, quarter=4, team="HOME", player="A", play_type="2pt"),
            _play(3, 56, 32, quarter=4, team="HOME", player="C", play_type="2pt"),
        ]
        timeline = build_score_timeline(events)

        evidence = select_evidence((1, 3), timeline, events, league_code="NBA")
        assert evidence.leverage == "LOW"
        # Even though there are scoring plays, leverage should still be LOW.
        assert len(evidence.scoring_plays) >= 1

    def test_clutch_close_late_segment_is_high_leverage(self):
        from app.services.pipeline.helpers.evidence_selection import select_evidence
        from app.services.pipeline.helpers.score_timeline import build_score_timeline

        # Q4, end-margin within clutch_window_pts (5) -> HIGH.
        events = [
            _play(0, 50, 50, quarter=3),
            _play(1, 52, 50, quarter=4, team="HOME", player="A", play_type="2pt"),
            _play(2, 52, 53, quarter=4, team="AWAY", player="B", play_type="3pt"),
        ]
        timeline = build_score_timeline(events)

        evidence = select_evidence((1, 2), timeline, events, league_code="NBA")
        assert evidence.leverage == "HIGH"


# ---------------------------------------------------------------------------
# Empty inputs / boundaries
# ---------------------------------------------------------------------------


class TestEmptyAndOutOfRange:
    def test_empty_pbp_returns_empty_evidence(self):
        from app.services.pipeline.helpers.evidence_selection import select_evidence
        from app.services.pipeline.helpers.score_timeline import ScoreTimeline

        evidence = select_evidence((0, 5), ScoreTimeline(), [], league_code="NBA")
        assert evidence.scoring_plays == []
        assert evidence.leverage == "MEDIUM"

    def test_inverted_range_returns_empty_evidence(self):
        from app.services.pipeline.helpers.evidence_selection import select_evidence
        from app.services.pipeline.helpers.score_timeline import build_score_timeline

        events = [_play(0, 0, 0), _play(1, 2, 0, team="HOME", player="A")]
        timeline = build_score_timeline(events)
        evidence = select_evidence((5, 1), timeline, events)
        assert evidence.scoring_plays == []


# ---------------------------------------------------------------------------
# Special markers (NHL, MLB)
# ---------------------------------------------------------------------------


class TestSpecialMarkers:
    def test_nhl_power_play_goal_flag(self):
        from app.services.pipeline.helpers.evidence_selection import select_evidence
        from app.services.pipeline.helpers.score_timeline import build_score_timeline

        events = [
            _play(0, 0, 0, quarter=1),
            _play(
                1,
                1,
                0,
                quarter=1,
                team="HOME",
                player="McDavid",
                play_type="goal",
                description="McDavid scores on the power play",
            ),
        ]
        timeline = build_score_timeline(events, league_code="NHL")
        evidence = select_evidence((0, 1), timeline, events, league_code="NHL")

        assert evidence.scoring_plays[0].is_power_play_goal is True
        assert evidence.is_power_play_goal is True
        # No empty-net cue in the description -> false.
        assert evidence.is_empty_net is False

    def test_nhl_empty_net_goal_flag(self):
        from app.services.pipeline.helpers.evidence_selection import select_evidence
        from app.services.pipeline.helpers.score_timeline import build_score_timeline

        events = [
            _play(0, 0, 0, quarter=1),
            _play(1, 1, 0, quarter=1, team="HOME", player="A", play_type="goal"),
            _play(2, 1, 1, quarter=2, team="AWAY", player="B", play_type="goal"),
            _play(
                3,
                2,
                1,
                quarter=3,
                team="HOME",
                player="Pastrnak",
                play_type="goal",
                description="Pastrnak scores into the empty net",
            ),
        ]
        timeline = build_score_timeline(events, league_code="NHL")
        evidence = select_evidence((3, 3), timeline, events, league_code="NHL")

        assert len(evidence.scoring_plays) == 1
        assert evidence.scoring_plays[0].is_empty_net_goal is True
        assert evidence.is_empty_net is True

    def test_mlb_home_run_flag(self):
        from app.services.pipeline.helpers.evidence_selection import select_evidence
        from app.services.pipeline.helpers.score_timeline import build_score_timeline

        events = [
            _play(0, 0, 0, quarter=1),
            _play(
                1,
                3,
                0,
                quarter=1,
                team="HOME",
                player="Judge",
                play_type="home_run",
                description="Judge hits a 3-run home run",
            ),
        ]
        timeline = build_score_timeline(events, league_code="MLB")
        evidence = select_evidence((0, 1), timeline, events, league_code="MLB")

        assert evidence.scoring_plays[0].is_home_run is True

    def test_overtime_flag_set_for_overtime_segment(self):
        from app.services.pipeline.helpers.evidence_selection import select_evidence
        from app.services.pipeline.helpers.score_timeline import build_score_timeline

        # NBA regulation_periods=4; quarter=5 is OT. Plays 0 and 1 establish
        # a tied score entering OT; plays 2-3 fall inside the requested range.
        events = [
            _play(0, 0, 0, quarter=1),
            _play(1, 100, 100, quarter=4, team="HOME", player="X", play_type="2pt"),
            _play(2, 102, 100, quarter=5, team="HOME", player="A", play_type="2pt"),
            _play(3, 102, 102, quarter=5, team="AWAY", player="B", play_type="2pt"),
        ]
        timeline = build_score_timeline(events, league_code="NBA")
        evidence = select_evidence((2, 3), timeline, events, league_code="NBA")

        assert evidence.is_overtime is True
        assert all(sp.is_overtime for sp in evidence.scoring_plays)
        # Overtime forces HIGH leverage regardless of margin.
        assert evidence.leverage == "HIGH"


# ---------------------------------------------------------------------------
# Scoring run detection
# ---------------------------------------------------------------------------


class TestScoringRuns:
    def test_detects_8_point_run_for_nba(self):
        from app.services.pipeline.helpers.evidence_selection import select_evidence
        from app.services.pipeline.helpers.score_timeline import build_score_timeline

        # HOME goes on a 10-0 run (5 buckets, 2 pts each), AWAY never scores.
        events = [
            _play(0, 0, 0),
            _play(1, 2, 0, team="HOME", player="A", play_type="2pt"),
            _play(2, 4, 0, team="HOME", player="A", play_type="2pt"),
            _play(3, 6, 0, team="HOME", player="B", play_type="2pt"),
            _play(4, 8, 0, team="HOME", player="A", play_type="2pt"),
            _play(5, 10, 0, team="HOME", player="B", play_type="2pt"),
        ]
        timeline = build_score_timeline(events)

        evidence = select_evidence((0, 5), timeline, events, league_code="NBA")
        assert evidence.is_scoring_run is True
        assert len(evidence.scoring_runs) == 1
        run = evidence.scoring_runs[0]
        assert run.points == 10
        assert run.duration_plays == 5
        assert run.team == "HOME"

    def test_run_breaks_when_other_team_scores(self):
        from app.services.pipeline.helpers.evidence_selection import select_evidence
        from app.services.pipeline.helpers.score_timeline import build_score_timeline

        # HOME starts a 6-0 run, AWAY interrupts, then HOME runs again to 12.
        events = [
            _play(0, 0, 0),
            _play(1, 2, 0, team="HOME", player="A", play_type="2pt"),
            _play(2, 4, 0, team="HOME", player="A", play_type="2pt"),
            _play(3, 6, 0, team="HOME", player="A", play_type="2pt"),
            _play(4, 6, 2, team="AWAY", player="B", play_type="2pt"),  # break
            _play(5, 8, 2, team="HOME", player="A", play_type="2pt"),
            _play(6, 10, 2, team="HOME", player="C", play_type="2pt"),
        ]
        timeline = build_score_timeline(events)

        evidence = select_evidence((0, 6), timeline, events, league_code="NBA")
        # Neither sub-run reaches NBA's 8-pt threshold individually.
        assert evidence.scoring_runs == []
        assert evidence.is_scoring_run is False


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_same_input_yields_identical_output(self):
        from app.services.pipeline.helpers.evidence_selection import select_evidence
        from app.services.pipeline.helpers.score_timeline import build_score_timeline

        events = [
            _play(0, 0, 0),
            _play(1, 2, 0, team="HOME", player="A", play_type="2pt"),
            _play(2, 2, 3, team="AWAY", player="B", play_type="3pt"),
            _play(3, 5, 3, team="HOME", player="A", play_type="3pt"),
        ]
        timeline = build_score_timeline(events)

        first = select_evidence((0, 3), timeline, events, league_code="NBA")
        second = select_evidence((0, 3), timeline, events, league_code="NBA")
        assert first == second
