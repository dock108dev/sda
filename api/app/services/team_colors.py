"""Team color utilities: hex conversion and clash detection.

Resolves game-level matchup colors so API consumers get final values
with no client-side color shifting needed. Home team always keeps its
primary colors; away team adapts (primary → secondary → neutral).
"""

from __future__ import annotations

import math

CLASH_THRESHOLD = 0.12
NEUTRAL_LIGHT = "#000000"  # black for light mode
NEUTRAL_DARK = "#FFFFFF"   # white for dark mode


def hex_to_rgb(hex_color: str) -> tuple[float, float, float]:
    """Convert '#RRGGBB' to normalized (0.0-1.0) RGB tuple."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return r / 255.0, g / 255.0, b / 255.0


def color_distance(c1: str, c2: str) -> float:
    """Normalized Euclidean distance in RGB space (0.0-1.0).

    Max possible RGB distance is sqrt(3) ≈ 1.732, so we normalize by that.
    """
    r1, g1, b1 = hex_to_rgb(c1)
    r2, g2, b2 = hex_to_rgb(c2)
    dr = r1 - r2
    dg = g1 - g2
    db = b1 - b2
    return math.sqrt(dr * dr + dg * dg + db * db) / math.sqrt(3)


def _pick_away_color(
    home_color: str,
    away_primary: str | None,
    away_secondary: str | None,
    neutral: str,
) -> str:
    """Pick the best away color that doesn't clash with home.

    Priority: primary → secondary → neutral.
    """
    if away_primary and color_distance(home_color, away_primary) >= CLASH_THRESHOLD:
        return away_primary
    if away_secondary and color_distance(home_color, away_secondary) >= CLASH_THRESHOLD:
        return away_secondary
    return neutral


def get_matchup_colors(
    home_color_light: str | None,
    home_color_dark: str | None,
    away_color_light: str | None,
    away_color_dark: str | None,
    away_secondary_light: str | None = None,
    away_secondary_dark: str | None = None,
) -> dict[str, str]:
    """Return matchup-aware colors. Away team adapts on clash; home keeps primary.

    Clash resolution is done independently for light and dark modes:
    - Home always uses its primary colors
    - Away uses primary unless it clashes with home, then secondary, then neutral

    Returns dict with keys: homeLightHex, homeDarkHex, awayLightHex, awayDarkHex.
    """
    h_light = home_color_light or NEUTRAL_LIGHT
    h_dark = home_color_dark or NEUTRAL_DARK

    a_light = _pick_away_color(
        h_light,
        away_color_light,
        away_secondary_light,
        NEUTRAL_LIGHT,
    )
    a_dark = _pick_away_color(
        h_dark,
        away_color_dark,
        away_secondary_dark,
        NEUTRAL_DARK,
    )

    return {
        "homeLightHex": h_light,
        "homeDarkHex": h_dark,
        "awayLightHex": a_light,
        "awayDarkHex": a_dark,
    }
