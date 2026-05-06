"""Tests for sport-specific flow thresholds in league_config."""

from __future__ import annotations

from app.services.pipeline.stages.league_config import (
    FLOW_THRESHOLDS,
    get_flow_thresholds,
)


class TestFlowThresholdsLookup:
    """Verify per-league thresholds resolve to the spec'd values."""

    def test_nba_thresholds(self) -> None:
        cfg = get_flow_thresholds("NBA")
        assert cfg["lead_created"] == 6
        assert cfg["meaningful_lead"] == 10
        assert cfg["large_lead"] == 15
        assert cfg["comeback_pressure"] == 7
        assert cfg["clutch_window_pts"] == 5
        assert cfg["clutch_window_minutes"] == 5
        assert cfg["game_out_of_reach_lead"] == 15
        assert cfg["game_out_of_reach_minutes"] == 2
        assert cfg["scoring_run_pts"] == 8
        assert cfg["scoring_run_opp_pts"] == 0

    def test_mlb_thresholds(self) -> None:
        cfg = get_flow_thresholds("MLB")
        assert cfg["multi_run_inning"] == 2
        assert cfg["major_inning"] == 4
        assert cfg["blowout_run_margin"] == 7
        assert cfg["blowout_after_inning"] == 5
        assert cfg["late_leverage_inning"] == 7
        assert cfg["low_scoring_combined"] == 4
        assert cfg["shutout"] == 0
        assert cfg["early_avalanche_runs"] == 4
        assert cfg["early_avalanche_innings"] == 2

    def test_nhl_thresholds(self) -> None:
        cfg = get_flow_thresholds("NHL")
        assert cfg["close_game_entering_third"] == 1
        assert cfg["safe_entering_third"] == 2
        assert cfg["late_tying_goal_window_minutes"] == 5
        assert cfg["power_play_swing_requires_state_change"] is True

    def test_ncaab_inherits_nba_scoring_thresholds(self) -> None:
        ncaab = get_flow_thresholds("NCAAB")
        nba = get_flow_thresholds("NBA")
        assert ncaab == nba

    def test_lookup_is_case_insensitive(self) -> None:
        assert get_flow_thresholds("nba") == get_flow_thresholds("NBA")
        assert get_flow_thresholds("Mlb") == get_flow_thresholds("MLB")


class TestUnknownLeagueFallback:
    """Unknown leagues fall back to NBA thresholds (per issue spec)."""

    def test_unknown_league_returns_nba_thresholds(self) -> None:
        assert get_flow_thresholds("WNBA") == get_flow_thresholds("NBA")

    def test_empty_string_returns_nba_thresholds(self) -> None:
        assert get_flow_thresholds("") == get_flow_thresholds("NBA")

    def test_none_returns_nba_thresholds(self) -> None:
        assert get_flow_thresholds(None) == get_flow_thresholds("NBA")


class TestFlowThresholdsImmutability:
    """Mutating the returned dict must not corrupt module-level config."""

    def test_returned_dict_is_isolated_copy(self) -> None:
        cfg = get_flow_thresholds("NBA")
        cfg["lead_created"] = 999
        fresh = get_flow_thresholds("NBA")
        assert fresh["lead_created"] == 6

    def test_module_level_dict_exposes_all_supported_leagues(self) -> None:
        assert set(FLOW_THRESHOLDS) == {"NBA", "MLB", "NHL", "NCAAB"}
