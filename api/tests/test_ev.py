"""Tests for EV calculation engine — eligibility gate, compute, and math regression."""

from datetime import UTC, datetime, timedelta

import pytest

from app.services.ev import (
    EVComputeResult,
    _find_sharp_entry,
    american_to_implied,
    book_spread_factor,
    calculate_ev,
    compute_ev_for_market,
    evaluate_ev_eligibility,
    extrapolation_distance_factor,
    implied_to_american,
    pinnacle_alignment_factor,
    probability_confidence,
    remove_vig,
)
from app.services.ev_config import EVStrategyConfig, get_strategy

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

NOW = datetime(2026, 2, 14, 12, 0, 0, tzinfo=UTC)
FRESH = NOW - timedelta(minutes=5)
STALE_1H = NOW - timedelta(hours=2)


def _make_books(
    book_prices: dict[str, float],
    observed_at: datetime = FRESH,
) -> list[dict]:
    """Build a list of book dicts for testing."""
    return [
        {"book": book, "price": price, "observed_at": observed_at}
        for book, price in book_prices.items()
    ]


# ---------------------------------------------------------------------------
# Math functions — byte-for-byte regression tests
# ---------------------------------------------------------------------------


class TestAmericanToImplied:
    """Regression tests for american_to_implied()."""

    def test_negative_110(self) -> None:
        result = american_to_implied(-110)
        assert abs(result - 0.52381) < 0.0001

    def test_positive_150(self) -> None:
        result = american_to_implied(150)
        assert abs(result - 0.4) < 0.0001

    def test_even_money_positive(self) -> None:
        result = american_to_implied(100)
        assert abs(result - 0.5) < 0.0001

    def test_even_money_negative(self) -> None:
        result = american_to_implied(-100)
        assert abs(result - 0.5) < 0.0001

    def test_heavy_favorite(self) -> None:
        result = american_to_implied(-300)
        assert abs(result - 0.75) < 0.0001

    def test_heavy_underdog(self) -> None:
        result = american_to_implied(300)
        assert abs(result - 0.25) < 0.0001

    def test_invalid_midrange_raises(self) -> None:
        """Prices between -100 and +100 are invalid American odds."""
        with pytest.raises(ValueError, match="Invalid American odds"):
            american_to_implied(50)
        with pytest.raises(ValueError, match="Invalid American odds"):
            american_to_implied(-50)
        with pytest.raises(ValueError, match="Invalid American odds"):
            american_to_implied(0)


