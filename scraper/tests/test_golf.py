"""Tests for golf data ingestion — DataGolf client, models, and persistence."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# DataGolf models
# ---------------------------------------------------------------------------


class TestDGModels:
    """Verify golf data models can be constructed."""

    def test_tournament(self):
        from sports_scraper.golf.models import DGTournament

        t = DGTournament(
            event_id="026",
            event_name="The Masters",
            course="Augusta National",
            course_key="augusta_national",
            start_date=date(2026, 4, 9),
            end_date=date(2026, 4, 12),
            tour="pga",
            purse=20_000_000.0,
        )
        assert t.event_name == "The Masters"
        assert t.tour == "pga"

    def test_player(self):
        from sports_scraper.golf.models import DGPlayer

        p = DGPlayer(dg_id=18417, player_name="Scottie Scheffler", country="USA")
        assert p.dg_id == 18417
        assert p.amateur is False

    def test_field_entry(self):
        from sports_scraper.golf.models import DGFieldEntry

        e = DGFieldEntry(dg_id=18417, player_name="Scottie Scheffler", dk_salary=11200)
        assert e.dk_salary == 11200

    def test_skill_rating(self):
        from sports_scraper.golf.models import DGSkillRating

        r = DGSkillRating(dg_id=18417, player_name="Scottie Scheffler", sg_total=2.5, sg_putt=0.3)
        assert r.sg_total == 2.5

    def test_leaderboard_entry(self):
        from sports_scraper.golf.models import DGLeaderboardEntry

        e = DGLeaderboardEntry(
            dg_id=18417,
            player_name="Scottie Scheffler",
            position=1,
            total_score=-12,
            thru=18,
        )
        assert e.position == 1
        assert e.total_score == -12
        assert e.status == "active"

    def test_odds_outright(self):
        from sports_scraper.golf.models import DGOddsOutright

        o = DGOddsOutright(
            dg_id=18417,
            player_name="Scottie Scheffler",
            book="draftkings",
            market="win",
            odds=600.0,
        )
        assert o.book == "draftkings"
        assert o.market == "win"

    def test_dfs_projection(self):
        from sports_scraper.golf.models import DGDFSProjection

        p = DGDFSProjection(
            dg_id=18417,
            player_name="Scottie Scheffler",
            site="draftkings",
            salary=11200,
            projected_points=82.5,
        )
        assert p.projected_points == 82.5

    def test_ranking(self):
        from sports_scraper.golf.models import DGRanking

        r = DGRanking(dg_id=18417, player_name="Scottie Scheffler", rank=1, owgr=1)
        assert r.rank == 1

    def test_pre_tournament_pred(self):
        from sports_scraper.golf.models import DGPreTournamentPred

        p = DGPreTournamentPred(
            dg_id=18417,
            player_name="Scottie Scheffler",
            win_prob=0.15,
            make_cut_prob=0.95,
        )
        assert p.win_prob == 0.15

    def test_round(self):
        from sports_scraper.golf.models import DGRound

        r = DGRound(
            dg_id=18417,
            player_name="Scottie Scheffler",
            event_id="026",
            round_num=1,
            score=-5,
            sg_total=3.2,
        )
        assert r.round_num == 1

    def test_event_result(self):
        from sports_scraper.golf.models import DGEventResult

        r = DGEventResult(
            dg_id=18417,
            player_name="Scottie Scheffler",
            event_id="026",
            event_name="The Masters",
            finish_position=1,
            earnings=3_600_000.0,
        )
        assert r.finish_position == 1


# ---------------------------------------------------------------------------
# Client parsing helpers
# ---------------------------------------------------------------------------


class TestNormalizeStatus:
    """Test _normalize_status merges status + position signals correctly."""

    def test_explicit_cut_status(self):
        from sports_scraper.golf.client_parsing import _normalize_status

        assert _normalize_status("cut", None) == "cut"
        assert _normalize_status("CUT", None) == "cut"

    def test_mc_status(self):
        from sports_scraper.golf.client_parsing import _normalize_status

        assert _normalize_status("mc", None) == "cut"
        assert _normalize_status("MC", None) == "cut"
        assert _normalize_status("missed cut", None) == "cut"

    def test_wd_status(self):
        from sports_scraper.golf.client_parsing import _normalize_status

        assert _normalize_status("wd", None) == "wd"
        assert _normalize_status("WD", None) == "wd"
        assert _normalize_status("w/d", None) == "wd"
        assert _normalize_status("withdrew", None) == "wd"

    def test_dq_status(self):
        from sports_scraper.golf.client_parsing import _normalize_status

        assert _normalize_status("dq", None) == "dq"
        assert _normalize_status("DQ", None) == "dq"
        assert _normalize_status("dsq", None) == "dq"
        assert _normalize_status("disqualified", None) == "dq"

    def test_active_status(self):
        from sports_scraper.golf.client_parsing import _normalize_status

        assert _normalize_status("active", None) == "active"
        assert _normalize_status("active", "T4") == "active"

    def test_missing_status_defaults_to_active(self):
        from sports_scraper.golf.client_parsing import _normalize_status

        assert _normalize_status("", None) == "active"
        assert _normalize_status(None, None) == "active"

    def test_position_mc_overrides_missing_status(self):
        from sports_scraper.golf.client_parsing import _normalize_status

        assert _normalize_status("", "MC") == "cut"
        assert _normalize_status(None, "MC") == "cut"
        assert _normalize_status("", "CUT") == "cut"

    def test_position_mc_overrides_active_status(self):
        """DataGolf sometimes returns status=active with pos=MC."""
        from sports_scraper.golf.client_parsing import _normalize_status

        assert _normalize_status("active", "MC") == "cut"
        assert _normalize_status("active", "CUT") == "cut"

    def test_position_wd_overrides_missing_status(self):
        from sports_scraper.golf.client_parsing import _normalize_status

        assert _normalize_status("", "WD") == "wd"
        assert _normalize_status(None, "WD") == "wd"

    def test_position_dq_overrides_missing_status(self):
        from sports_scraper.golf.client_parsing import _normalize_status

        assert _normalize_status("", "DQ") == "dq"
        assert _normalize_status(None, "DQ") == "dq"

    def test_numeric_position_keeps_active(self):
        from sports_scraper.golf.client_parsing import _normalize_status

        assert _normalize_status("", "T4") == "active"
        assert _normalize_status("active", "1") == "active"


class TestClientHelpers:
    """Test the parsing helper functions in client.py."""

    def test_safe_float(self):
        from sports_scraper.golf.client_parsing import _safe_float

        assert _safe_float(1.5) == 1.5
        assert _safe_float("2.3") == 2.3
        assert _safe_float(None) is None
        assert _safe_float("") is None
        assert _safe_float("-") is None
        assert _safe_float("abc") is None

    def test_safe_int(self):
        from sports_scraper.golf.client_parsing import _safe_int

        assert _safe_int(5) == 5
        assert _safe_int("10") == 10
        assert _safe_int(None) is None
        assert _safe_int("") is None
        assert _safe_int("-") is None

    def test_parse_date(self):
        from sports_scraper.golf.client_parsing import _parse_date

        assert _parse_date("2026-04-09") == date(2026, 4, 9)
        assert _parse_date("2026-04-09T10:00:00Z") == date(2026, 4, 9)
        assert _parse_date(None) is None
        assert _parse_date("") is None
        assert _parse_date("invalid") is None


# ---------------------------------------------------------------------------
# Client API parsing
# ---------------------------------------------------------------------------


class TestDataGolfClientParsing:
    """Test DataGolf client response parsing with mock HTTP responses."""

    def _make_client(self):
        from sports_scraper.golf.client import DataGolfClient

        return DataGolfClient(api_key="test-key")

    def test_get_schedule_parses_response(self):
        client = self._make_client()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "event_id": "026",
                "event_name": "The Masters",
                "course": "Augusta National",
                "date": "2026-04-09",
                "end_date": "2026-04-12",
                "purse": 20000000,
                "country": "USA",
            }
        ]

        with patch.object(client, "_get", return_value=mock_response.json()):
            tournaments = client.get_schedule()

        assert len(tournaments) == 1
        assert tournaments[0].event_name == "The Masters"
        assert tournaments[0].tour == "pga"

    def test_get_player_list_parses_response(self):
        client = self._make_client()

        with patch.object(client, "_get", return_value=[
            {"dg_id": 18417, "player_name": "Scottie Scheffler", "country": "USA", "amateur": False},
            {"dg_id": 16543, "player_name": "Rory McIlroy", "country": "NIR"},
        ]):
            players = client.get_player_list()

        assert len(players) == 2
        assert players[0].player_name == "Scottie Scheffler"
        assert players[1].dg_id == 16543

    def test_get_field_updates_parses_response(self):
        client = self._make_client()

        with patch.object(client, "_get", return_value={
            "field": [
                {"dg_id": 18417, "player_name": "Scottie Scheffler", "dk_salary": 11200},
            ]
        }):
            entries = client.get_field_updates()

        assert len(entries) == 1
        assert entries[0].dk_salary == 11200

    def test_get_skill_ratings_parses_response(self):
        client = self._make_client()

        with patch.object(client, "_get", return_value={
            "players": [
                {"dg_id": 18417, "player_name": "Scottie Scheffler", "sg_total": 2.5, "sg_putt": 0.3},
            ]
        }):
            ratings = client.get_skill_ratings()

        assert len(ratings) == 1
        assert ratings[0].sg_total == 2.5

    def test_get_rankings_parses_response(self):
        client = self._make_client()

        with patch.object(client, "_get", return_value={
            "rankings": [
                {"dg_id": 18417, "player_name": "Scottie Scheffler", "rank": 1, "owgr": 1},
            ]
        }):
            rankings = client.get_rankings()

        assert len(rankings) == 1
        assert rankings[0].rank == 1

    def test_get_outrights_parses_multi_book(self):
        client = self._make_client()

        with patch.object(client, "_get", return_value={
            "odds": [
                {
                    "dg_id": 18417,
                    "player_name": "Scottie Scheffler",
                    "datagolf": 0.12,
                    "draftkings": 600,
                    "fanduel": 550,
                },
            ]
        }):
            odds = client.get_outrights()

        assert len(odds) == 2  # Two books
        books = {o.book for o in odds}
        assert "draftkings" in books
        assert "fanduel" in books
        assert all(o.dg_id == 18417 for o in odds)

    def test_get_dfs_projections_parses_response(self):
        client = self._make_client()

        with patch.object(client, "_get", return_value={
            "projections": [
                {"dg_id": 18417, "player_name": "Scottie Scheffler", "salary": 11200, "proj_pts": 82.5},
            ]
        }):
            projections = client.get_dfs_projections()

        assert len(projections) == 1
        assert projections[0].salary == 11200
        assert projections[0].projected_points == 82.5
        assert projections[0].site == "draftkings"

    def test_get_returns_none_on_error(self):
        client = self._make_client()

        with patch.object(client, "_get", return_value=None):
            assert client.get_schedule() == []
            assert client.get_player_list() == []
            assert client.get_field_updates() == []
            assert client.get_skill_ratings() == []
            assert client.get_rankings() == []
            assert client.get_outrights() == []
            assert client.get_dfs_projections() == []
            assert client.get_live_predictions() == ([], {})
            assert client.get_live_tournament_stats() == []

    def test_get_pre_tournament_predictions(self):
        client = self._make_client()

        with patch.object(client, "_get", return_value={
            "baseline_history_fit": [
                {"dg_id": 18417, "player_name": "Scottie Scheffler", "win_prob": 0.15, "make_cut": 0.95},
            ]
        }):
            preds = client.get_pre_tournament_predictions()

        assert len(preds) == 1
        assert preds[0].win_prob == 0.15
        assert preds[0].make_cut_prob == 0.95

    def test_get_live_predictions(self):
        client = self._make_client()

        with patch.object(client, "_get", return_value={
            "data": [
                {"dg_id": 18417, "player_name": "Scottie Scheffler", "position": 1, "total": -12, "thru": 14},
            ]
        }):
            entries, meta = client.get_live_predictions()

        assert len(entries) == 1
        assert entries[0].position == 1
        assert entries[0].total_score == -12

    def test_get_matchups(self):
        client = self._make_client()

        with patch.object(client, "_get", return_value={
            "2_balls": [
                {"book": "draftkings", "players": [{"dg_id": 1, "odds": -110}, {"dg_id": 2, "odds": -110}]},
            ],
            "3_balls": [],
        }):
            matchups = client.get_matchups()

        assert len(matchups) == 1
        assert matchups[0].matchup_type == "2_balls"
        assert matchups[0].book == "draftkings"

    def test_get_historical_rounds(self):
        client = self._make_client()

        with patch.object(client, "_get", return_value=[
            {"dg_id": 18417, "player_name": "Scottie Scheffler", "event_id": "026", "round_num": 1, "score": -5},
        ]):
            rounds = client.get_historical_rounds()

        assert len(rounds) == 1
        assert rounds[0].score == -5

    def test_get_historical_results(self):
        client = self._make_client()

        with patch.object(client, "_get", return_value=[
            {"dg_id": 18417, "player_name": "Scottie Scheffler", "event_id": "026",
             "event_name": "The Masters", "fin_pos": 1, "earnings": 3600000},
        ]):
            results = client.get_historical_results()

        assert len(results) == 1
        assert results[0].finish_position == 1
        assert results[0].earnings == 3600000


# ---------------------------------------------------------------------------
# Golf tasks
# ---------------------------------------------------------------------------


class TestGolfTasks:
    """Verify golf Celery tasks are importable and callable."""

    def test_tasks_importable(self):
        from sports_scraper.jobs.golf_tasks import (
            golf_sync_dfs,
            golf_sync_field,
            golf_sync_leaderboard,
            golf_sync_odds,
            golf_sync_players,
            golf_sync_schedule,
            golf_sync_stats,
        )

        # Verify they're Celery tasks with the right names
        assert golf_sync_schedule.name == "golf_sync_schedule"
        assert golf_sync_players.name == "golf_sync_players"
        assert golf_sync_field.name == "golf_sync_field"
        assert golf_sync_leaderboard.name == "golf_sync_leaderboard"
        assert golf_sync_odds.name == "golf_sync_odds"
        assert golf_sync_dfs.name == "golf_sync_dfs"
        assert golf_sync_stats.name == "golf_sync_stats"
