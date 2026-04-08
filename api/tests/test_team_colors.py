"""Tests for app.services.team_colors."""


from app.services.team_colors import (
    NEUTRAL_DARK,
    NEUTRAL_LIGHT,
    color_distance,
    get_matchup_colors,
    hex_to_rgb,
)

# ---------------------------------------------------------------------------
# hex_to_rgb
# ---------------------------------------------------------------------------


class TestHexToRgb:
    def test_black(self):
        assert hex_to_rgb("#000000") == (0.0, 0.0, 0.0)

    def test_white(self):
        assert hex_to_rgb("#FFFFFF") == (1.0, 1.0, 1.0)

    def test_pure_red(self):
        assert hex_to_rgb("#FF0000") == (1.0, 0.0, 0.0)

    def test_arbitrary_color(self):
        r, g, b = hex_to_rgb("#1A2B3C")
        assert abs(r - 26 / 255) < 1e-6
        assert abs(g - 43 / 255) < 1e-6
        assert abs(b - 60 / 255) < 1e-6

    def test_lowercase_hex(self):
        assert hex_to_rgb("#aabbcc") == hex_to_rgb("#AABBCC")


# ---------------------------------------------------------------------------
# color_distance
# ---------------------------------------------------------------------------


class TestColorDistance:
    def test_identical_colors_zero(self):
        assert color_distance("#FF0000", "#FF0000") == 0.0

    def test_black_white_is_one(self):
        d = color_distance("#000000", "#FFFFFF")
        assert abs(d - 1.0) < 1e-6

    def test_symmetric(self):
        d1 = color_distance("#112233", "#AABBCC")
        d2 = color_distance("#AABBCC", "#112233")
        assert abs(d1 - d2) < 1e-9

    def test_range_is_0_to_1(self):
        d = color_distance("#FF0000", "#00FF00")
        assert 0.0 <= d <= 1.0


# ---------------------------------------------------------------------------
# get_matchup_colors — basic passthrough
# ---------------------------------------------------------------------------


class TestGetMatchupColors:
    def test_distinct_colors_pass_through(self):
        result = get_matchup_colors("#FF0000", "#CC0000", "#0000FF", "#0000CC")
        assert result["homeLightHex"] == "#FF0000"
        assert result["homeDarkHex"] == "#CC0000"
        assert result["awayLightHex"] == "#0000FF"
        assert result["awayDarkHex"] == "#0000CC"

    def test_home_always_keeps_primary(self):
        """Home never yields — away adapts."""
        result = get_matchup_colors("#FF0000", "#CC0000", "#FF0000", "#CC0000")
        assert result["homeLightHex"] == "#FF0000"
        assert result["homeDarkHex"] == "#CC0000"

    def test_none_colors_default_to_neutral(self):
        result = get_matchup_colors(None, None, None, None)
        assert result["homeLightHex"] == NEUTRAL_LIGHT
        assert result["homeDarkHex"] == NEUTRAL_DARK

    def test_one_side_none(self):
        result = get_matchup_colors(None, None, "#0000FF", "#0000CC")
        assert result["awayLightHex"] == "#0000FF"


# ---------------------------------------------------------------------------
# get_matchup_colors — clash detection with secondary fallback
# ---------------------------------------------------------------------------


class TestClashWithSecondary:
    def test_clash_falls_back_to_secondary(self):
        """Away primary clashes → away switches to secondary."""
        result = get_matchup_colors(
            "#FF0000", "#CC0000",  # home primary
            "#FF0000", "#CC0000",  # away primary (clashes)
            away_secondary_light="#0000FF",
            away_secondary_dark="#0000CC",
        )
        assert result["homeLightHex"] == "#FF0000"
        assert result["homeDarkHex"] == "#CC0000"
        assert result["awayLightHex"] == "#0000FF"
        assert result["awayDarkHex"] == "#0000CC"

    def test_clash_no_secondary_falls_to_neutral(self):
        """Away primary clashes, no secondary → away gets neutral."""
        result = get_matchup_colors(
            "#FF0000", "#CC0000",
            "#FF0000", "#CC0000",
        )
        assert result["awayLightHex"] == NEUTRAL_LIGHT
        assert result["awayDarkHex"] == NEUTRAL_DARK

    def test_clash_secondary_also_clashes_falls_to_neutral(self):
        """Away primary AND secondary both clash → neutral."""
        result = get_matchup_colors(
            "#FF0000", "#CC0000",
            "#FF0000", "#CC0000",
            away_secondary_light="#FE0000",  # still too close
            away_secondary_dark="#CB0000",
        )
        assert result["awayLightHex"] == NEUTRAL_LIGHT
        assert result["awayDarkHex"] == NEUTRAL_DARK

    def test_very_similar_colors_trigger_clash(self):
        """Colors differ by 1 unit in red — should clash."""
        result = get_matchup_colors(
            "#FF0000", "#CC0000",
            "#FE0000", "#CB0000",
            away_secondary_light="#0000FF",
            away_secondary_dark="#0000CC",
        )
        # Light clashes → secondary used
        assert result["awayLightHex"] == "#0000FF"

    def test_independent_light_dark_clash(self):
        """Light clashes but dark doesn't — resolved independently."""
        result = get_matchup_colors(
            "#FF0000", "#000066",  # home: red light, dark blue dark
            "#FE0000", "#FFFF00",  # away: red light (clashes), yellow dark (fine)
            away_secondary_light="#00FF00",
            away_secondary_dark="#009900",
        )
        # Light: away primary clashes, falls to secondary
        assert result["awayLightHex"] == "#00FF00"
        # Dark: away primary is fine (yellow vs dark blue)
        assert result["awayDarkHex"] == "#FFFF00"
