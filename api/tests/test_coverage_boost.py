"""Tests targeting specific uncovered lines across multiple modules.

Covers:
- lineup_weights.build_lineup_weights (lines 113-152)
- calibration/dataset.py (lines 69-143, 182, 189-190, 198-212)
- simulation_runner.py (lines 65-69, 169-228)
- _simulation_helpers.py (lines 229-284)
- live_odds_redis.py (lines 52-55, 68, 83-87, 104, 111, 116-117, 141, 157-158, 167-190)
- lineup_reconstruction.py (lines 39-114, 128-194, 216-297)
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# 1. lineup_weights.build_lineup_weights  (lines 113-152)
# ---------------------------------------------------------------------------
class TestBuildLineupWeights:
    """Cover the async build_lineup_weights function."""

    @pytest.mark.asyncio
    async def test_build_lineup_weights_happy_path(self):
        """Two-batter lineup, one resolved, one fallback."""
        db = AsyncMock()
        lineup = [
            {"external_ref": "p1", "name": "Player One"},
            {"external_ref": "p2", "name": "Player Two"},
        ]
        starter_profile = {"strikeout_rate": 0.25, "walk_rate": 0.07}
        bullpen_profile = {"strikeout_rate": 0.22, "walk_rate": 0.08}
        team_profile = {"contact_rate": 0.78, "power_index": 0.15}

        fake_weights = [0.1, 0.2, 0.3, 0.2, 0.05, 0.05, 0.1]

        with (
            patch(
                "app.analytics.services.profile_service.get_player_rolling_profile",
                new_callable=AsyncMock,
                side_effect=[{"contact_rate": 0.80}, None],
            ),
            patch(
                "app.analytics.sports.mlb.matchup.MLBMatchup",
            ) as mock_matchup_cls,
            patch(
                "app.analytics.sports.mlb.game_simulator._build_weights",
                return_value=fake_weights,
            ),
        ):
            mock_matchup_cls.return_value.batter_vs_pitcher.return_value = {
                "strikeout_probability": 0.2,
            }

            from app.analytics.services.lineup_weights import build_lineup_weights

            result = await build_lineup_weights(
                db,
                lineup,
                team_id=1,
                opposing_starter_profile=starter_profile,
                opposing_bullpen_profile=bullpen_profile,
                team_profile=team_profile,
            )

        assert result["batters_resolved"] == 1
        assert len(result["starter_weights"]) == 2
        assert len(result["bullpen_weights"]) == 2

    @pytest.mark.asyncio
    async def test_build_lineup_weights_empty_lineup(self):
        """Empty lineup returns empty weight lists."""
        db = AsyncMock()

        with (
            patch(
                "app.analytics.services.profile_service.get_player_rolling_profile",
                new_callable=AsyncMock,
            ),
            patch("app.analytics.sports.mlb.matchup.MLBMatchup"),
            patch("app.analytics.sports.mlb.game_simulator._build_weights"),
        ):
            from app.analytics.services.lineup_weights import build_lineup_weights

            result = await build_lineup_weights(
                db,
                lineup=[],
                team_id=1,
                opposing_starter_profile={},
                opposing_bullpen_profile={},
                team_profile=None,
            )

        assert result["starter_weights"] == []
        assert result["bullpen_weights"] == []
        assert result["batters_resolved"] == 0

    @pytest.mark.asyncio
    async def test_build_lineup_weights_no_ext_ref(self):
        """Batter without external_ref skips profile lookup, uses team fallback."""
        db = AsyncMock()
        lineup = [{"external_ref": "", "name": "Unknown"}]
        fake_weights = [0.1, 0.2, 0.3, 0.2, 0.05, 0.05, 0.1]

        with (
            patch(
                "app.analytics.services.profile_service.get_player_rolling_profile",
                new_callable=AsyncMock,
            ) as mock_get,
            patch("app.analytics.sports.mlb.matchup.MLBMatchup") as mock_m,
            patch(
                "app.analytics.sports.mlb.game_simulator._build_weights",
                return_value=fake_weights,
            ),
        ):
            mock_m.return_value.batter_vs_pitcher.return_value = {}

            from app.analytics.services.lineup_weights import build_lineup_weights

            result = await build_lineup_weights(
                db,
                lineup,
                team_id=1,
                opposing_starter_profile={},
                opposing_bullpen_profile={},
                team_profile={"contact_rate": 0.75},
            )

        # ext_ref is empty -> profile lookup not called
        mock_get.assert_not_called()
        assert result["batters_resolved"] == 0


# ---------------------------------------------------------------------------
# 2. calibration/dataset.py  (lines 69-143, 182, 189-190, 198-212)
# ---------------------------------------------------------------------------
class TestDeVigClosingLines:
    """Cover _devig_closing_lines helper (pure function, no DB)."""

    def test_less_than_two_lines(self):
        from app.analytics.calibration.dataset import _devig_closing_lines

        assert _devig_closing_lines([], "NYY", "BOS", None, None) is None
        assert (
            _devig_closing_lines([("NYY", -150)], "NYY", "BOS", None, None) is None
        )

    def test_matched_teams(self):
        from app.analytics.calibration.dataset import _devig_closing_lines

        remove_vig = lambda probs: [p / sum(probs) for p in probs]  # noqa: E731
        american_to_implied = (  # noqa: E731
            lambda x: 100 / (x + 100) if x > 0 else -x / (-x + 100)
        )

        result = _devig_closing_lines(
            [("NYY", -150), ("BOS", 130)],
            "NYY",
            "BOS",
            remove_vig,
            american_to_implied,
        )
        assert result is not None
        assert 0 < result < 1

    def test_unmatched_teams_fallback(self):
        """When team names don't match selections, use positional fallback."""
        from app.analytics.calibration.dataset import _devig_closing_lines

        remove_vig = lambda probs: [p / sum(probs) for p in probs]  # noqa: E731
        american_to_implied = (  # noqa: E731
            lambda x: 100 / (x + 100) if x > 0 else -x / (-x + 100)
        )

        result = _devig_closing_lines(
            [("Team A", -150), ("Team B", 130)],
            "NYY",
            "BOS",
            remove_vig,
            american_to_implied,
        )
        assert result is not None

    def test_value_error_returns_none(self):
        from app.analytics.calibration.dataset import _devig_closing_lines

        def bad_implied(x):
            raise ValueError("bad")

        result = _devig_closing_lines(
            [("NYY", -150), ("BOS", 130)],
            "NYY",
            "BOS",
            lambda x: x,
            bad_implied,
        )
        assert result is None

    def test_zero_division_returns_none(self):
        from app.analytics.calibration.dataset import _devig_closing_lines

        def bad_vig(probs):
            raise ZeroDivisionError("oops")

        result = _devig_closing_lines(
            [("NYY", -150), ("BOS", 130)],
            "NYY",
            "BOS",
            bad_vig,
            lambda x: 0.5,
        )
        assert result is None


