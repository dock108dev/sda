"""Tests for median consensus EV calculation engine."""

from datetime import UTC, datetime, timedelta

import pytest

from app.services.ev import evaluate_ev_eligibility
from app.services.ev_config import EVStrategyConfig, get_strategy
from app.services.ev_consensus import (
    _iqr,
    _median,
    compute_ev_median_consensus,
    consensus_agreement_factor,
)

NOW = datetime(2026, 2, 14, 12, 0, 0, tzinfo=UTC)
FRESH = NOW - timedelta(minutes=5)


def _make_books(
    book_prices: dict[str, float],
    observed_at: datetime = FRESH,
) -> list[dict]:
    return [
        {"book": book, "price": price, "observed_at": observed_at}
        for book, price in book_prices.items()
    ]


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestMedianHelper:
    def test_odd_count(self) -> None:
        assert _median([1.0, 2.0, 3.0]) == 2.0

    def test_even_count(self) -> None:
        assert _median([1.0, 2.0, 3.0, 4.0]) == 2.5

    def test_single(self) -> None:
        assert _median([5.0]) == 5.0

    def test_empty(self) -> None:
        assert _median([]) == 0.0


class TestIQRHelper:
    def test_four_values(self) -> None:
        # Q1=median([1,2])=1.5, Q3=median([3,4])=3.5 → IQR=2.0
        result = _iqr([1.0, 2.0, 3.0, 4.0])
        assert result == pytest.approx(2.0)

    def test_too_few(self) -> None:
        assert _iqr([1.0, 2.0, 3.0]) == 0.0

    def test_identical_values(self) -> None:
        assert _iqr([0.5, 0.5, 0.5, 0.5]) == 0.0


# ---------------------------------------------------------------------------
# consensus_agreement_factor
# ---------------------------------------------------------------------------


class TestConsensusAgreementFactor:
    def test_tight_agreement(self) -> None:
        """IQR < 2% → 1.0."""
        probs = [0.50, 0.505, 0.51, 0.505]
        assert consensus_agreement_factor(probs) == 1.0

    def test_medium_iqr(self) -> None:
        """IQR between 2% and 4% → 0.85."""
        probs = [0.485, 0.50, 0.51, 0.525]
        factor = consensus_agreement_factor(probs)
        assert factor == 0.85

    def test_wide_iqr(self) -> None:
        """IQR >= 4% → 0.70."""
        probs = [0.45, 0.50, 0.55, 0.60]
        assert consensus_agreement_factor(probs) == 0.70

    def test_few_books_default(self) -> None:
        """Fewer than 4 books → 0.85 (not enough for IQR)."""
        assert consensus_agreement_factor([0.50, 0.52, 0.54]) == 0.85


# ---------------------------------------------------------------------------
# compute_ev_median_consensus — core algorithm
# ---------------------------------------------------------------------------


class TestComputeEVMedianConsensus:
    @pytest.fixture
    def consensus_config(self) -> EVStrategyConfig:
        config = get_strategy("NBA", "player_prop")
        assert config is not None
        assert config.strategy_name == "median_consensus"
        return config

    def test_symmetric_market(self, consensus_config: EVStrategyConfig) -> None:
        """All books at -110/-110 → fair prob ~0.5 each side."""
        side_a = _make_books({
            "DraftKings": -110, "FanDuel": -110, "BetMGM": -110, "Caesars": -110,
        })
        side_b = _make_books({
            "DraftKings": -110, "FanDuel": -110, "BetMGM": -110, "Caesars": -110,
        })
        ev_result, metadata = compute_ev_median_consensus(side_a, side_b, consensus_config)
        assert ev_result.true_prob_a is not None
        assert ev_result.true_prob_b is not None
        assert abs(ev_result.true_prob_a - 0.5) < 0.01
        assert abs(ev_result.true_prob_b - 0.5) < 0.01
        assert ev_result.ev_method == "median_consensus"
        assert metadata is not None
        assert metadata.consensus_book_count == 4

    def test_realistic_prop_spread(self, consensus_config: EVStrategyConfig) -> None:
        """Books at different prices produce valid median fair prob."""
        side_a = _make_books({
            "DraftKings": -115, "FanDuel": -110, "BetMGM": -120, "Caesars": -108,
        })
        side_b = _make_books({
            "DraftKings": -105, "FanDuel": -110, "BetMGM": 100, "Caesars": -112,
        })
        ev_result, metadata = compute_ev_median_consensus(side_a, side_b, consensus_config)
        assert ev_result.true_prob_a is not None
        assert ev_result.true_prob_b is not None
        assert abs(ev_result.true_prob_a + ev_result.true_prob_b - 1.0) < 0.01
        assert metadata is not None
        assert metadata.consensus_book_count == 4
        # All books should have EV annotations
        assert all(b["ev_percent"] is not None for b in ev_result.annotated_a)
        assert all(b["ev_percent"] is not None for b in ev_result.annotated_b)

    def test_outlier_resilience(self, consensus_config: EVStrategyConfig) -> None:
        """One outlier book doesn't distort the median."""
        # 3 books near -110, 1 outlier at -300
        side_a = _make_books({
            "DraftKings": -110, "FanDuel": -112, "BetMGM": -108, "Caesars": -300,
        })
        side_b = _make_books({
            "DraftKings": -110, "FanDuel": -108, "BetMGM": -112, "Caesars": 250,
        })
        ev_result, metadata = compute_ev_median_consensus(side_a, side_b, consensus_config)
        assert ev_result.true_prob_a is not None
        # Median should be close to 0.5, not pulled by outlier
        assert abs(ev_result.true_prob_a - 0.5) < 0.05

    def test_insufficient_common_books(self, consensus_config: EVStrategyConfig) -> None:
        """Fewer than 4 common books → still computes but with fewer data points."""
        side_a = _make_books({"DraftKings": -110, "FanDuel": -112})
        side_b = _make_books({"DraftKings": -110, "BetMGM": -112})
        # Only DraftKings is common
        ev_result, metadata = compute_ev_median_consensus(side_a, side_b, consensus_config)
        assert ev_result.true_prob_a is not None
        assert metadata is not None
        assert metadata.consensus_book_count == 1

    def test_no_common_books(self, consensus_config: EVStrategyConfig) -> None:
        """No common books → None metadata, no true_prob."""
        side_a = _make_books({"DraftKings": -110})
        side_b = _make_books({"FanDuel": -110})
        ev_result, metadata = compute_ev_median_consensus(side_a, side_b, consensus_config)
        assert metadata is None
        assert ev_result.true_prob_a is None

    def test_per_book_fair_probs_populated(self, consensus_config: EVStrategyConfig) -> None:
        """Metadata contains per-book fair probabilities."""
        side_a = _make_books({
            "DraftKings": -110, "FanDuel": -110, "BetMGM": -110, "Caesars": -110,
        })
        side_b = _make_books({
            "DraftKings": -110, "FanDuel": -110, "BetMGM": -110, "Caesars": -110,
        })
        _, metadata = compute_ev_median_consensus(side_a, side_b, consensus_config)
        assert metadata is not None
        assert "DraftKings" in metadata.per_book_fair_probs
        assert "FanDuel" in metadata.per_book_fair_probs
        assert len(metadata.per_book_fair_probs) == 4

    def test_no_sharp_books_marked(self, consensus_config: EVStrategyConfig) -> None:
        """In consensus mode, no books are marked as sharp."""
        side_a = _make_books({
            "DraftKings": -110, "FanDuel": -110, "BetMGM": -110, "Caesars": -110,
        })
        side_b = _make_books({
            "DraftKings": -110, "FanDuel": -110, "BetMGM": -110, "Caesars": -110,
        })
        ev_result, _ = compute_ev_median_consensus(side_a, side_b, consensus_config)
        for b in ev_result.annotated_a + ev_result.annotated_b:
            assert b["is_sharp"] is False

    def test_reference_prices_are_none(self, consensus_config: EVStrategyConfig) -> None:
        """Consensus has no single reference price."""
        side_a = _make_books({
            "DraftKings": -110, "FanDuel": -110, "BetMGM": -110, "Caesars": -110,
        })
        side_b = _make_books({
            "DraftKings": -110, "FanDuel": -110, "BetMGM": -110, "Caesars": -110,
        })
        ev_result, _ = compute_ev_median_consensus(side_a, side_b, consensus_config)
        assert ev_result.reference_price_a is None
        assert ev_result.reference_price_b is None


