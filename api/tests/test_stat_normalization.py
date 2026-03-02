"""Tests for stat_normalization.normalize_stats."""

from __future__ import annotations

from app.services.stat_normalization import normalize_stats


class TestNormalizeStats:
    def test_empty_stats(self) -> None:
        assert normalize_stats({}, "NBA") == []

    def test_basic_flat_stats(self) -> None:
        raw = {"points": 25, "rebounds": 10, "assists": 7}
        result = normalize_stats(raw, "NBA")
        keys = [s["key"] for s in result]
        assert "points" in keys
        assert "rebounds" in keys
        assert "assists" in keys

    def test_alias_resolution(self) -> None:
        # Basketball Reference uses "trb" for total rebounds
        raw = {"trb": 12, "ast": 5, "pts": 20}
        result = normalize_stats(raw, "NBA")
        keys = {s["key"]: s["value"] for s in result}
        assert keys["rebounds"] == 12
        assert keys["assists"] == 5
        assert keys["points"] == 20

    def test_nested_cbb_format(self) -> None:
        # CBB API nests rebounds like {"total": 8, "offensive": 3}
        raw = {
            "rebounds": {"total": 8, "offensive": 3, "defensive": 5},
            "points": 15,
        }
        result = normalize_stats(raw, "NCAAB")
        keys = {s["key"]: s["value"] for s in result}
        assert keys["rebounds"] == 8

    def test_dot_notation_alias(self) -> None:
        raw = {
            "free_throws": {"made": 5, "attempted": 7},
            "points": 20,
        }
        result = normalize_stats(raw, "NBA")
        keys = {s["key"]: s["value"] for s in result}
        assert keys.get("free_throws_made") == 5

    def test_dedup(self) -> None:
        # If both canonical and alias present, only one should appear
        raw = {"rebounds": 10, "trb": 12}
        result = normalize_stats(raw, "NBA")
        reb_entries = [s for s in result if s["key"] == "rebounds"]
        assert len(reb_entries) == 1

    def test_display_label(self) -> None:
        raw = {"points": 25}
        result = normalize_stats(raw, "NBA")
        assert result[0]["displayLabel"] == "PTS"

    def test_group(self) -> None:
        raw = {"points": 25}
        result = normalize_stats(raw, "NBA")
        assert result[0]["group"] == "scoring"

    def test_format_type(self) -> None:
        raw = {"fg_pct": 0.485}
        result = normalize_stats(raw, "NBA")
        pct_stats = [s for s in result if s["formatType"] == "pct"]
        assert len(pct_stats) >= 1

    def test_invalid_value_skipped(self) -> None:
        raw = {"points": "not_a_number"}
        result = normalize_stats(raw, "NBA")
        pts = [s for s in result if s["key"] == "points"]
        assert len(pts) == 0


class TestMLBTeamBoxscoreNormalization:
    """Tests that MLB stat aliases resolve against the actual persisted structure.

    MLB team boxscores are stored as:
      {"points": 5, "hits": 10,
       "batting": {"runs": "5", "hits": "10", "atBats": "35", ...},
       "pitching": {"era": "3.00", ...},
       "fielding": {"errors": "1", ...}}
    """

    STORED = {
        "points": 5,
        "hits": 10,
        "batting": {
            "runs": "5",
            "hits": "10",
            "atBats": "35",
            "homeRuns": "2",
            "rbi": "4",
            "baseOnBalls": "3",
            "strikeOuts": "8",
            "stolenBases": "1",
            "leftOnBase": "7",
            "avg": ".286",
            "obp": ".350",
            "slg": ".500",
        },
        "pitching": {
            "era": "3.00",
        },
        "fielding": {
            "errors": "1",
        },
    }

    def test_runs_from_points(self) -> None:
        result = normalize_stats(self.STORED, "MLB")
        by_key = {s["key"]: s["value"] for s in result}
        assert by_key["runs"] == 5

    def test_hits_from_top_level(self) -> None:
        result = normalize_stats(self.STORED, "MLB")
        by_key = {s["key"]: s["value"] for s in result}
        assert by_key["hits"] == 10

    def test_errors_from_fielding(self) -> None:
        result = normalize_stats(self.STORED, "MLB")
        by_key = {s["key"]: s["value"] for s in result}
        assert by_key["errors"] == 1

    def test_batting_stats_from_nested(self) -> None:
        result = normalize_stats(self.STORED, "MLB")
        by_key = {s["key"]: s["value"] for s in result}
        assert by_key["at_bats"] == 35
        assert by_key["home_runs"] == 2
        assert by_key["rbi"] == 4
        assert by_key["base_on_balls"] == 3
        assert by_key["strike_outs"] == 8
        assert by_key["stolen_bases"] == 1
        assert by_key["left_on_base"] == 7

    def test_batting_rate_stats(self) -> None:
        result = normalize_stats(self.STORED, "MLB")
        by_key = {s["key"]: s["value"] for s in result}
        assert by_key["avg"] == ".286"
        assert by_key["obp"] == ".350"
        assert by_key["slg"] == ".500"

    def test_era_from_pitching(self) -> None:
        result = normalize_stats(self.STORED, "MLB")
        by_key = {s["key"]: s["value"] for s in result}
        assert by_key["era"] == "3.00"

    def test_all_expected_keys_present(self) -> None:
        result = normalize_stats(self.STORED, "MLB")
        keys = {s["key"] for s in result}
        expected = {
            "runs", "hits", "errors", "left_on_base",
            "at_bats", "home_runs", "rbi", "base_on_balls",
            "strike_outs", "stolen_bases", "avg", "obp", "slg", "era",
        }
        assert expected == keys