class TestBuildCalibrationDataset:
    """Cover build_calibration_dataset and get_dataset_stats."""

    @staticmethod
    def _make_pred(game_id, home, away, wp, brier, game_date="2025-06-01"):
        return SimpleNamespace(
            game_id=game_id,
            game_date=game_date,
            home_team=home,
            away_team=away,
            predicted_home_wp=wp,
            sim_wp_std_dev=0.01,
            sim_iterations=1000,
            home_win_actual=True,
            brier_score=brier,
        )

    @staticmethod
    def _make_closing_line(game_id, selection, price):
        return SimpleNamespace(
            game_id=game_id,
            selection=selection,
            price_american=price,
        )

    @pytest.mark.asyncio
    async def test_build_calibration_dataset_with_predictions(self):
        pred = self._make_pred(1, "NYY", "BOS", 0.6, 0.16)
        cl1 = self._make_closing_line(1, "NYY", -150)
        cl2 = self._make_closing_line(1, "BOS", 130)

        mock_db = AsyncMock()
        pred_result = MagicMock()
        pred_result.scalars.return_value.all.return_value = [pred]
        cl_result = MagicMock()
        cl_result.scalars.return_value.all.return_value = [cl1, cl2]
        mock_db.execute = AsyncMock(side_effect=[pred_result, cl_result])

        with (
            patch("app.analytics.calibration.dataset.select"),
            patch(
                "app.services.ev.american_to_implied",
                side_effect=lambda x: (
                    100 / (x + 100) if x > 0 else -x / (-x + 100)
                ),
            ),
            patch(
                "app.services.ev.remove_vig",
                side_effect=lambda probs: [p / sum(probs) for p in probs],
            ),
        ):
            from app.analytics.calibration.dataset import build_calibration_dataset

            rows = await build_calibration_dataset(mock_db, "mlb")

        assert len(rows) == 1
        assert rows[0].game_id == 1
        assert rows[0].actual_home_win is True

    @pytest.mark.asyncio
    async def test_build_calibration_dataset_empty(self):
        mock_db = AsyncMock()
        pred_result = MagicMock()
        pred_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=pred_result)

        with patch("app.analytics.calibration.dataset.select"):
            from app.analytics.calibration.dataset import build_calibration_dataset

            rows = await build_calibration_dataset(mock_db, "mlb")

        assert rows == []

    @pytest.mark.asyncio
    async def test_require_market_filters_rows(self):
        pred = self._make_pred(1, "NYY", "BOS", 0.6, 0.16)

        mock_db = AsyncMock()
        pred_result = MagicMock()
        pred_result.scalars.return_value.all.return_value = [pred]
        cl_result = MagicMock()
        cl_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(side_effect=[pred_result, cl_result])

        with patch("app.analytics.calibration.dataset.select"):
            from app.analytics.calibration.dataset import build_calibration_dataset

            rows = await build_calibration_dataset(
                mock_db, "mlb", require_market=True
            )

        assert rows == []

    @pytest.mark.asyncio
    async def test_get_dataset_stats_empty(self):
        with patch(
            "app.analytics.calibration.dataset.build_calibration_dataset",
            new_callable=AsyncMock,
            return_value=[],
        ):
            from app.analytics.calibration.dataset import get_dataset_stats

            stats = await get_dataset_stats(AsyncMock(), "mlb")

        assert stats.total_predictions == 0
        assert stats.coverage_pct == 0.0
        assert stats.date_range is None

    @pytest.mark.asyncio
    async def test_get_dataset_stats_with_data(self):
        from app.analytics.calibration.dataset import CalibrationRow

        rows = [
            CalibrationRow(
                game_id=1,
                game_date="2025-06-01",
                home_team="NYY",
                away_team="BOS",
                sim_home_wp=0.6,
                sim_wp_std_dev=0.01,
                sim_iterations=1000,
                market_close_home_wp=0.55,
                actual_home_win=True,
                brier_score=0.16,
            ),
            CalibrationRow(
                game_id=2,
                game_date="2025-06-02",
                home_team="LAD",
                away_team="SF",
                sim_home_wp=0.7,
                sim_wp_std_dev=0.02,
                sim_iterations=1000,
                market_close_home_wp=None,
                actual_home_win=False,
                brier_score=0.49,
            ),
        ]

        with patch(
            "app.analytics.calibration.dataset.build_calibration_dataset",
            new_callable=AsyncMock,
            return_value=rows,
        ):
            from app.analytics.calibration.dataset import get_dataset_stats

            stats = await get_dataset_stats(AsyncMock(), "mlb")

        assert stats.total_predictions == 2
        assert stats.with_market_data == 1
        assert stats.without_market_data == 1
        assert stats.date_range == ("2025-06-01", "2025-06-02")
        assert stats.coverage_pct == 50.0


