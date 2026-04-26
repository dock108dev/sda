"""Sport-aware period labels for play-by-play data."""

from __future__ import annotations


def period_label(
    period: int,
    league_code: str,
    period_type: str | None = None,
) -> str:
    """Return a display-ready period label.

    NBA:   Q1-Q4, OT, 2OT, 3OT …
    NHL:   P1-P3, OT, 2OT, 3OT …, SO  (SO requires period_type='SO')
    NCAAB: H1, H2, OT, 2OT, 3OT …
    """
    period = max(period, 1)  # Guard against period=0 from bad data
    code = league_code.upper()

    if code == "NHL":
        if period <= 3:
            return f"P{period}"
        # NHL distinguishes OT from shootout via the API's periodType field.
        # Regular season: period 4 = OT, period 5 = SO.  Playoffs: there is no
        # shootout and overtime continues with periods 5, 6, 7 = 2OT, 3OT, 4OT.
        # Falling back to "period == 4 ? OT : SO" mislabels playoff multi-OTs.
        ptype = (period_type or "").upper()
        if ptype == "SO":
            return "SO"
        ot_num = period - 3
        return "OT" if ot_num == 1 else f"{ot_num}OT"

    if code == "NCAAB":
        if period <= 2:
            return f"H{period}"
        ot_num = period - 2
        return "OT" if ot_num == 1 else f"{ot_num}OT"

    if code == "MLB":
        if period <= 9:
            ordinals = {1: "1st", 2: "2nd", 3: "3rd"}
            return ordinals.get(period, f"{period}th")
        return f"{period}th"  # extras

    # NBA (default)
    if period <= 4:
        return f"Q{period}"
    ot_num = period - 4
    return "OT" if ot_num == 1 else f"{ot_num}OT"


def time_label(
    period: int,
    game_clock: str | None,
    league_code: str,
    period_type: str | None = None,
) -> str:
    """Combine period label + game clock: "Q4 2:35", "P3 12:00", "H2 5:15"."""
    plabel = period_label(period, league_code, period_type)
    if game_clock:
        return f"{plabel} {game_clock}"
    return plabel