class TestRemoveVig:
    """Regression tests for remove_vig() using Shin's method."""

    def test_standard_vig(self) -> None:
        """Standard -110/-110 market has ~4.76% vig.

        Shin produces ~0.5005 per side (tiny residual from the formula),
        which is close enough for practical purposes.
        """
        implied_a = american_to_implied(-110)
        implied_b = american_to_implied(-110)
        true = remove_vig([implied_a, implied_b])
        assert abs(true[0] - 0.5) < 0.001
        assert abs(true[1] - 0.5) < 0.001
        assert abs(sum(true) - 1.0) < 0.01

    def test_asymmetric_line(self) -> None:
        """Asymmetric line like -150/+130."""
        implied_a = american_to_implied(-150)
        implied_b = american_to_implied(130)
        true = remove_vig([implied_a, implied_b])
        assert abs(sum(true) - 1.0) < 0.01
        assert true[0] > true[1]  # Favorite has higher true prob

    def test_zero_total(self) -> None:
        """Zero total returns input unchanged."""
        result = remove_vig([0.0, 0.0])
        assert result == [0.0, 0.0]

    def test_no_vig_no_change(self) -> None:
        """When total = 1.0 (no vig), falls back to additive (identity)."""
        result = remove_vig([0.5, 0.5])
        assert abs(result[0] - 0.5) < 0.0001
        assert abs(result[1] - 0.5) < 0.0001

    def test_shin_favors_longshot_correction(self) -> None:
        """Shin should shift more vig to the longshot than additive."""
        # -200 fav (~66.7%) vs +200 dog (~33.3%), with ~5% vig
        fav_implied = 0.6897  # -200 → 68.97% (vigged)
        dog_implied = 0.3571  # +200 → 35.71% (vigged)
        result = remove_vig([fav_implied, dog_implied])
        # Additive would give: 65.87%, 34.13%
        # Shin: fav gets LESS correction, dog gets MORE
        assert result[0] > 0.66  # Fav true prob higher than additive
        assert result[1] < 0.34  # Dog true prob lower than additive
        assert abs(sum(result) - 1.0) < 0.01

    def test_shin_extreme_longshot(self) -> None:
        """Extreme longshot (+400) gets even larger Shin correction."""
        fav_implied = american_to_implied(-500)  # 83.3%
        dog_implied = american_to_implied(400)   # 20.0%
        result = remove_vig([fav_implied, dog_implied])
        # Additive: fav=80.6%, dog=19.4%
        additive_fav = fav_implied / (fav_implied + dog_implied)
        additive_dog = dog_implied / (fav_implied + dog_implied)
        # Shin should give fav MORE prob (less correction) and dog LESS
        assert result[0] > additive_fav
        assert result[1] < additive_dog
        assert abs(sum(result) - 1.0) < 0.01

    def test_shin_near_even_minimal_difference(self) -> None:
        """Near-even odds should show minimal difference from additive."""
        implied_a = american_to_implied(-108)
        implied_b = american_to_implied(-112)
        result = remove_vig([implied_a, implied_b])
        additive_a = implied_a / (implied_a + implied_b)
        # Near 50/50 lines: Shin and additive should be very close
        assert abs(result[0] - additive_a) < 0.005
        assert abs(sum(result) - 1.0) < 0.01


class TestCalculateEV:
    """Regression tests for calculate_ev()."""

    def test_positive_ev(self) -> None:
        """Book offers better odds than true prob suggests."""
        ev = calculate_ev(150, 0.45)
        # decimal_odds = 2.5, ev = (2.5 * 0.45 - 1) * 100 = 12.5%
        assert abs(ev - 12.5) < 0.01

    def test_negative_ev(self) -> None:
        """Standard -110 at 50% true prob is negative EV."""
        ev = calculate_ev(-110, 0.5)
        # decimal_odds = 1.9091, ev = (1.9091 * 0.5 - 1) * 100 = -4.55%
        assert ev < 0

    def test_zero_ev(self) -> None:
        """Fair line at true probability gives 0 EV."""
        ev = calculate_ev(100, 0.5)
        # decimal_odds = 2.0, ev = (2.0 * 0.5 - 1) * 100 = 0%
        assert abs(ev) < 0.01

    def test_invalid_midrange_raises(self) -> None:
        """Prices between -100 and +100 are invalid American odds."""
        with pytest.raises(ValueError, match="Invalid American odds"):
            calculate_ev(50, 0.5)
        with pytest.raises(ValueError, match="Invalid American odds"):
            calculate_ev(0, 0.5)


# ---------------------------------------------------------------------------
# _find_sharp_entry
# ---------------------------------------------------------------------------


class TestFindSharpEntry:
    """Tests for _find_sharp_entry() helper."""

    def test_finds_pinnacle(self) -> None:
        books = _make_books({"DraftKings": -110, "Pinnacle": -108, "FanDuel": -112})
        entry = _find_sharp_entry(books, ("Pinnacle",))
        assert entry is not None
        assert entry["book"] == "Pinnacle"
        assert entry["price"] == -108

    def test_returns_none_when_missing(self) -> None:
        books = _make_books({"DraftKings": -110, "FanDuel": -112})
        entry = _find_sharp_entry(books, ("Pinnacle",))
        assert entry is None

    def test_returns_first_match(self) -> None:
        books = _make_books({"SharpA": -105, "SharpB": -107})
        entry = _find_sharp_entry(books, ("SharpA", "SharpB"))
        assert entry is not None
        assert entry["book"] == "SharpA"