# ---------------------------------------------------------------------------
# 3. simulation_runner.py  (lines 65-69, 169-228)
# ---------------------------------------------------------------------------
class TestSimulationRunnerLineup:
    """Cover use_lineup=True branch and _aggregate_events."""

    def test_use_lineup_raises_without_method(self):
        from app.analytics.core.simulation_runner import SimulationRunner

        runner = SimulationRunner()
        sim = MagicMock(spec=[])

        with pytest.raises(RuntimeError, match="does not support lineup-aware"):
            runner.run_simulations(sim, {}, iterations=1, use_lineup=True)

    def test_use_lineup_calls_correct_method(self):
        from app.analytics.core.simulation_runner import SimulationRunner

        runner = SimulationRunner()
        sim = MagicMock()
        sim.simulate_game_with_lineups.return_value = {
            "home_score": 5,
            "away_score": 3,
            "winner": "home",
        }

        result = runner.run_simulations(
            sim, {}, iterations=3, seed=42, use_lineup=True
        )

        assert sim.simulate_game_with_lineups.call_count == 3
        assert result["iterations"] == 3

    def test_aggregate_events_private_method(self):
        """Cover _aggregate_events (lines 169-228)."""
        from app.analytics.core.simulation_runner import SimulationRunner

        runner = SimulationRunner()
        sim_results = [
            {
                "home_score": 5,
                "away_score": 3,
                "winner": "home",
                "home_events": {
                    "pa_total": 35,
                    "single": 5,
                    "double": 2,
                    "triple": 0,
                    "home_run": 2,
                    "strikeout": 8,
                    "walk_or_hbp": 3,
                    "ball_in_play_out": 15,
                },
                "away_events": {
                    "pa_total": 33,
                    "single": 4,
                    "double": 1,
                    "triple": 1,
                    "home_run": 1,
                    "strikeout": 10,
                    "walk": 2,
                    "out": 14,
                },
                "innings_played": 9,
            },
            {
                "home_score": 0,
                "away_score": 2,
                "winner": "away",
                "home_events": {
                    "pa_total": 30,
                    "single": 3,
                    "double": 1,
                    "triple": 0,
                    "home_run": 0,
                    "strikeout": 9,
                    "walk_or_hbp": 2,
                    "ball_in_play_out": 15,
                },
                "away_events": {
                    "pa_total": 32,
                    "single": 5,
                    "double": 2,
                    "triple": 0,
                    "home_run": 1,
                    "strikeout": 7,
                    "walk": 3,
                    "out": 14,
                },
                "innings_played": 10,
            },
        ]

        result = runner._aggregate_events(sim_results)

        assert "home" in result
        assert "away" in result
        assert "game" in result

        assert result["game"]["avg_total_runs"] > 0
        assert result["game"]["extra_innings_pct"] == 0.5
        assert result["game"]["shutout_pct"] == 0.5
        assert result["game"]["one_run_game_pct"] == 0.0

        assert result["home"]["avg_pa"] > 0
        assert "pa_rates" in result["home"]
        assert result["away"]["avg_pa"] > 0

    def test_aggregate_events_one_run_games(self):
        from app.analytics.core.simulation_runner import SimulationRunner

        runner = SimulationRunner()
        sim_results = [
            {
                "home_score": 3,
                "away_score": 2,
                "winner": "home",
                "home_events": {
                    "pa_total": 30,
                    "single": 3,
                    "double": 0,
                    "triple": 0,
                    "home_run": 1,
                    "strikeout": 7,
                    "walk_or_hbp": 2,
                    "ball_in_play_out": 17,
                },
                "away_events": {
                    "pa_total": 30,
                    "single": 2,
                    "double": 0,
                    "triple": 0,
                    "home_run": 1,
                    "strikeout": 8,
                    "walk": 1,
                    "out": 18,
                },
                "innings_played": 9,
            },
        ]
        result = runner._aggregate_events(sim_results)
        assert result["game"]["one_run_game_pct"] == 1.0


