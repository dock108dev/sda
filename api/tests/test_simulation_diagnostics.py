"""Tests for SimulationDiagnostics and the diagnostics threading.

Covers:
1. ML mode + failure → error propagates (no fallback)
2. ML mode + active model → model_info populated
3. Rule-based mode → profile-derived PA probs, executed_mode="rule_based"
4. Priority: user-explicit > resolver > profile-derived
5. data_freshness populated when profiles loaded
6. validate_probabilities catches bad inputs
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from app.analytics.core.simulation_diagnostics import (
    ModelInfo,
    SimulationDiagnostics,
)

# ---------------------------------------------------------------------------
# 1. SimulationDiagnostics unit tests
# ---------------------------------------------------------------------------

class TestSimulationDiagnostics:
    """Unit tests for the SimulationDiagnostics dataclass itself."""

    def test_defaults(self):
        diag = SimulationDiagnostics(requested_mode="ml", executed_mode="ml")
        assert diag.model_info is None
        assert diag.warnings == []

    def test_to_dict_without_model(self):
        diag = SimulationDiagnostics(
            requested_mode="ml",
            executed_mode="ml",
        )
        d = diag.to_dict()
        assert d["requested_mode"] == "ml"
        assert d["executed_mode"] == "ml"
        assert d["model_info"] is None
        assert d["warnings"] == []
        assert "fallback_used" not in d
        assert "fallback_reason" not in d

    def test_to_dict_with_model_info(self):
        info = ModelInfo(
            model_id="pa-v3",
            version=3,
            trained_at="2026-03-10",
            metrics={"accuracy": 0.58, "brier_score": 0.24},
        )
        diag = SimulationDiagnostics(
            requested_mode="ml",
            executed_mode="ml",
            model_info=info,
        )
        d = diag.to_dict()
        assert d["model_info"]["model_id"] == "pa-v3"
        assert d["model_info"]["version"] == 3
        assert d["model_info"]["metrics"]["accuracy"] == 0.58

    def test_warnings_accumulate(self):
        diag = SimulationDiagnostics(requested_mode="ml", executed_mode="ml")
        diag.warnings.append("sum_not_one:0.9500")
        diag.warnings.append("missing_event:triple")
        d = diag.to_dict()
        assert len(d["warnings"]) == 2


# ---------------------------------------------------------------------------
# 2. _apply_probability_resolver diagnostics threading
# ---------------------------------------------------------------------------

class TestApplyProbabilityResolver:
    """Tests for SimulationEngine._apply_probability_resolver diagnostics."""

    def _make_engine(self):
        from app.analytics.core.simulation_engine import SimulationEngine
        return SimulationEngine("mlb")

    @patch("app.analytics.probabilities.probability_resolver.ProbabilityResolver")
    def test_ml_failure_raises(self, MockResolver):
        """ML mode failure should raise — no silent fallback."""
        instance = MockResolver.return_value
        instance.get_probabilities_with_meta.side_effect = RuntimeError(
            "ML probability provider failed"
        )

        engine = self._make_engine()
        ctx = {"profiles": {}}
        with pytest.raises(RuntimeError, match="ML probability provider failed"):
            engine._apply_probability_resolver(ctx, "ml", "plate_appearance")

    @patch("app.analytics.probabilities.probability_resolver.ProbabilityResolver")
    def test_ml_with_active_model(self, MockResolver):
        """ML mode + active model → model_info populated."""
        instance = MockResolver.return_value
        instance.get_probabilities_with_meta.return_value = {
            "strikeout": 0.22, "walk": 0.08, "single": 0.18,
            "double": 0.05, "triple": 0.01, "home_run": 0.03,
            "_meta": {
                "probability_source": "ml",
                "model_type": "plate_appearance",
                "requested_mode": "ml",
                "executed_mode": "ml",
                "model_info": {
                    "model_id": "pa-v5",
                    "version": 5,
                    "trained_at": "2026-03-09",
                    "metrics": {"accuracy": 0.61},
                },
            },
        }

        engine = self._make_engine()
        ctx = {"profiles": {}}
        ctx, meta = engine._apply_probability_resolver(ctx, "ml", "plate_appearance")

        diag = meta.get("_diagnostics")
        assert diag is not None
        assert diag.executed_mode == "ml"
        assert diag.model_info is not None
        assert diag.model_info.model_id == "pa-v5"
        assert diag.model_info.version == 5

    @patch("app.analytics.probabilities.probability_resolver.ProbabilityResolver")
    def test_rule_based_mode(self, MockResolver):
        """Rule-based mode → executed_mode='rule_based'."""
        instance = MockResolver.return_value
        instance.get_probabilities_with_meta.return_value = {
            "strikeout": 0.22, "walk": 0.08, "single": 0.18,
            "double": 0.05, "triple": 0.01, "home_run": 0.03,
            "_meta": {
                "probability_source": "rule_based",
                "model_type": "plate_appearance",
                "requested_mode": "rule_based",
                "executed_mode": "rule_based",
            },
        }

        engine = self._make_engine()
        ctx = {"profiles": {}}
        ctx, meta = engine._apply_probability_resolver(ctx, "rule_based", "plate_appearance")

        diag = meta.get("_diagnostics")
        assert diag is not None
        assert diag.executed_mode == "rule_based"

    def test_exception_in_resolver_propagates(self):
        """When the resolver throws, error propagates — no silent fallback."""
        engine = self._make_engine()
        ctx = {"profiles": {}}

        with patch(
            "app.analytics.probabilities.probability_resolver.ProbabilityResolver",
            side_effect=RuntimeError("test boom"),
        ):
            with pytest.raises(RuntimeError, match="test boom"):
                engine._apply_probability_resolver(ctx, "ml", "plate_appearance")


# ---------------------------------------------------------------------------
# 3. Priority: resolver output overwrites profile-derived PA probs
# ---------------------------------------------------------------------------

class TestPriorityBugFix:
    """The old code skipped resolver output when home_probabilities was
    already set.  Now the resolver always overwrites."""

    @patch("app.analytics.probabilities.probability_resolver.ProbabilityResolver")
    def test_resolver_overwrites_profile_probs(self, MockResolver):
        """Resolver output replaces pre-existing home/away probabilities."""
        from app.analytics.core.simulation_engine import SimulationEngine

        instance = MockResolver.return_value
        instance.get_probabilities_with_meta.return_value = {
            "strikeout": 0.30, "walk": 0.10, "single": 0.15,
            "double": 0.04, "triple": 0.01, "home_run": 0.04,
            "_meta": {
                "probability_source": "ml",
                "model_type": "plate_appearance",
                "requested_mode": "ml",
                "executed_mode": "ml",
            },
        }

        engine = SimulationEngine("mlb")
        ctx = {
            "profiles": {},
            # Pre-set by profile_to_pa_probabilities in analytics_routes
            "home_probabilities": {"strikeout_probability": 0.20},
            "away_probabilities": {"strikeout_probability": 0.20},
        }
        ctx, _meta = engine._apply_probability_resolver(ctx, "ml", "plate_appearance")

        # Resolver should have overwritten the profile-derived values
        assert ctx["home_probabilities"]["strikeout_probability"] == 0.30
        assert ctx["away_probabilities"]["strikeout_probability"] == 0.30


# ---------------------------------------------------------------------------
# 4. validate_probabilities integration
# ---------------------------------------------------------------------------

class TestValidateProbabilities:
    """validate_probabilities catches bad inputs and adds warnings."""

    def test_valid_probs(self):
        from app.analytics.probabilities.probability_provider import (
            validate_probabilities,
        )
        probs = {
            "strikeout_probability": 0.22,
            "walk_or_hbp_probability": 0.08,
            "single_probability": 0.18,
            "double_probability": 0.05,
            "triple_probability": 0.01,
            "home_run_probability": 0.03,
            "ball_in_play_out_probability": 0.43,
        }
        issues = validate_probabilities(probs)
        assert issues == []

    def test_empty_probs(self):
        from app.analytics.probabilities.probability_provider import (
            validate_probabilities,
        )
        issues = validate_probabilities({})
        assert "empty_probabilities" in issues

    def test_negative_value(self):
        from app.analytics.probabilities.probability_provider import (
            validate_probabilities,
        )
        probs = {"a": -0.1, "b": 1.1}
        issues = validate_probabilities(probs)
        assert any("negative" in i for i in issues)

    def test_sum_not_one(self):
        from app.analytics.probabilities.probability_provider import (
            validate_probabilities,
        )
        probs = {"a": 0.3, "b": 0.3}
        issues = validate_probabilities(probs)
        assert any("sum_not_one" in i for i in issues)


# ---------------------------------------------------------------------------
# 4b. normalize_probabilities with canonical PA labels
# ---------------------------------------------------------------------------


class TestNormalizeProbabilitiesCanonicalLabels:
    """PA labels use canonical names (walk_or_hbp, ball_in_play_out)."""

    def test_canonical_labels_normalize(self):
        from app.analytics.probabilities.probability_provider import (
            normalize_probabilities,
        )
        from app.analytics.sports.mlb.constants import PA_EVENTS

        probs = {
            "strikeout": 0.22,
            "walk_or_hbp": 0.08,
            "single": 0.15,
            "double": 0.05,
            "triple": 0.01,
            "home_run": 0.03,
            "ball_in_play_out": 0.46,
        }
        result = normalize_probabilities(probs, PA_EVENTS)

        assert result["walk_or_hbp"] > 0
        assert result["ball_in_play_out"] > 0
        assert abs(sum(result.values()) - 1.0) < 0.01

    def test_missing_events_default_to_zero(self):
        from app.analytics.probabilities.probability_provider import (
            normalize_probabilities,
        )
        from app.analytics.sports.mlb.constants import PA_EVENTS

        # Only provide a few events — rest should be 0
        probs = {"strikeout": 0.5, "home_run": 0.5}
        result = normalize_probabilities(probs, PA_EVENTS)
        assert result["walk_or_hbp"] == 0.0
        assert result["ball_in_play_out"] == 0.0
        assert abs(sum(result.values()) - 1.0) < 0.01


# ---------------------------------------------------------------------------
# 5. ProfileResult / data_freshness
# ---------------------------------------------------------------------------

class TestProfileResult:
    """ProfileResult dataclass carries freshness metadata."""

    def test_profile_result_fields(self):
        from app.analytics.services.profile_service import ProfileResult

        pr = ProfileResult(
            metrics={"whiff_rate": 0.23},
            games_used=15,
            date_range=("2026-02-10", "2026-03-10"),
            season_breakdown={2026: 15},
        )
        assert pr.games_used == 15
        assert pr.date_range == ("2026-02-10", "2026-03-10")
        assert pr.season_breakdown[2026] == 15


# ---------------------------------------------------------------------------
# 6. ModelInferenceEngine.get_model_status
# ---------------------------------------------------------------------------

class TestGetModelStatus:
    """get_model_status returns structured info about model availability."""

    def test_no_active_model(self):
        from app.analytics.inference.model_inference_engine import (
            ModelInferenceEngine,
        )

        registry = MagicMock()
        registry.get_active_model_info.return_value = None
        engine = ModelInferenceEngine(registry=registry)

        status = engine.get_model_status("mlb", "plate_appearance")
        assert status["available"] is False
        assert status["reason"] == "no_active_model"

    def test_active_model_no_path(self):
        from app.analytics.inference.model_inference_engine import (
            ModelInferenceEngine,
        )

        registry = MagicMock()
        registry.get_active_model_info.return_value = {
            "model_id": "pa-v1",
            "version": 1,
            "trained_at": None,
            "metrics": {},
            "path": None,
        }
        engine = ModelInferenceEngine(registry=registry)

        status = engine.get_model_status("mlb", "plate_appearance")
        assert status["available"] is False
        assert status["reason"] == "no_artifact_path"

    def test_active_model_with_path(self, tmp_path):
        from app.analytics.inference.model_inference_engine import (
            ModelInferenceEngine,
        )

        # Create a real file so is_file() returns True
        artifact = tmp_path / "pa-v3.pkl"
        artifact.write_bytes(b"fake")

        registry = MagicMock()
        registry.get_active_model_info.return_value = {
            "model_id": "pa-v3",
            "version": 3,
            "trained_at": "2026-03-09",
            "metrics": {"accuracy": 0.61},
            "path": str(artifact),
        }
        engine = ModelInferenceEngine(registry=registry)

        status = engine.get_model_status("mlb", "plate_appearance")
        assert status["available"] is True
        assert status["model_id"] == "pa-v3"
        assert status["version"] == 3
        assert status["metrics"]["accuracy"] == 0.61

    def test_active_model_artifact_missing(self):
        """get_model_status reports unavailable when artifact file is missing."""
        from app.analytics.inference.model_inference_engine import (
            ModelInferenceEngine,
        )

        registry = MagicMock()
        registry.get_active_model_info.return_value = {
            "model_id": "pa-v3",
            "version": 3,
            "trained_at": "2026-03-09",
            "metrics": {"accuracy": 0.61},
            "path": "/nonexistent/pa-v3.pkl",
        }
        engine = ModelInferenceEngine(registry=registry)

        status = engine.get_model_status("mlb", "plate_appearance")
        assert status["available"] is False
        assert status["reason"] == "artifact_not_found"
        assert status["model_id"] == "pa-v3"
