"""Tests for fairbet_display service functions."""

from __future__ import annotations

from app.services.ev import calculate_ev
from app.services.fairbet_display import (
    book_abbreviation,
    build_explanation_steps,
    confidence_display_label,
    ev_method_display_name,
    ev_method_explanation,
    fair_american_odds,
    market_display_name,
    selection_display,
)


class TestFairAmericanOdds:
    def test_even_money(self) -> None:
        # 50% probability -> -100
        result = fair_american_odds(0.5)
        assert result == -100

    def test_underdog(self) -> None:
        # ~33% probability -> +200
        result = fair_american_odds(1 / 3)
        assert result == 200

    def test_favorite(self) -> None:
        # ~67% probability -> -200
        result = fair_american_odds(2 / 3)
        assert result == -200

    def test_none_input(self) -> None:
        assert fair_american_odds(None) is None

    def test_degenerate_input(self) -> None:
        # prob <= 0 or >= 1 returns None (implied_to_american returns 0.0)
        assert fair_american_odds(0.0) is None
        assert fair_american_odds(1.0) is None


class TestMarketDisplayName:
    def test_known_keys(self) -> None:
        assert market_display_name("spreads") == "Spread"
        assert market_display_name("totals") == "Total"
        assert market_display_name("h2h") == "Moneyline"
        assert market_display_name("player_points") == "Player Points"
        assert market_display_name("team_totals") == "Team Total"

    def test_unknown_key_fallback(self) -> None:
        assert market_display_name("some_new_market") == "Some New Market"


class TestBookAbbreviation:
    def test_known_books(self) -> None:
        assert book_abbreviation("DraftKings") == "DK"
        assert book_abbreviation("FanDuel") == "FD"
        assert book_abbreviation("Pinnacle") == "PIN"
        assert book_abbreviation("BetMGM") == "MGM"

    def test_unknown_book_fallback(self) -> None:
        assert book_abbreviation("SomeNewBook") == "SOM"


class TestConfidenceDisplayLabel:
    def test_known_tiers(self) -> None:
        assert confidence_display_label("full") == "Sharp"
        assert confidence_display_label("decent") == "Market"
        assert confidence_display_label("thin") == "Thin"

    def test_none_input(self) -> None:
        assert confidence_display_label(None) is None

    def test_unknown_tier_fallback(self) -> None:
        assert confidence_display_label("unknown_tier") == "Unknown_Tier"


class TestSelectionDisplay:
    def test_team_spread(self) -> None:
        result = selection_display(
            "team:bos:home", "spreads",
            home_team="Boston Celtics", line_value=-3.5,
        )
        assert result == "Boston Celtics -3.5"

    def test_game_total(self) -> None:
        result = selection_display("total:over", "totals", line_value=215.5)
        assert result == "Over 215.5"

    def test_player_prop(self) -> None:
        result = selection_display(
            "player:lebron_james:over", "player_points",
            player_name="LeBron James", line_value=25.5,
        )
        assert result == "LeBron James Over 25.5"

    def test_moneyline(self) -> None:
        result = selection_display(
            "team:bos:home", "h2h",
            home_team="Boston Celtics",
        )
        assert result == "Boston Celtics ML"

    def test_team_total(self) -> None:
        result = selection_display(
            "total:bos:over", "team_totals",
            line_value=110.5,
        )
        assert result == "Bos Over 110.5"

    def test_empty_selection_key(self) -> None:
        result = selection_display("", "spreads")
        assert result == "Spread"

    def test_player_prop_no_name_fallback(self) -> None:
        result = selection_display(
            "player:lebron_james:over", "player_points",
            line_value=25.5,
        )
        assert result == "Lebron James Over 25.5"