# ---------------------------------------------------------------------------
# 4. _simulation_helpers.py  (lines 229-284)
# ---------------------------------------------------------------------------
class TestPredictWithGameModel:
    """Cover _predict_with_game_model function."""

    @pytest.mark.asyncio
    async def test_no_completed_model(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        from app.analytics.api._simulation_helpers import _predict_with_game_model

        result = await _predict_with_game_model(
            "mlb", {"contact_rate": 0.78}, {"contact_rate": 0.75}, mock_db
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_model_found_and_predicts(self):
        job = SimpleNamespace(
            feature_names=["f1", "f2"],
            artifact_path="/tmp/fake_model.pkl",
        )
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = job
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_model = MagicMock()
        mock_model.classes_ = [0, 1]
        mock_model.predict_proba.return_value = [[0.35, 0.65]]

        mock_vec = MagicMock()
        mock_vec.to_array.return_value = [1.0, 2.0]

        mock_builder = MagicMock()
        mock_builder.build_game_features.return_value = mock_vec

        with (
            patch(
                "app.analytics.features.sports.mlb_features.MLBFeatureBuilder",
                return_value=mock_builder,
            ),
            patch("pathlib.Path") as mock_path,
            patch("joblib.load", return_value=mock_model),
            patch("numpy.array", return_value=[[1.0, 2.0]]),
        ):
            mock_path.return_value.exists.return_value = True

            from app.analytics.api._simulation_helpers import (
                _predict_with_game_model,
            )

            result = await _predict_with_game_model(
                "mlb",
                {"contact_rate": 0.78},
                {"contact_rate": 0.75},
                mock_db,
            )

        assert result == 0.65

    @pytest.mark.asyncio
    async def test_model_empty_feature_array(self):
        job = SimpleNamespace(feature_names=["f1"], artifact_path=None)
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = job
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_vec = MagicMock()
        mock_vec.to_array.return_value = []

        mock_builder = MagicMock()
        mock_builder.build_game_features.return_value = mock_vec

        with patch(
            "app.analytics.features.sports.mlb_features.MLBFeatureBuilder",
            return_value=mock_builder,
        ):
            from app.analytics.api._simulation_helpers import (
                _predict_with_game_model,
            )

            result = await _predict_with_game_model("mlb", {}, {}, mock_db)

        assert result is None

    @pytest.mark.asyncio
    async def test_model_exception_returns_none(self):
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=Exception("DB error"))

        from app.analytics.api._simulation_helpers import _predict_with_game_model

        result = await _predict_with_game_model("mlb", {}, {}, mock_db)
        assert result is None

    @pytest.mark.asyncio
    async def test_model_no_feature_names(self):
        """Job exists but feature_names is empty/None."""
        job = SimpleNamespace(feature_names=None, artifact_path=None)
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = job
        mock_db.execute = AsyncMock(return_value=mock_result)

        from app.analytics.api._simulation_helpers import _predict_with_game_model

        result = await _predict_with_game_model("mlb", {}, {}, mock_db)
        assert result is None


# ---------------------------------------------------------------------------
# 5. live_odds_redis.py
# ---------------------------------------------------------------------------
class TestLiveOddsRedis:
    """Cover the Redis live odds reader functions."""

    def setup_method(self):
        """Reset circuit breaker state before each test."""
        import app.services.live_odds_redis as mod

        mod._redis_error_until = 0.0

    def test_get_redis(self):
        import app.services.live_odds_redis as mod

        mock_redis_mod = MagicMock()
        mock_settings = MagicMock()
        mock_settings.celery_broker = "redis://localhost:6379/2"

        with (
            patch.dict("sys.modules", {"redis": mock_redis_mod}),
            patch("app.config.settings", mock_settings),
        ):
            mod._get_redis()
            mock_redis_mod.from_url.assert_called_once_with(
                "redis://localhost:6379/2", decode_responses=True
            )

    def test_read_live_snapshot_circuit_open(self):
        import app.services.live_odds_redis as mod

        mod._redis_error_until = time.time() + 100

        data, err = mod.read_live_snapshot("mlb", 123, "h2h")
        assert data is None
        assert err == "redis_circuit_open"

    def test_read_live_snapshot_redis_error(self):
        import app.services.live_odds_redis as mod

        with patch.object(mod, "_get_redis", side_effect=Exception("conn refused")):
            data, err = mod.read_live_snapshot("mlb", 123, "h2h")

        assert data is None
        assert "redis_error" in err
        assert mod._redis_error_until > time.time()

    def test_read_live_snapshot_json_error(self):
        import app.services.live_odds_redis as mod

        mock_r = MagicMock()
        mock_r.get.return_value = "not valid json{{"

        with patch.object(mod, "_get_redis", return_value=mock_r):
            data, err = mod.read_live_snapshot("mlb", 123, "h2h")

        assert data is None
        assert "json_error" in err

    def test_read_live_snapshot_success(self):
        import app.services.live_odds_redis as mod

        payload = {"odds": [{"book": "DK", "price": -110}]}
        mock_r = MagicMock()
        mock_r.get.return_value = json.dumps(payload)
        mock_r.ttl.return_value = 120

        with patch.object(mod, "_get_redis", return_value=mock_r):
            data, err = mod.read_live_snapshot("mlb", 123, "h2h")

        assert err is None
        assert data["odds"] == [{"book": "DK", "price": -110}]
        assert data["ttl_seconds_remaining"] == 120

    def test_read_live_snapshot_no_data(self):
        import app.services.live_odds_redis as mod

        mock_r = MagicMock()
        mock_r.get.return_value = None

        with patch.object(mod, "_get_redis", return_value=mock_r):
            data, err = mod.read_live_snapshot("mlb", 123, "h2h")

        assert data is None
        assert err is None

    def test_read_all_live_snapshots_circuit_open(self):
        import app.services.live_odds_redis as mod

        mod._redis_error_until = time.time() + 100

        result, err = mod.read_all_live_snapshots_for_game("mlb", 123)
        assert result == {}
        assert err == "redis_circuit_open"

    def test_read_all_live_snapshots_success(self):
        import app.services.live_odds_redis as mod

        payload = json.dumps({"odds": []})
        mock_r = MagicMock()
        mock_r.scan_iter.return_value = [
            "live:odds:mlb:123:h2h",
            "live:odds:mlb:123:spreads",
            "live:odds:history:123:h2h",
        ]
        mock_r.get.return_value = payload
        mock_r.ttl.return_value = 60

        with patch.object(mod, "_get_redis", return_value=mock_r):
            result, err = mod.read_all_live_snapshots_for_game("mlb", 123)

        assert err is None
        assert "h2h" in result
        assert "spreads" in result
        assert len(result) == 2

    def test_read_all_live_snapshots_bad_json_skipped(self):
        import app.services.live_odds_redis as mod

        mock_r = MagicMock()
        mock_r.scan_iter.return_value = ["live:odds:mlb:123:h2h"]
        mock_r.get.return_value = "BAD JSON"

        with patch.object(mod, "_get_redis", return_value=mock_r):
            result, err = mod.read_all_live_snapshots_for_game("mlb", 123)

        assert err is None
        assert result == {}

    def test_read_all_live_snapshots_redis_error(self):
        import app.services.live_odds_redis as mod

        with patch.object(mod, "_get_redis", side_effect=Exception("conn")):
            result, err = mod.read_all_live_snapshots_for_game("mlb", 123)

        assert result == {}
        assert "redis_error" in err

    def test_read_live_history_circuit_open(self):
        import app.services.live_odds_redis as mod

        mod._redis_error_until = time.time() + 100

        entries, err = mod.read_live_history(123, "h2h")
        assert entries == []
        assert err == "redis_circuit_open"

    def test_read_live_history_success(self):
        import app.services.live_odds_redis as mod

        mock_r = MagicMock()
        mock_r.lrange.return_value = [
            json.dumps({"ts": 1, "odds": -110}),
            "bad json",
            json.dumps({"ts": 2, "odds": -105}),
        ]

        with patch.object(mod, "_get_redis", return_value=mock_r):
            entries, err = mod.read_live_history(123, "h2h")

        assert err is None
        assert len(entries) == 2

    def test_read_live_history_redis_error(self):
        import app.services.live_odds_redis as mod

        with patch.object(mod, "_get_redis", side_effect=Exception("fail")):
            entries, err = mod.read_live_history(123, "h2h")

        assert entries == []
        assert "redis_error" in err

    def test_discover_live_game_ids_circuit_open(self):
        import app.services.live_odds_redis as mod

        mod._redis_error_until = time.time() + 100

        result = mod.discover_live_game_ids()
        assert result == []

    def test_discover_live_game_ids_success(self):
        import app.services.live_odds_redis as mod

        mock_r = MagicMock()
        mock_r.scan_iter.return_value = [
            "live:odds:mlb:100:h2h",
            "live:odds:mlb:100:spreads",
            "live:odds:nba:200:h2h",
            "live:odds:history:100:h2h",
            "live:odds:mlb:bad:h2h",
        ]

        with patch.object(mod, "_get_redis", return_value=mock_r):
            result = mod.discover_live_game_ids()

        assert ("mlb", 100) in result
        assert ("nba", 200) in result
        assert len(result) == 2

    def test_discover_live_game_ids_with_league_filter(self):
        import app.services.live_odds_redis as mod

        mock_r = MagicMock()
        mock_r.scan_iter.return_value = [
            "live:odds:mlb:100:h2h",
        ]

        with patch.object(mod, "_get_redis", return_value=mock_r):
            result = mod.discover_live_game_ids(league="mlb")

        assert result == [("mlb", 100)]

    def test_discover_live_game_ids_redis_error(self):
        import app.services.live_odds_redis as mod

        with patch.object(mod, "_get_redis", side_effect=Exception("fail")):
            result = mod.discover_live_game_ids()

        assert result == []

    def test_discover_short_key_ignored(self):
        """Keys with < 5 parts are silently skipped."""
        import app.services.live_odds_redis as mod

        mock_r = MagicMock()
        mock_r.scan_iter.return_value = ["live:odds:mlb:short"]

        with patch.object(mod, "_get_redis", return_value=mock_r):
            result = mod.discover_live_game_ids()

        assert result == []


# ---------------------------------------------------------------------------
# 6. lineup_reconstruction.py  (lines 39-114, 128-194, 216-297)
# ---------------------------------------------------------------------------
class TestReconstructLineupFromPBP:
    """Cover reconstruct_lineup_from_pbp."""

    @staticmethod
    def _make_play(player_id, player_name, batter_info=None, event="Single"):
        return SimpleNamespace(
            play_index=0,
            player_id=player_id,
            player_name=player_name,
            raw_data={
                "matchup": {"batter": batter_info or {}},
                "event": event,
            },
        )

    @pytest.mark.asyncio
    async def test_reconstruct_from_pbp_happy_path(self):
        """9 unique batters extracted in order."""
        plays = []
        for i in range(1, 12):
            batter_id = str(i) if i <= 9 else "1"
            plays.append(
                self._make_play(
                    player_id=batter_id,
                    player_name=f"Player {batter_id}",
                    batter_info={
                        "id": int(batter_id),
                        "fullName": f"Player {batter_id}",
                    },
                )
            )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = plays
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.analytics.services.lineup_reconstruction.select"):
            from app.analytics.services.lineup_reconstruction import (
                reconstruct_lineup_from_pbp,
            )

            result = await reconstruct_lineup_from_pbp(mock_db, 1, 1)

        assert result is not None
        assert len(result["batters"]) == 9

    @pytest.mark.asyncio
    async def test_reconstruct_no_plays_fallback(self):
        """No PBP data -> falls back to boxscore."""
        mock_db = AsyncMock()
        empty_result = MagicMock()
        empty_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=empty_result)

        with patch("app.analytics.services.lineup_reconstruction.select"):
            from app.analytics.services.lineup_reconstruction import (
                reconstruct_lineup_from_pbp,
            )

            result = await reconstruct_lineup_from_pbp(mock_db, 1, 1)

        assert result is None

    @pytest.mark.asyncio
    async def test_reconstruct_fewer_than_3_batters_fallback(self):
        """If only 2 unique batters from PBP, falls back to boxscore."""
        plays = [
            self._make_play("1", "P1", {"id": 1, "fullName": "P1"}),
            self._make_play("2", "P2", {"id": 2, "fullName": "P2"}),
        ]

        mock_db = AsyncMock()
        play_result = MagicMock()
        play_result.scalars.return_value.all.return_value = plays
        empty_result = MagicMock()
        empty_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(side_effect=[play_result, empty_result])

        with patch("app.analytics.services.lineup_reconstruction.select"):
            from app.analytics.services.lineup_reconstruction import (
                reconstruct_lineup_from_pbp,
            )

            result = await reconstruct_lineup_from_pbp(mock_db, 1, 1)

        assert result is None

    @pytest.mark.asyncio
    async def test_reconstruct_partial_lineup(self):
        """Between 3 and 9 batters still returns partial result."""
        plays = [
            self._make_play(str(i), f"P{i}", {"id": i, "fullName": f"P{i}"})
            for i in range(1, 6)
        ]

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = plays
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.analytics.services.lineup_reconstruction.select"):
            from app.analytics.services.lineup_reconstruction import (
                reconstruct_lineup_from_pbp,
            )

            result = await reconstruct_lineup_from_pbp(mock_db, 1, 1)

        assert result is not None
        assert len(result["batters"]) == 5

    @pytest.mark.asyncio
    async def test_reconstruct_skips_plays_without_event(self):
        """Plays without event result are skipped."""
        plays = [
            self._make_play(
                "1", "P1", {"id": 1, "fullName": "P1"}, event=""
            ),
            self._make_play(
                "1", "P1", {"id": 1, "fullName": "P1"}, event="Single"
            ),
        ]
        for i in range(2, 10):
            plays.append(
                self._make_play(
                    str(i), f"P{i}", {"id": i, "fullName": f"P{i}"}, event="Out"
                )
            )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = plays
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.analytics.services.lineup_reconstruction.select"):
            from app.analytics.services.lineup_reconstruction import (
                reconstruct_lineup_from_pbp,
            )

            result = await reconstruct_lineup_from_pbp(mock_db, 1, 1)

        assert result is not None
        assert len(result["batters"]) == 9

    @pytest.mark.asyncio
    async def test_reconstruct_fallback_to_player_id_fields(self):
        """When matchup.batter is empty, falls back to play.player_id."""
        plays = [
            SimpleNamespace(
                play_index=0,
                player_id="99",
                player_name="Fallback Guy",
                raw_data={"matchup": {"batter": {}}, "event": "Single"},
            ),
        ]
        for i in range(2, 10):
            plays.append(
                SimpleNamespace(
                    play_index=i,
                    player_id=str(i),
                    player_name=f"P{i}",
                    raw_data={"matchup": {"batter": {}}, "event": "Out"},
                )
            )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = plays
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.analytics.services.lineup_reconstruction.select"):
            from app.analytics.services.lineup_reconstruction import (
                reconstruct_lineup_from_pbp,
            )

            result = await reconstruct_lineup_from_pbp(mock_db, 1, 1)

        assert result is not None
        assert result["batters"][0]["external_ref"] == "99"
        assert result["batters"][0]["name"] == "Fallback Guy"