# ---------------------------------------------------------------------------
# Eligibility integration — consensus path
# ---------------------------------------------------------------------------


class TestConsensusEligibility:
    def test_eligible_with_4_common_books(self) -> None:
        """4 common included books → eligible."""
        result = evaluate_ev_eligibility(
            "NBA", "player_prop",
            _make_books({"DraftKings": -110, "FanDuel": -108, "BetMGM": -112, "Caesars": -109}),
            _make_books({"DraftKings": -110, "FanDuel": -112, "BetMGM": -108, "Caesars": -111}),
            now=NOW,
        )
        assert result.eligible is True
        assert result.ev_method == "median_consensus"

    def test_insufficient_common_books(self) -> None:
        """Only 3 common books → insufficient for consensus (needs 4)."""
        result = evaluate_ev_eligibility(
            "NBA", "player_prop",
            _make_books({"DraftKings": -110, "FanDuel": -108, "BetMGM": -112}),
            _make_books({"DraftKings": -110, "FanDuel": -112, "BetMGM": -108}),
            now=NOW,
        )
        assert result.eligible is False
        assert result.disabled_reason == "insufficient_books"
        assert result.ev_method == "median_consensus"

    def test_excluded_books_not_counted(self) -> None:
        """Excluded books don't count toward common book requirement."""
        result = evaluate_ev_eligibility(
            "NBA", "player_prop",
            _make_books({"DraftKings": -110, "FanDuel": -108, "Bovada": -112, "BetOnline.ag": -109}),
            _make_books({"DraftKings": -110, "FanDuel": -112, "Bovada": -108, "BetOnline.ag": -111}),
            now=NOW,
        )
        assert result.eligible is False
        assert result.disabled_reason == "insufficient_books"

    def test_pinnacle_not_required(self) -> None:
        """Consensus doesn't require Pinnacle — eligible without it."""
        result = evaluate_ev_eligibility(
            "NBA", "player_prop",
            _make_books({"DraftKings": -110, "FanDuel": -108, "BetMGM": -112, "Caesars": -109}),
            _make_books({"DraftKings": -110, "FanDuel": -112, "BetMGM": -108, "Caesars": -111}),
            now=NOW,
        )
        assert result.eligible is True
        # No Pinnacle needed

    def test_mainline_still_uses_pinnacle(self) -> None:
        """Mainline markets still use pinnacle_devig strategy."""
        result = evaluate_ev_eligibility(
            "NBA", "mainline",
            _make_books({"Pinnacle": -110, "DraftKings": -108, "FanDuel": -112}),
            _make_books({"Pinnacle": -110, "DraftKings": -112, "FanDuel": -108}),
            now=NOW,
        )
        assert result.eligible is True
        assert result.ev_method == "pinnacle_devig"

    def test_all_leagues_player_prop_consensus(self) -> None:
        """All leagues use median_consensus for player_prop."""
        for league in ("NBA", "NHL", "NCAAB", "MLB"):
            config = get_strategy(league, "player_prop")
            assert config is not None
            assert config.strategy_name == "median_consensus"
