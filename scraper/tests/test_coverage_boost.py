"""Targeted tests to push coverage over 90%."""

from __future__ import annotations


class TestClassifyMarket:
    """Cover classify_market branches in models/schemas.py."""

    def test_mainline_h2h(self):
        from sports_scraper.models.schemas import classify_market
        assert classify_market("h2h") == "mainline"

    def test_mainline_spreads(self):
        from sports_scraper.models.schemas import classify_market
        assert classify_market("spreads") == "mainline"

    def test_mainline_totals(self):
        from sports_scraper.models.schemas import classify_market
        assert classify_market("totals") == "mainline"

    def test_player_prop(self):
        from sports_scraper.models.schemas import classify_market
        assert classify_market("player_points") == "player_prop"

    def test_batter_prop(self):
        from sports_scraper.models.schemas import classify_market
        assert classify_market("batter_hits") == "player_prop"

    def test_pitcher_prop(self):
        from sports_scraper.models.schemas import classify_market
        assert classify_market("pitcher_strikeouts") == "player_prop"

    def test_team_total(self):
        from sports_scraper.models.schemas import classify_market
        assert classify_market("team_totals") == "team_prop"

    def test_alternate(self):
        from sports_scraper.models.schemas import classify_market
        assert classify_market("alternate_spreads") == "alternate"

    def test_period_h1(self):
        from sports_scraper.models.schemas import classify_market
        assert classify_market("spreads_h1") == "period"

    def test_period_q2(self):
        from sports_scraper.models.schemas import classify_market
        assert classify_market("totals_q2") == "period"

    def test_period_p1(self):
        from sports_scraper.models.schemas import classify_market
        assert classify_market("h2h_p1") == "period"

    def test_period_q3(self):
        from sports_scraper.models.schemas import classify_market
        assert classify_market("totals_q3") == "period"

    def test_period_q4(self):
        from sports_scraper.models.schemas import classify_market
        assert classify_market("totals_q4") == "period"

    def test_period_h2(self):
        from sports_scraper.models.schemas import classify_market
        assert classify_market("totals_h2") == "period"

    def test_period_p2(self):
        from sports_scraper.models.schemas import classify_market
        assert classify_market("h2h_p2") == "period"

    def test_period_p3(self):
        from sports_scraper.models.schemas import classify_market
        assert classify_market("h2h_p3") == "period"

    def test_game_prop_fallback(self):
        from sports_scraper.models.schemas import classify_market
        assert classify_market("draw_no_bet") == "game_prop"

    def test_case_insensitive(self):
        from sports_scraper.models.schemas import classify_market
        assert classify_market("H2H") == "mainline"
        assert classify_market("Player_Points") == "player_prop"
