"""Tests for PA training data helpers in _training_helpers.py."""

from __future__ import annotations

from types import SimpleNamespace

from app.tasks._training_data import _derive_pa_outcome


class TestDerivePaOutcome:
    """Unit tests for _derive_pa_outcome heuristic."""

    def _make_stats(self, **overrides) -> SimpleNamespace:
        defaults = {
            "barrel_pct": 0.07,
            "hard_hit_pct": 0.35,
            "avg_exit_velo": 88.0,
            "z_contact_pct": 0.84,
            "o_contact_pct": 0.60,
            "z_swing_pct": 0.68,
            "o_swing_pct": 0.32,
            "balls_in_play": 3,
            "total_pitches": 15,
            "zone_swings": 10,
            "outside_swings": 5,
            "zone_contact": 8,
            "outside_contact": 3,
        }
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def test_high_whiff_returns_strikeout(self) -> None:
        stats = self._make_stats(
            zone_swings=10, outside_swings=10,
            zone_contact=4, outside_contact=2,
        )
        # whiff_rate = 1 - 6/20 = 0.70
        assert _derive_pa_outcome(stats) == "strikeout"

    def test_low_swing_returns_walk(self) -> None:
        stats = self._make_stats(
            z_swing_pct=0.50, o_swing_pct=0.15,
            zone_swings=8, outside_swings=2,
            zone_contact=7, outside_contact=2,
        )
        assert _derive_pa_outcome(stats) == "walk_or_hbp"

    def test_high_barrel_high_ev_returns_home_run(self) -> None:
        stats = self._make_stats(
            barrel_pct=0.20, avg_exit_velo=98.0,
            hard_hit_pct=0.60,
            zone_swings=10, outside_swings=5,
            zone_contact=8, outside_contact=4,
        )
        assert _derive_pa_outcome(stats) == "home_run"

    def test_high_hard_hit_returns_double(self) -> None:
        stats = self._make_stats(
            hard_hit_pct=0.55, avg_exit_velo=95.0,
            barrel_pct=0.10,
            zone_swings=10, outside_swings=5,
            zone_contact=8, outside_contact=4,
        )
        assert _derive_pa_outcome(stats) == "double"

    def test_moderate_contact_returns_single(self) -> None:
        stats = self._make_stats(
            hard_hit_pct=0.42, avg_exit_velo=89.0,
            balls_in_play=5,
            zone_swings=10, outside_swings=5,
            zone_contact=8, outside_contact=4,
        )
        assert _derive_pa_outcome(stats) == "single"

    def test_low_hard_hit_returns_out(self) -> None:
        stats = self._make_stats(
            hard_hit_pct=0.15, avg_exit_velo=85.0,
            barrel_pct=0.02, balls_in_play=2,
            zone_swings=10, outside_swings=5,
            zone_contact=8, outside_contact=4,
        )
        assert _derive_pa_outcome(stats) == "ball_in_play_out"

    def test_no_bip_returns_out(self) -> None:
        stats = self._make_stats(
            balls_in_play=0, hard_hit_pct=0.0,
            zone_swings=10, outside_swings=5,
            zone_contact=8, outside_contact=4,
        )
        assert _derive_pa_outcome(stats) == "ball_in_play_out"

    def test_moderate_whiff_returns_strikeout(self) -> None:
        stats = self._make_stats(
            zone_swings=10, outside_swings=10,
            zone_contact=7, outside_contact=4,
            hard_hit_pct=0.25, balls_in_play=2,
        )
        # whiff_rate = 1 - 11/20 = 0.45 > 0.40
        assert _derive_pa_outcome(stats) == "strikeout"

    def test_all_outcomes_are_valid(self) -> None:
        """Every outcome returned must be a valid PA outcome."""
        from app.analytics.sports.mlb.constants import PA_EVENTS

        test_cases = [
            {},
            {"barrel_pct": 0.25, "avg_exit_velo": 100.0},
            {"z_swing_pct": 0.40, "o_swing_pct": 0.10},
            {"hard_hit_pct": 0.60, "avg_exit_velo": 96.0},
            {"balls_in_play": 0, "total_pitches": 20},
            {"zone_swings": 5, "outside_swings": 15,
             "zone_contact": 1, "outside_contact": 1},
        ]
        for overrides in test_cases:
            stats = self._make_stats(**overrides)
            outcome = _derive_pa_outcome(stats)
            assert outcome in PA_EVENTS, f"Invalid outcome '{outcome}' for {overrides}"