# ---------------------------------------------------------------------------
# evaluate_ev_eligibility — all 4 disabled reasons + eligible
# ---------------------------------------------------------------------------


class TestEvaluateEVEligibility:
    """Tests for the eligibility gate."""

    def test_no_strategy_for_period(self) -> None:
        """period markets have no strategy → disabled_reason='no_strategy'."""
        result = evaluate_ev_eligibility(
            "NBA",
            "period",
            _make_books({"Pinnacle": -110, "DraftKings": -108, "FanDuel": -112}),
            _make_books({"Pinnacle": -110, "DraftKings": -112, "FanDuel": -108}),
            now=NOW,
        )
        assert result.eligible is False
        assert result.disabled_reason == "no_strategy"
        assert result.strategy_config is None
        assert result.ev_method is None

    def test_no_strategy_for_game_prop(self) -> None:
        result = evaluate_ev_eligibility(
            "NBA",
            "game_prop",
            _make_books({"Pinnacle": -110}),
            _make_books({"Pinnacle": -110}),
            now=NOW,
        )
        assert result.eligible is False
        assert result.disabled_reason == "no_strategy"

    def test_reference_missing_no_pinnacle(self) -> None:
        """No Pinnacle on side A → disabled_reason='reference_missing'."""
        result = evaluate_ev_eligibility(
            "NBA",
            "mainline",
            _make_books({"DraftKings": -110, "FanDuel": -108, "BetMGM": -112}),
            _make_books({"Pinnacle": -110, "DraftKings": -112, "FanDuel": -108}),
            now=NOW,
        )
        assert result.eligible is False
        assert result.disabled_reason == "reference_missing"
        assert result.ev_method == "pinnacle_devig"
        assert result.confidence_tier is None  # No tier when reference missing

    def test_reference_stale(self) -> None:
        """Pinnacle observed_at older than staleness limit → 'reference_stale'."""
        stale_books_a = _make_books(
            {"Pinnacle": -110, "DraftKings": -108, "FanDuel": -112},
            observed_at=STALE_1H,
        )
        fresh_books_b = _make_books(
            {"Pinnacle": -110, "DraftKings": -112, "FanDuel": -108}, observed_at=FRESH
        )
        result = evaluate_ev_eligibility(
            "NBA",
            "mainline",
            stale_books_a,
            fresh_books_b,
            now=NOW,
        )
        assert result.eligible is False
        assert result.disabled_reason == "reference_stale"

    def test_insufficient_books(self) -> None:
        """Fewer than 3 qualifying books per side → 'insufficient_books'."""
        result = evaluate_ev_eligibility(
            "NBA",
            "mainline",
            _make_books({"Pinnacle": -110, "DraftKings": -108}),  # Only 2 books
            _make_books({"Pinnacle": -110, "DraftKings": -112, "FanDuel": -108}),
            now=NOW,
        )
        assert result.eligible is False
        assert result.disabled_reason == "insufficient_books"

    def test_eligible_nba_mainline(self) -> None:
        """Full eligible NBA mainline market."""
        result = evaluate_ev_eligibility(
            "NBA",
            "mainline",
            _make_books({"Pinnacle": -110, "DraftKings": -108, "FanDuel": -112}),
            _make_books({"Pinnacle": -110, "DraftKings": -112, "FanDuel": -108}),
            now=NOW,
        )
        assert result.eligible is True
        assert result.disabled_reason is None
        assert result.ev_method == "pinnacle_devig"
        # 2 non-sharp books per side (DraftKings, FanDuel) → "thin"
        assert result.confidence_tier == "thin"
        assert result.strategy_config is not None

    def test_eligible_ncaab_player_prop(self) -> None:
        """Eligible NCAAB player prop — consensus requires 4 common books."""
        result = evaluate_ev_eligibility(
            "NCAAB",
            "player_prop",
            _make_books({"DraftKings": -108, "FanDuel": -112, "BetMGM": -110, "Caesars": -109}),
            _make_books({"DraftKings": -112, "FanDuel": -108, "BetMGM": -110, "Caesars": -111}),
            now=NOW,
        )
        assert result.eligible is True
        assert result.ev_method == "median_consensus"
        # 4 non-sharp books per side → "decent"
        assert result.confidence_tier == "decent"

    def test_excluded_books_dont_count(self) -> None:
        """Excluded books should not count toward min_qualifying_books."""
        result = evaluate_ev_eligibility(
            "NBA",
            "mainline",
            _make_books(
                {"Pinnacle": -110, "DraftKings": -108, "Bovada": -112}
            ),  # Bovada is excluded
            _make_books({"Pinnacle": -110, "DraftKings": -112, "FanDuel": -108}),
            now=NOW,
        )
        assert result.eligible is False
        assert result.disabled_reason == "insufficient_books"