class TestEvMethodDisplay:
    def test_known_method(self) -> None:
        assert ev_method_display_name("pinnacle_devig") == "Pinnacle Devig"
        assert ev_method_display_name("pinnacle_extrapolated") == "Pinnacle Extrapolated"
        assert ev_method_display_name("median_consensus") == "Median Consensus"

    def test_unknown_method_fallback(self) -> None:
        assert ev_method_display_name("some_method") == "Some Method"

    def test_none_input(self) -> None:
        assert ev_method_display_name(None) is None

    def test_explanation(self) -> None:
        result = ev_method_explanation("pinnacle_devig")
        assert result is not None
        assert "Pinnacle" in result

    def test_explanation_consensus(self) -> None:
        result = ev_method_explanation("median_consensus")
        assert result is not None
        assert "median" in result

    def test_explanation_unknown(self) -> None:
        assert ev_method_explanation("unknown") is None

    def test_explanation_none(self) -> None:
        assert ev_method_explanation(None) is None


# ---------------------------------------------------------------------------
# build_explanation_steps tests
# ---------------------------------------------------------------------------

# Shared kwargs for a standard Pinnacle devig scenario:
# -110 / -110 → ~52.4% each, total ~104.8%, true_prob ~0.50
_PINNACLE_BASE = dict(
    ev_method="pinnacle_devig",
    ev_disabled_reason=None,
    true_prob=0.5,
    reference_price=-110.0,
    opposite_reference_price=-110.0,
    fair_odds=-100,
    estimated_sharp_price=None,
    extrapolation_ref_line=None,
    extrapolation_distance=None,
)


