"""Tests for live/mlb_statcast.py — pitch classification and aggregation logic."""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRAPER_ROOT = REPO_ROOT / "scraper"
if str(SCRAPER_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRAPER_ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/test_db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ENVIRONMENT", "development")

import pytest

from sports_scraper.live.mlb_statcast import (
    aggregate_from_payload,
    is_barrel,
    is_contact,
    is_hard_hit,
    is_in_zone,
    is_swing,
)

# ---------------------------------------------------------------------------
# Zone classification
# ---------------------------------------------------------------------------


class TestZoneClassification:
    @pytest.mark.parametrize("zone", list(range(1, 10)))
    def test_zones_1_through_9_are_in_zone(self, zone):
        assert is_in_zone(zone) is True

    @pytest.mark.parametrize("zone", list(range(11, 15)))
    def test_zones_11_through_14_are_outside(self, zone):
        assert is_in_zone(zone) is False

    def test_zone_none_returns_none(self):
        assert is_in_zone(None) is None

    def test_zone_0_returns_none(self):
        assert is_in_zone(0) is None

    def test_zone_10_returns_none(self):
        assert is_in_zone(10) is None

    def test_zone_15_returns_none(self):
        assert is_in_zone(15) is None


# ---------------------------------------------------------------------------
# Swing detection
# ---------------------------------------------------------------------------


class TestSwingDetection:
    @pytest.mark.parametrize("code", ["S", "F", "X", "T", "W", "E", "D", "L"])
    def test_swing_codes(self, code):
        assert is_swing(code) is True

    @pytest.mark.parametrize("code", ["B", "C", "*B", "V", "P", "Q", "R", "I", "Y", "H"])
    def test_non_swing_codes(self, code):
        assert is_swing(code) is False

    def test_none_is_not_swing(self):
        assert is_swing(None) is False

    def test_empty_string_is_not_swing(self):
        assert is_swing("") is False


# ---------------------------------------------------------------------------
# Contact detection
# ---------------------------------------------------------------------------


class TestContactDetection:
    @pytest.mark.parametrize("code", ["F", "X", "T", "D", "L", "E"])
    def test_contact_codes(self, code):
        assert is_contact(code) is True

    @pytest.mark.parametrize("code", ["S", "W"])
    def test_swing_without_contact(self, code):
        """S (swinging strike) and W (swinging strike blocked) are swings but not contact."""
        assert is_contact(code) is False

    def test_none_is_not_contact(self):
        assert is_contact(None) is False

    def test_empty_string_is_not_contact(self):
        assert is_contact("") is False


# ---------------------------------------------------------------------------
# Hard hit
# ---------------------------------------------------------------------------


class TestHardHit:
    def test_at_threshold(self):
        assert is_hard_hit(95.0) is True

    def test_above_threshold(self):
        assert is_hard_hit(105.3) is True

    def test_below_threshold(self):
        assert is_hard_hit(94.9) is False

    def test_none_returns_false(self):
        assert is_hard_hit(None) is False


# ---------------------------------------------------------------------------
# Barrel
# ---------------------------------------------------------------------------


class TestBarrel:
    def test_below_min_exit_velo(self):
        assert is_barrel(97.0, 28.0) is False

    def test_at_98_within_angle_window(self):
        """At 98 mph, angle window is 26-30 degrees."""
        assert is_barrel(98.0, 28.0) is True

    def test_at_98_at_lower_bound(self):
        assert is_barrel(98.0, 26.0) is True

    def test_at_98_at_upper_bound(self):
        assert is_barrel(98.0, 30.0) is True

    def test_at_98_below_angle_window(self):
        assert is_barrel(98.0, 25.9) is False

    def test_at_98_above_angle_window(self):
        assert is_barrel(98.0, 30.1) is False

    def test_at_100_wider_window(self):
        """At 100 mph (2 extra), window is 24-32 degrees."""
        assert is_barrel(100.0, 24.0) is True
        assert is_barrel(100.0, 32.0) is True
        assert is_barrel(100.0, 23.9) is False

    def test_angle_cap_at_50(self):
        """Upper angle caps at 50 degrees even at very high exit velo."""
        assert is_barrel(120.0, 50.0) is True
        assert is_barrel(120.0, 51.0) is False

    def test_none_speed_returns_false(self):
        assert is_barrel(None, 28.0) is False

    def test_none_angle_returns_false(self):
        assert is_barrel(98.0, None) is False

    def test_both_none_returns_false(self):
        assert is_barrel(None, None) is False


# ---------------------------------------------------------------------------
# Aggregation from playByPlay payload
# ---------------------------------------------------------------------------


class TestAggregation:
    @staticmethod
    def _build_pitch_event(
        zone=5,
        code="S",
        is_pitch=True,
        hit_data=None,
    ):
        """Build a minimal playEvents entry."""
        event = {
            "isPitch": is_pitch,
            "details": {"code": code},
            "pitchData": {"zone": zone},
        }
        if hit_data is not None:
            event["hitData"] = hit_data
        return event

    @staticmethod
    def _build_at_bat(is_top_inning, events):
        """Build a minimal allPlays entry."""
        return {
            "about": {"isTopInning": is_top_inning},
            "playEvents": events,
        }

    def test_empty_payload(self):
        result = aggregate_from_payload({})
        assert result["home"].total_pitches == 0
        assert result["away"].total_pitches == 0

    def test_top_inning_counts_as_away_batting(self):
        """Top of inning = away team is batting."""
        payload = {
            "allPlays": [
                self._build_at_bat(
                    is_top_inning=True,
                    events=[self._build_pitch_event(zone=5, code="S")],
                ),
            ]
        }
        result = aggregate_from_payload(payload)
        assert result["away"].total_pitches == 1
        assert result["away"].zone_pitches == 1
        assert result["away"].zone_swings == 1
        assert result["home"].total_pitches == 0

    def test_bottom_inning_counts_as_home_batting(self):
        """Bottom of inning = home team is batting."""
        payload = {
            "allPlays": [
                self._build_at_bat(
                    is_top_inning=False,
                    events=[self._build_pitch_event(zone=5, code="F")],
                ),
            ]
        }
        result = aggregate_from_payload(payload)
        assert result["home"].total_pitches == 1
        assert result["home"].zone_pitches == 1
        assert result["home"].zone_swings == 1
        assert result["home"].zone_contact == 1
        assert result["away"].total_pitches == 0

    def test_outside_zone_tracking(self):
        payload = {
            "allPlays": [
                self._build_at_bat(
                    is_top_inning=True,
                    events=[self._build_pitch_event(zone=12, code="S")],
                ),
            ]
        }
        result = aggregate_from_payload(payload)
        assert result["away"].outside_pitches == 1
        assert result["away"].outside_swings == 1
        assert result["away"].outside_contact == 0

    def test_non_pitch_events_are_ignored(self):
        payload = {
            "allPlays": [
                self._build_at_bat(
                    is_top_inning=True,
                    events=[self._build_pitch_event(zone=5, code="S", is_pitch=False)],
                ),
            ]
        }
        result = aggregate_from_payload(payload)
        assert result["away"].total_pitches == 0

    def test_hit_data_accumulation(self):
        hit_data = {"launchSpeed": 100.0, "launchAngle": 28.0}
        payload = {
            "allPlays": [
                self._build_at_bat(
                    is_top_inning=True,
                    events=[
                        self._build_pitch_event(zone=5, code="X", hit_data=hit_data),
                    ],
                ),
            ]
        }
        result = aggregate_from_payload(payload)
        agg = result["away"]
        assert agg.balls_in_play == 1
        assert agg.total_exit_velo == 100.0
        assert agg.hard_hit_count == 1  # 100 >= 95
        assert agg.barrel_count == 1  # 100 mph, 28 deg -> barrel

    def test_hit_data_no_barrel_below_threshold(self):
        hit_data = {"launchSpeed": 90.0, "launchAngle": 28.0}
        payload = {
            "allPlays": [
                self._build_at_bat(
                    is_top_inning=False,
                    events=[
                        self._build_pitch_event(zone=5, code="X", hit_data=hit_data),
                    ],
                ),
            ]
        }
        result = aggregate_from_payload(payload)
        agg = result["home"]
        assert agg.balls_in_play == 1
        assert agg.hard_hit_count == 0  # 90 < 95
        assert agg.barrel_count == 0

    def test_realistic_mixed_payload(self):
        """Test a realistic multi-at-bat, multi-pitch payload."""
        payload = {
            "allPlays": [
                # Top 1st — away batting
                self._build_at_bat(
                    is_top_inning=True,
                    events=[
                        self._build_pitch_event(zone=5, code="C"),  # called strike (no swing)
                        self._build_pitch_event(zone=12, code="B"),  # ball outside
                        self._build_pitch_event(zone=3, code="F"),  # foul in zone (swing+contact)
                        self._build_pitch_event(
                            zone=7,
                            code="X",
                            hit_data={"launchSpeed": 102.0, "launchAngle": 25.0},
                        ),  # in play
                    ],
                ),
                # Bottom 1st — home batting
                self._build_at_bat(
                    is_top_inning=False,
                    events=[
                        self._build_pitch_event(zone=1, code="S"),  # swinging strike in zone
                        self._build_pitch_event(
                            zone=14, code="W"
                        ),  # swinging strike blocked outside
                    ],
                ),
            ]
        }
        result = aggregate_from_payload(payload)

        away = result["away"]
        assert away.total_pitches == 4
        assert away.zone_pitches == 3  # zones 5, 3, 7
        assert away.zone_swings == 2  # F and X are swings
        assert away.zone_contact == 2  # F and X are contact
        assert away.outside_pitches == 1  # zone 12
        assert away.outside_swings == 0  # B is not a swing
        assert away.balls_in_play == 1
        assert away.total_exit_velo == 102.0
        assert away.hard_hit_count == 1  # 102 >= 95

        home = result["home"]
        assert home.total_pitches == 2
        assert home.zone_pitches == 1  # zone 1
        assert home.zone_swings == 1  # S
        assert home.zone_contact == 0  # S is not contact
        assert home.outside_pitches == 1  # zone 14
        assert home.outside_swings == 1  # W is a swing
        assert home.outside_contact == 0  # W is not contact