# ---------------------------------------------------------------------------
# compute_ev_for_market — new return type
# ---------------------------------------------------------------------------


class TestComputeEVForMarket:
    """Tests for compute_ev_for_market() with EVComputeResult."""

    @pytest.fixture
    def nba_mainline_config(self) -> EVStrategyConfig:
        config = get_strategy("NBA", "mainline")
        assert config is not None
        return config

    def test_returns_ev_compute_result(
        self, nba_mainline_config: EVStrategyConfig
    ) -> None:
        result = compute_ev_for_market(
            _make_books({"Pinnacle": -110, "DraftKings": -105}),
            _make_books({"Pinnacle": -110, "DraftKings": -115}),
            nba_mainline_config,
        )
        assert isinstance(result, EVComputeResult)
        assert result.ev_method == "pinnacle_devig"
        # 1 non-sharp book per side (DraftKings) → "thin"
        assert result.confidence_tier == "thin"

    def test_true_probs_sum_to_one(self, nba_mainline_config: EVStrategyConfig) -> None:
        result = compute_ev_for_market(
            _make_books({"Pinnacle": -150, "DraftKings": -145}),
            _make_books({"Pinnacle": 130, "DraftKings": 125}),
            nba_mainline_config,
        )
        assert result.true_prob_a is not None
        assert result.true_prob_b is not None
        assert abs(result.true_prob_a + result.true_prob_b - 1.0) < 0.01

    def test_reference_prices_captured(
        self, nba_mainline_config: EVStrategyConfig
    ) -> None:
        result = compute_ev_for_market(
            _make_books({"Pinnacle": -110, "DraftKings": -105}),
            _make_books({"Pinnacle": -110, "DraftKings": -115}),
            nba_mainline_config,
        )
        assert result.reference_price_a == -110
        assert result.reference_price_b == -110

    def test_annotated_books_have_ev(
        self, nba_mainline_config: EVStrategyConfig
    ) -> None:
        result = compute_ev_for_market(
            _make_books({"Pinnacle": -110, "DraftKings": -105}),
            _make_books({"Pinnacle": -110, "DraftKings": -115}),
            nba_mainline_config,
        )
        # Every book on both sides should have ev_percent
        for b in result.annotated_a:
            assert b["ev_percent"] is not None
            assert b["true_prob"] is not None
            assert b["implied_prob"] is not None
        for b in result.annotated_b:
            assert b["ev_percent"] is not None

    def test_sharp_book_marked(self, nba_mainline_config: EVStrategyConfig) -> None:
        result = compute_ev_for_market(
            _make_books({"Pinnacle": -110, "DraftKings": -105}),
            _make_books({"Pinnacle": -110, "DraftKings": -115}),
            nba_mainline_config,
        )
        pinnacle_a = next(b for b in result.annotated_a if b["book"] == "Pinnacle")
        dk_a = next(b for b in result.annotated_a if b["book"] == "DraftKings")
        assert pinnacle_a["is_sharp"] is True
        assert dk_a["is_sharp"] is False

    def test_ev_math_regression(self, nba_mainline_config: EVStrategyConfig) -> None:
        """Regression: verify EV numbers for known inputs.

        Pinnacle -110/-110 → Shin true_prob ≈ 0.5005/0.5005 each side.
        DraftKings -105 on side A: decimal = 1.9524, ev ≈ -2.28%
        FanDuel +105 on side A: decimal = 2.05, ev ≈ +2.60%
        """
        result = compute_ev_for_market(
            _make_books({"Pinnacle": -110, "DraftKings": -105, "FanDuel": 105}),
            _make_books({"Pinnacle": -110, "DraftKings": -115, "FanDuel": -105}),
            nba_mainline_config,
        )

        # Side A — DK should be negative EV, FD should be positive EV
        dk_a = next(b for b in result.annotated_a if b["book"] == "DraftKings")
        fd_a = next(b for b in result.annotated_a if b["book"] == "FanDuel")
        assert dk_a["ev_percent"] < 0  # DK -105 is still negative EV
        assert abs(dk_a["ev_percent"] - (-2.28)) < 0.3
        assert fd_a["ev_percent"] > 0  # FD +105 is still positive EV
        assert abs(fd_a["ev_percent"] - 2.60) < 0.3

        # True probs should be ~0.5 each (Shin gives ~0.5005 for symmetric)
        assert abs(result.true_prob_a - 0.5) < 0.002
        assert abs(result.true_prob_b - 0.5) < 0.002

    def test_invalid_book_price_skipped_gracefully(
        self, nba_mainline_config: EVStrategyConfig
    ) -> None:
        """A single book with an invalid price (between -100 and +100) does not crash.

        The bad entry should get implied_prob=None and ev_percent=None while
        the valid entries are annotated normally.
        """
        side_a = _make_books({"Pinnacle": -110, "DraftKings": -105, "BadBook": 50})
        side_b = _make_books({"Pinnacle": -110, "DraftKings": -115})
        result = compute_ev_for_market(side_a, side_b, nba_mainline_config)

        bad = next(b for b in result.annotated_a if b["book"] == "BadBook")
        assert bad["implied_prob"] is None
        assert bad["ev_percent"] is None

        good = next(b for b in result.annotated_a if b["book"] == "DraftKings")
        assert good["implied_prob"] is not None
        assert good["ev_percent"] is not None

    def test_invalid_sharp_price_skips_devig(
        self, nba_mainline_config: EVStrategyConfig
    ) -> None:
        """If the sharp book itself has an invalid price, devig is skipped.

        No true_prob can be computed, so ev_percent is None for all entries,
        but the function does not raise.
        """
        side_a = _make_books({"Pinnacle": 50, "DraftKings": -105})
        side_b = _make_books({"Pinnacle": -110, "DraftKings": -115})
        result = compute_ev_for_market(side_a, side_b, nba_mainline_config)

        assert result.true_prob_a is None
        assert result.true_prob_b is None

        for b in result.annotated_a + result.annotated_b:
            assert b["ev_percent"] is None