class TestBuildExplanationSteps:
    def test_pinnacle_devig_full_path(self) -> None:
        steps = build_explanation_steps(
            **_PINNACLE_BASE,
            best_book="DraftKings",
            best_book_price=-105.0,
            best_ev_percent=2.5,
        )
        assert len(steps) == 4
        assert steps[0]["title"] == "Convert odds to implied probability"
        assert steps[1]["title"] == "Identify the vig"
        assert steps[2]["title"] == "Remove the vig (Shin's method)"
        assert steps[3]["title"] == "Calculate EV at best price"

        # Step 1 should have 3 detail rows (this side, other side, total)
        assert len(steps[0]["detail_rows"]) == 3
        # Verify implied conversion values appear
        assert "-110" in steps[0]["detail_rows"][0]["value"]
        assert "52." in steps[0]["detail_rows"][0]["value"]  # ~52.4%

        # Step 2 vig row should be highlighted
        vig_row = steps[1]["detail_rows"][2]
        assert vig_row["is_highlight"] is True
        assert "4." in vig_row["value"]  # ~4.8% vig

        # Step 3 fair probability row should be highlighted
        fair_prob_row = steps[2]["detail_rows"][2]
        assert fair_prob_row["is_highlight"] is True

        # Step 4 EV row should be highlighted
        ev_row = steps[3]["detail_rows"][3]
        assert ev_row["is_highlight"] is True

    def test_pinnacle_devig_no_best_book(self) -> None:
        steps = build_explanation_steps(
            **_PINNACLE_BASE,
            best_book=None,
            best_book_price=None,
            best_ev_percent=None,
        )
        assert len(steps) == 3
        assert steps[0]["title"] == "Convert odds to implied probability"
        assert steps[1]["title"] == "Identify the vig"
        assert steps[2]["title"] == "Remove the vig (Shin's method)"

    def test_pinnacle_extrapolated_full_path(self) -> None:
        steps = build_explanation_steps(
            ev_method="pinnacle_extrapolated",
            ev_disabled_reason=None,
            true_prob=0.55,
            reference_price=-110.0,
            opposite_reference_price=-110.0,
            fair_odds=-122,
            best_book="FanDuel",
            best_book_price=-115.0,
            best_ev_percent=1.8,
            estimated_sharp_price=-118.0,
            extrapolation_ref_line=5.5,
            extrapolation_distance=2.0,
        )
        assert len(steps) == 4
        assert steps[0]["title"] == "Convert odds to implied probability"
        assert steps[1]["title"] == "Identify the vig"
        assert steps[2]["title"] == "Extrapolate to target line"
        assert steps[3]["title"] == "Calculate EV at best price"

        # Step 3 should contain extrapolation-specific rows
        step3_labels = [r["label"] for r in steps[2]["detail_rows"]]
        assert "Reference line" in step3_labels
        assert "Distance" in step3_labels
        assert "Estimated sharp price" in step3_labels
        assert "Fair probability" in step3_labels

    def test_disabled_reason_produces_single_step(self) -> None:
        reasons = [
            "no_strategy",
            "reference_missing",
            "reference_stale",
            "insufficient_books",
            "fair_odds_outlier",
            "entity_mismatch",
            "no_pair",
        ]
        for reason in reasons:
            steps = build_explanation_steps(
                ev_method=None,
                ev_disabled_reason=reason,
                true_prob=None,
                reference_price=None,
                opposite_reference_price=None,
                fair_odds=None,
                best_book=None,
                best_book_price=None,
                best_ev_percent=None,
                estimated_sharp_price=None,
                extrapolation_ref_line=None,
                extrapolation_distance=None,
            )
            assert len(steps) == 1, f"Expected 1 step for reason={reason}"
            assert steps[0]["title"] == "Fair odds not available"
            # Description should be the human-readable label, not the raw reason
            assert steps[0]["description"] != reason

    def test_fallback_unknown_method(self) -> None:
        steps = build_explanation_steps(
            ev_method="some_unknown_method",
            ev_disabled_reason=None,
            true_prob=0.45,
            reference_price=None,
            opposite_reference_price=None,
            fair_odds=122,
            best_book="BetMGM",
            best_book_price=130.0,
            best_ev_percent=3.0,
            estimated_sharp_price=None,
            extrapolation_ref_line=None,
            extrapolation_distance=None,
        )
        assert len(steps) == 2
        assert steps[0]["title"] == "Fair probability"
        assert steps[1]["title"] == "Calculate EV at best price"

    def test_all_none_not_available(self) -> None:
        steps = build_explanation_steps(
            ev_method=None,
            ev_disabled_reason=None,
            true_prob=None,
            reference_price=None,
            opposite_reference_price=None,
            fair_odds=None,
            best_book=None,
            best_book_price=None,
            best_ev_percent=None,
            estimated_sharp_price=None,
            extrapolation_ref_line=None,
            extrapolation_distance=None,
        )
        assert len(steps) == 1
        assert steps[0]["title"] == "Fair odds not available"

    def test_step_numbers_sequential(self) -> None:
        steps = build_explanation_steps(
            **_PINNACLE_BASE,
            best_book="DraftKings",
            best_book_price=-105.0,
            best_ev_percent=2.5,
        )
        for i, step in enumerate(steps, start=1):
            assert step["step_number"] == i, f"Step {i} has step_number={step['step_number']}"

    def test_median_consensus_full_path(self) -> None:
        per_book = {"DraftKings": 0.52, "FanDuel": 0.51, "BetMGM": 0.50, "Caesars": 0.53}
        steps = build_explanation_steps(
            ev_method="median_consensus",
            ev_disabled_reason=None,
            true_prob=0.515,
            reference_price=None,
            opposite_reference_price=None,
            fair_odds=-106,
            best_book="DraftKings",
            best_book_price=-105.0,
            best_ev_percent=2.0,
            estimated_sharp_price=None,
            extrapolation_ref_line=None,
            extrapolation_distance=None,
            per_book_fair_probs=per_book,
            consensus_iqr=0.015,
        )
        assert len(steps) == 3
        assert steps[0]["title"] == "Devig each book individually"
        assert steps[1]["title"] == "Take median fair probability"
        assert steps[2]["title"] == "Calculate EV at best price"

        # Step 1 should list each book's devigged prob
        step1_labels = [r["label"] for r in steps[0]["detail_rows"]]
        assert "Books contributing" in step1_labels
        assert "DraftKings" in step1_labels
        assert "FanDuel" in step1_labels
        assert "BetMGM" in step1_labels
        assert "Caesars" in step1_labels

        # Step 2 should have fair probability highlighted and IQR
        step2_labels = [r["label"] for r in steps[1]["detail_rows"]]
        assert "Fair probability (median)" in step2_labels
        assert "IQR (agreement)" in step2_labels
        fair_row = next(r for r in steps[1]["detail_rows"] if r["label"] == "Fair probability (median)")
        assert fair_row["is_highlight"] is True

        # Step 3 EV row should be highlighted
        ev_row = steps[2]["detail_rows"][3]
        assert ev_row["is_highlight"] is True

    def test_median_consensus_no_best_book(self) -> None:
        per_book = {"DraftKings": 0.52, "FanDuel": 0.51, "BetMGM": 0.50, "Caesars": 0.53}
        steps = build_explanation_steps(
            ev_method="median_consensus",
            ev_disabled_reason=None,
            true_prob=0.515,
            reference_price=None,
            opposite_reference_price=None,
            fair_odds=-106,
            best_book=None,
            best_book_price=None,
            best_ev_percent=None,
            estimated_sharp_price=None,
            extrapolation_ref_line=None,
            extrapolation_distance=None,
            per_book_fair_probs=per_book,
            consensus_iqr=0.015,
        )
        assert len(steps) == 2
        assert steps[0]["title"] == "Devig each book individually"
        assert steps[1]["title"] == "Take median fair probability"

    def test_median_consensus_no_per_book_data(self) -> None:
        steps = build_explanation_steps(
            ev_method="median_consensus",
            ev_disabled_reason=None,
            true_prob=0.515,
            reference_price=None,
            opposite_reference_price=None,
            fair_odds=-106,
            best_book="DraftKings",
            best_book_price=-105.0,
            best_ev_percent=2.0,
            estimated_sharp_price=None,
            extrapolation_ref_line=None,
            extrapolation_distance=None,
            per_book_fair_probs=None,
            consensus_iqr=None,
        )
        assert len(steps) == 3
        assert steps[0]["title"] == "Devig each book individually"
        # No book rows when per_book_fair_probs is None
        assert len(steps[0]["detail_rows"]) == 0

    def test_median_consensus_step_numbers_sequential(self) -> None:
        per_book = {"DraftKings": 0.52, "FanDuel": 0.51, "BetMGM": 0.50, "Caesars": 0.53}
        steps = build_explanation_steps(
            ev_method="median_consensus",
            ev_disabled_reason=None,
            true_prob=0.515,
            reference_price=None,
            opposite_reference_price=None,
            fair_odds=-106,
            best_book="DraftKings",
            best_book_price=-105.0,
            best_ev_percent=2.0,
            estimated_sharp_price=None,
            extrapolation_ref_line=None,
            extrapolation_distance=None,
            per_book_fair_probs=per_book,
            consensus_iqr=0.015,
        )
        for i, step in enumerate(steps, start=1):
            assert step["step_number"] == i

    def test_ev_math_matches_calculate_ev(self) -> None:
        """Verify EV numbers in step 4 match calculate_ev() output."""
        true_prob = 0.5
        best_price = -105.0
        steps = build_explanation_steps(
            **_PINNACLE_BASE,
            best_book="DraftKings",
            best_book_price=best_price,
            best_ev_percent=2.5,
        )
        ev_step = steps[3]
        assert ev_step["title"] == "Calculate EV at best price"

        expected_ev = calculate_ev(best_price, true_prob)
        ev_row = ev_step["detail_rows"][3]
        # Parse the EV value from the row (format: "+2.38%" or "-1.23%")
        ev_str = ev_row["value"].replace("%", "").strip()
        actual_ev = float(ev_str)
        assert abs(actual_ev - expected_ev) < 0.01
