"""Tests for MLB PA outcome labeler."""

from __future__ import annotations

import pytest

from app.analytics.datasets.mlb_pa_labeler import PA_OUTCOME_LABELS, label_pa_event


class TestLabelPaEvent:
    """Core event mapping tests."""

    @pytest.mark.parametrize(
        "event_str,expected",
        [
            ("Strikeout", "strikeout"),
            ("strikeout", "strikeout"),
            ("Strikeout - DP", "strikeout"),
            ("Walk", "walk_or_hbp"),
            ("Intent Walk", "walk_or_hbp"),
            ("Hit By Pitch", "walk_or_hbp"),
            ("Single", "single"),
            ("Double", "double"),
            ("Triple", "triple"),
            ("Home Run", "home_run"),
            ("Groundout", "ball_in_play_out"),
            ("Flyout", "ball_in_play_out"),
            ("Lineout", "ball_in_play_out"),
            ("Pop Out", "ball_in_play_out"),
            ("Forceout", "ball_in_play_out"),
            ("Grounded Into DP", "ball_in_play_out"),
            ("Sac Fly", "ball_in_play_out"),
            ("Sac Bunt", "ball_in_play_out"),
            ("Field Error", "ball_in_play_out"),
            ("Field Out", "ball_in_play_out"),
            ("Fielders Choice", "ball_in_play_out"),
            ("Double Play", "ball_in_play_out"),
            ("Bunt Groundout", "ball_in_play_out"),
        ],
    )
    def test_known_events(self, event_str, expected):
        assert label_pa_event(event_str) == expected

    @pytest.mark.parametrize(
        "event_str",
        [
            "Stolen Base",
            "Caught Stealing",
            "Wild Pitch",
            "Passed Ball",
            "Balk",
            "Pickoff",
            "",
        ],
    )
    def test_non_pa_events_return_none(self, event_str):
        assert label_pa_event(event_str) is None

    def test_none_input(self):
        assert label_pa_event("") is None

    def test_fuzzy_strikeout(self):
        assert label_pa_event("Strikeout Looking") == "strikeout"

    def test_fuzzy_walk(self):
        assert label_pa_event("Intentional Walk") == "walk_or_hbp"

    def test_fuzzy_homer(self):
        assert label_pa_event("Two-Run Homer") == "home_run"

    def test_fuzzy_flyout(self):
        assert label_pa_event("Sacrifice Fly Out") == "ball_in_play_out"

    def test_fuzzy_single(self):
        assert label_pa_event("Infield Single") == "single"

    def test_fuzzy_double(self):
        assert label_pa_event("Ground Rule Double") == "double"

    def test_fuzzy_triple(self):
        assert label_pa_event("Ground Rule Triple") == "triple"

    def test_fuzzy_walk_variant(self):
        assert label_pa_event("Base On Walk") == "walk_or_hbp"

    def test_unknown_event_returns_none(self):
        assert label_pa_event("Mound Visit") is None

    def test_canonical_labels_count(self):
        assert len(PA_OUTCOME_LABELS) == 7