# ---------------------------------------------------------------------------
# implied_to_american — inverse of american_to_implied
# ---------------------------------------------------------------------------


class TestImpliedToAmerican:
    """Unit tests for the implied_to_american() helper."""

    def test_favorite(self) -> None:
        """0.75 implied → -300 American."""
        result = implied_to_american(0.75)
        assert abs(result - (-300)) < 0.1

    def test_underdog(self) -> None:
        """0.25 implied → +300 American."""
        result = implied_to_american(0.25)
        assert abs(result - 300) < 0.1

    def test_even_money(self) -> None:
        """0.5 implied → -100 American."""
        result = implied_to_american(0.5)
        assert abs(result - (-100)) < 0.1

    def test_edge_zero(self) -> None:
        """0 probability → 0 (degenerate)."""
        assert implied_to_american(0) == 0.0

    def test_edge_one(self) -> None:
        """1.0 probability → 0 (degenerate)."""
        assert implied_to_american(1.0) == 0.0

    def test_roundtrip(self) -> None:
        """american_to_implied(implied_to_american(p)) ≈ p for several values."""
        for p in [0.2, 0.35, 0.5, 0.65, 0.8]:
            american = implied_to_american(p)
            roundtripped = american_to_implied(american)
            assert abs(roundtripped - p) < 0.001, f"Roundtrip failed for p={p}"