class TestLineupFromBoxscores:
    """Cover _lineup_from_boxscores fallback."""

    @staticmethod
    def _make_boxscore_row(
        ext_ref, name, at_bats=3, pa=4, batting_order=None
    ):
        stats = {"atBats": at_bats, "plateAppearances": pa}
        if batting_order is not None:
            stats["battingOrder"] = batting_order
        return SimpleNamespace(
            player_external_ref=ext_ref,
            player_name=name,
            stats=stats,
        )

    @pytest.mark.asyncio
    async def test_boxscore_happy_path(self):
        rows = [
            self._make_boxscore_row(
                f"p{i}", f"Player {i}", batting_order=i * 100
            )
            for i in range(1, 10)
        ]

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = rows
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.analytics.services.lineup_reconstruction.select"):
            from app.analytics.services.lineup_reconstruction import (
                _lineup_from_boxscores,
            )

            result = await _lineup_from_boxscores(mock_db, 1, 1)

        assert result is not None
        assert len(result["batters"]) == 9

    @pytest.mark.asyncio
    async def test_boxscore_no_rows(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.analytics.services.lineup_reconstruction.select"):
            from app.analytics.services.lineup_reconstruction import (
                _lineup_from_boxscores,
            )

            result = await _lineup_from_boxscores(mock_db, 1, 1)

        assert result is None

    @pytest.mark.asyncio
    async def test_boxscore_insufficient_batters(self):
        """Fewer than 3 batters returns None."""
        rows = [self._make_boxscore_row("p1", "P1")]

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = rows
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.analytics.services.lineup_reconstruction.select"):
            from app.analytics.services.lineup_reconstruction import (
                _lineup_from_boxscores,
            )

            result = await _lineup_from_boxscores(mock_db, 1, 1)

        assert result is None

    @pytest.mark.asyncio
    async def test_boxscore_sort_by_at_bats_when_no_order(self):
        """Without battingOrder, sorts by at-bats descending."""
        rows = [
            self._make_boxscore_row("p1", "P1", at_bats=1, pa=2),
            self._make_boxscore_row("p2", "P2", at_bats=5, pa=6),
            self._make_boxscore_row("p3", "P3", at_bats=3, pa=4),
        ]

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = rows
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.analytics.services.lineup_reconstruction.select"):
            from app.analytics.services.lineup_reconstruction import (
                _lineup_from_boxscores,
            )

            result = await _lineup_from_boxscores(mock_db, 1, 1)

        assert result is not None
        assert result["batters"][0]["external_ref"] == "p2"

    @pytest.mark.asyncio
    async def test_boxscore_filters_non_batters(self):
        """Players with 0 AB and 0 PA are filtered out."""
        rows = [
            self._make_boxscore_row("p1", "P1", at_bats=3, pa=4),
            self._make_boxscore_row("p2", "Pitcher", at_bats=0, pa=0),
            self._make_boxscore_row("p3", "P3", at_bats=2, pa=3),
            self._make_boxscore_row("p4", "P4", at_bats=4, pa=5),
        ]

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = rows
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.analytics.services.lineup_reconstruction.select"):
            from app.analytics.services.lineup_reconstruction import (
                _lineup_from_boxscores,
            )

            result = await _lineup_from_boxscores(mock_db, 1, 1)

        assert result is not None
        refs = [b["external_ref"] for b in result["batters"]]
        assert "p2" not in refs


class TestGetStartingPitcher:
    """Cover get_starting_pitcher with its multiple fallback layers."""

    @pytest.mark.asyncio
    async def test_starter_found_via_is_starter(self):
        starter = SimpleNamespace(
            player_external_ref="sp1",
            player_name="Ace Pitcher",
            innings_pitched=6.0,
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = starter
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.analytics.services.lineup_reconstruction.select"):
            from app.analytics.services.lineup_reconstruction import (
                get_starting_pitcher,
            )

            result = await get_starting_pitcher(mock_db, 1, 1)

        assert result is not None
        assert result["external_ref"] == "sp1"
        assert result["avg_ip"] == 6.0

    @pytest.mark.asyncio
    async def test_fallback_to_most_innings(self):
        pitcher = SimpleNamespace(
            player_external_ref="sp2",
            player_name="Reliever Guy",
            innings_pitched=4.0,
        )

        mock_db = AsyncMock()
        no_starter = MagicMock()
        no_starter.scalar_one_or_none.return_value = None
        found = MagicMock()
        found.scalar_one_or_none.return_value = pitcher
        mock_db.execute = AsyncMock(side_effect=[no_starter, found])

        with patch("app.analytics.services.lineup_reconstruction.select"):
            from app.analytics.services.lineup_reconstruction import (
                get_starting_pitcher,
            )

            result = await get_starting_pitcher(mock_db, 1, 1)

        assert result is not None
        assert result["external_ref"] == "sp2"

    @pytest.mark.asyncio
    async def test_fallback_to_boxscore(self):
        """No MLBPitcherGameStats -> uses boxscore fallback."""
        box_row = SimpleNamespace(
            player_external_ref="sp3",
            player_name="Boxscore Pitcher",
            stats={"inningsPitched": "5.2"},
        )

        mock_db = AsyncMock()
        no_starter = MagicMock()
        no_starter.scalar_one_or_none.return_value = None
        no_pitcher = MagicMock()
        no_pitcher.scalar_one_or_none.return_value = None
        box_result = MagicMock()
        box_result.scalars.return_value.all.return_value = [box_row]
        mock_db.execute = AsyncMock(
            side_effect=[no_starter, no_pitcher, box_result]
        )

        with patch("app.analytics.services.lineup_reconstruction.select"):
            from app.analytics.services.lineup_reconstruction import (
                get_starting_pitcher,
            )

            result = await get_starting_pitcher(mock_db, 1, 1)

        assert result is not None
        assert result["external_ref"] == "sp3"
        assert result["avg_ip"] == 5.2

    @pytest.mark.asyncio
    async def test_all_fallbacks_exhausted(self):
        """No data anywhere -> returns None."""
        mock_db = AsyncMock()
        no_result = MagicMock()
        no_result.scalar_one_or_none.return_value = None
        empty_box = MagicMock()
        empty_box.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(
            side_effect=[no_result, no_result, empty_box]
        )

        with patch("app.analytics.services.lineup_reconstruction.select"):
            from app.analytics.services.lineup_reconstruction import (
                get_starting_pitcher,
            )

            result = await get_starting_pitcher(mock_db, 1, 1)

        assert result is None

    @pytest.mark.asyncio
    async def test_boxscore_bad_ip_value_skipped(self):
        """Non-numeric inningsPitched in boxscore is skipped."""
        box_row_bad = SimpleNamespace(
            player_external_ref="bad",
            player_name="Bad IP",
            stats={"inningsPitched": "not-a-number"},
        )
        box_row_good = SimpleNamespace(
            player_external_ref="sp4",
            player_name="Good IP",
            stats={"inningsPitched": "3.0"},
        )

        mock_db = AsyncMock()
        no_result = MagicMock()
        no_result.scalar_one_or_none.return_value = None
        box_result = MagicMock()
        box_result.scalars.return_value.all.return_value = [
            box_row_bad,
            box_row_good,
        ]
        mock_db.execute = AsyncMock(
            side_effect=[no_result, no_result, box_result]
        )

        with patch("app.analytics.services.lineup_reconstruction.select"):
            from app.analytics.services.lineup_reconstruction import (
                get_starting_pitcher,
            )

            result = await get_starting_pitcher(mock_db, 1, 1)

        assert result is not None
        assert result["external_ref"] == "sp4"

    @pytest.mark.asyncio
    async def test_boxscore_zero_ip_returns_none(self):
        """All boxscore rows have 0 IP -> returns None."""
        box_row = SimpleNamespace(
            player_external_ref="sp5",
            player_name="Zero IP",
            stats={"inningsPitched": 0},
        )

        mock_db = AsyncMock()
        no_result = MagicMock()
        no_result.scalar_one_or_none.return_value = None
        box_result = MagicMock()
        box_result.scalars.return_value.all.return_value = [box_row]
        mock_db.execute = AsyncMock(
            side_effect=[no_result, no_result, box_result]
        )

        with patch("app.analytics.services.lineup_reconstruction.select"):
            from app.analytics.services.lineup_reconstruction import (
                get_starting_pitcher,
            )

            result = await get_starting_pitcher(mock_db, 1, 1)

        assert result is None

    @pytest.mark.asyncio
    async def test_starter_with_none_innings_pitched(self):
        """is_starter found but innings_pitched is None."""
        starter = SimpleNamespace(
            player_external_ref="sp6",
            player_name="None IP Starter",
            innings_pitched=None,
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = starter
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.analytics.services.lineup_reconstruction.select"):
            from app.analytics.services.lineup_reconstruction import (
                get_starting_pitcher,
            )

            result = await get_starting_pitcher(mock_db, 1, 1)

        assert result is not None
        assert result["avg_ip"] == 0.0