# ---------------------------------------------------------------------------
# Fair odds sanity check — compute_ev_for_market() with divergence detection
# ---------------------------------------------------------------------------


class TestFairOddsSanityCheck:
    """Tests for the fair odds divergence check in compute_ev_for_market()."""

    @pytest.fixture
    def nba_mainline_config(self) -> EVStrategyConfig:
        config = get_strategy("NBA", "mainline")
        assert config is not None
        return config

    @pytest.fixture
    def pinnacle_prop_config(self) -> EVStrategyConfig:
        return EVStrategyConfig(
            strategy_name="pinnacle_devig",
            eligible_sharp_books=("Pinnacle",),
            min_qualifying_books=3,
            max_reference_staleness_seconds=1800,
            max_fair_prob_divergence=0.10,
        )

    def test_normal_market_not_flagged(
        self, nba_mainline_config: EVStrategyConfig
    ) -> None:
        """Pinnacle -110/-110, consensus near -110 → not flagged."""
        result = compute_ev_for_market(
            _make_books({"Pinnacle": -110, "DraftKings": -108, "FanDuel": -112}),
            _make_books({"Pinnacle": -110, "DraftKings": -112, "FanDuel": -108}),
            nba_mainline_config,
        )
        assert result.fair_odds_suspect is False

    def test_divergent_longshot_flagged(
        self, pinnacle_prop_config: EVStrategyConfig
    ) -> None:
        """Pinnacle -1500/+800, consensus near -400/+350 → flagged.

        Pinnacle's extremely lopsided line devigs to a fair price far from consensus.
        """
        result = compute_ev_for_market(
            _make_books({"Pinnacle": -1500, "DraftKings": -400, "FanDuel": -400}),
            _make_books({"Pinnacle": 800, "DraftKings": 350, "FanDuel": 350}),
            pinnacle_prop_config,
        )
        assert result.fair_odds_suspect is True

    def test_threshold_boundary_not_flagged(
        self, nba_mainline_config: EVStrategyConfig
    ) -> None:
        """Fair odds exactly at the threshold boundary → not flagged.

        NBA mainline threshold is 150. Build a scenario where the divergence
        is just under the limit.
        """
        # Pinnacle -150/+130, books consensus near the same range
        result = compute_ev_for_market(
            _make_books({"Pinnacle": -150, "DraftKings": -145, "FanDuel": -155}),
            _make_books({"Pinnacle": 130, "DraftKings": 125, "FanDuel": 135}),
            nba_mainline_config,
        )
        assert result.fair_odds_suspect is False

    def test_suspect_result_still_has_annotations(
        self, pinnacle_prop_config: EVStrategyConfig
    ) -> None:
        """Even when flagged, annotated_a/annotated_b are populated."""
        result = compute_ev_for_market(
            _make_books({"Pinnacle": -1500, "DraftKings": -400, "FanDuel": -400}),
            _make_books({"Pinnacle": 800, "DraftKings": 350, "FanDuel": 350}),
            pinnacle_prop_config,
        )
        assert result.fair_odds_suspect is True
        # Annotations are still computed — the caller decides what to do
        assert len(result.annotated_a) == 3
        assert len(result.annotated_b) == 3
        for b in result.annotated_a:
            assert b["ev_percent"] is not None


# ---------------------------------------------------------------------------
# Confidence functions — probability_confidence, pinnacle_alignment_factor,
# extrapolation_distance_factor
# ---------------------------------------------------------------------------


class TestProbabilityConfidence:
    """Tests for probability_confidence() decay below 25%."""

    def test_above_threshold_returns_one(self) -> None:
        """Probabilities >= 25% have full confidence."""
        assert probability_confidence(0.52) == 1.0
        assert probability_confidence(0.28) == 1.0
        assert probability_confidence(0.50) == 1.0
        assert probability_confidence(0.25) == 1.0

    def test_at_15_percent(self) -> None:
        """15% → sqrt(0.15/0.25) ≈ 0.7746."""
        result = probability_confidence(0.15)
        assert abs(result - 0.7746) < 0.001

    def test_at_12_percent(self) -> None:
        """12% → sqrt(0.12/0.25) ≈ 0.6928."""
        result = probability_confidence(0.12)
        assert abs(result - 0.6928) < 0.001

    def test_at_8_percent(self) -> None:
        """8% → sqrt(0.08/0.25) ≈ 0.5657."""
        result = probability_confidence(0.08)
        assert abs(result - 0.5657) < 0.001

    def test_at_5_percent(self) -> None:
        """5% → sqrt(0.05/0.25) ≈ 0.4472."""
        result = probability_confidence(0.05)
        assert abs(result - 0.4472) < 0.001

    def test_zero_returns_zero(self) -> None:
        assert probability_confidence(0.0) == 0.0

    def test_negative_returns_zero(self) -> None:
        assert probability_confidence(-0.1) == 0.0

    def test_monotonically_increasing(self) -> None:
        """Confidence increases with probability below threshold."""
        probs = [0.05, 0.08, 0.12, 0.15, 0.20, 0.25]
        confidences = [probability_confidence(p) for p in probs]
        for i in range(len(confidences) - 1):
            assert confidences[i] < confidences[i + 1]


class TestPinnacleAlignmentFactor:
    """Tests for pinnacle_alignment_factor() vig-gap check."""

    def test_small_gap_full_confidence(self) -> None:
        """Gap < 2% → factor 1.0 (low vig, reliable devig)."""
        assert pinnacle_alignment_factor(0.50, 0.505) == 1.0
        assert pinnacle_alignment_factor(0.50, 0.515) == 1.0
        assert pinnacle_alignment_factor(0.15, 0.155) == 1.0

    def test_medium_gap(self) -> None:
        """Gap between 2-4% → factor 0.85."""
        assert pinnacle_alignment_factor(0.50, 0.525) == 0.85
        assert pinnacle_alignment_factor(0.50, 0.535) == 0.85

    def test_large_gap(self) -> None:
        """Gap > 4% → factor 0.7 (high vig, suspicious)."""
        assert pinnacle_alignment_factor(0.50, 0.55) == 0.7
        assert pinnacle_alignment_factor(0.50, 0.60) == 0.7

    def test_threshold_boundaries(self) -> None:
        """Near boundary at 0.02 and 0.04."""
        # gap clearly under 0.02 → 1.0
        assert pinnacle_alignment_factor(0.50, 0.519) == 1.0
        # gap clearly over 0.02 → 0.85
        assert pinnacle_alignment_factor(0.50, 0.521) == 0.85
        # gap clearly under 0.04 → 0.85
        assert pinnacle_alignment_factor(0.50, 0.539) == 0.85
        # gap clearly over 0.04 → 0.7
        assert pinnacle_alignment_factor(0.50, 0.541) == 0.7


class TestExtrapolationDistanceFactor:
    """Tests for extrapolation_distance_factor()."""

    def test_close_extrapolation(self) -> None:
        """1-2 half points → 0.90."""
        assert extrapolation_distance_factor(1.0) == 0.90
        assert extrapolation_distance_factor(2.0) == 0.90

    def test_medium_extrapolation(self) -> None:
        """3-4 half points → 0.80."""
        assert extrapolation_distance_factor(3.0) == 0.80
        assert extrapolation_distance_factor(4.0) == 0.80

    def test_far_extrapolation(self) -> None:
        """5+ half points → 0.65."""
        assert extrapolation_distance_factor(5.0) == 0.65
        assert extrapolation_distance_factor(6.0) == 0.65

    def test_negative_values_use_abs(self) -> None:
        """Negative half-points should use absolute value."""
        assert extrapolation_distance_factor(-1.0) == 0.90
        assert extrapolation_distance_factor(-3.0) == 0.80
        assert extrapolation_distance_factor(-5.0) == 0.65


class TestBookSpreadFactor:
    """Tests for book_spread_factor() outlier detection."""

    def test_tight_consensus(self) -> None:
        """All books within 3% of median → 1.0 (no penalty)."""
        assert book_spread_factor([0.40, 0.41, 0.42, 0.43]) == 1.0

    def test_moderate_spread(self) -> None:
        """Best book 3-6% from median → 0.85."""
        # min=0.36, median ~0.41 → spread 0.05
        assert book_spread_factor([0.36, 0.40, 0.42, 0.44]) == 0.85

    def test_wide_spread(self) -> None:
        """Best book 6-10% from median → 0.70."""
        # min=0.33, median ~0.42 → spread 0.09
        assert book_spread_factor([0.33, 0.41, 0.43, 0.45]) == 0.70

    def test_extreme_outlier(self) -> None:
        """Best book >10% from median → 0.55."""
        # min=0.30, median ~0.43 → spread 0.13
        assert book_spread_factor([0.30, 0.42, 0.44, 0.46]) == 0.55

    def test_thin_market(self) -> None:
        """Single book → 0.80 (thin market penalty)."""
        assert book_spread_factor([0.45]) == 0.80

    def test_two_books_tight(self) -> None:
        """Two books close together → 1.0."""
        assert book_spread_factor([0.40, 0.42]) == 1.0

    def test_empty_list(self) -> None:
        """Empty list → 0.80 (thin market)."""
        assert book_spread_factor([]) == 0.80


class TestDisplayEVComputation:
    """Tests verifying display_ev = raw_ev * confidence end-to-end."""

    @pytest.fixture
    def nba_mainline_config(self) -> EVStrategyConfig:
        config = get_strategy("NBA", "mainline")
        assert config is not None
        return config

    def test_high_prob_confidence_one(
        self, nba_mainline_config: EVStrategyConfig
    ) -> None:
        """52% true prob → confidence ~1.0, display_ev ≈ raw_ev."""
        result = compute_ev_for_market(
            _make_books({"Pinnacle": -110, "DraftKings": -105, "FanDuel": 105}),
            _make_books({"Pinnacle": -110, "DraftKings": -115, "FanDuel": -105}),
            nba_mainline_config,
        )
        # true_prob should be ~0.5 each side
        assert result.true_prob_a is not None
        conf = probability_confidence(result.true_prob_a)
        assert conf == 1.0

    def test_low_prob_confidence_decays(self) -> None:
        """15% true prob → confidence ≈ 0.77, display_ev < raw_ev."""
        raw_ev = 14.2
        conf = probability_confidence(0.15)
        display = raw_ev * conf
        assert abs(display - 11.0) < 0.5  # ~10.93

    def test_extreme_longshot_confidence(self) -> None:
        """8% true prob → confidence ≈ 0.57, significant reduction."""
        raw_ev = 25.0
        conf = probability_confidence(0.08)
        display = raw_ev * conf
        assert display < 15.0  # 25 * 0.566 ≈ 14.14
        assert display > 13.0
