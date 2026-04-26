"""Tests for app.services.period_labels."""

from app.services.period_labels import period_label, time_label

# ---------------------------------------------------------------------------
# period_label
# ---------------------------------------------------------------------------


class TestPeriodLabelNBA:
    def test_quarters(self):
        assert period_label(1, "NBA") == "Q1"
        assert period_label(2, "NBA") == "Q2"
        assert period_label(3, "NBA") == "Q3"
        assert period_label(4, "NBA") == "Q4"

    def test_overtime(self):
        assert period_label(5, "NBA") == "OT"
        assert period_label(6, "NBA") == "2OT"
        assert period_label(7, "NBA") == "3OT"

    def test_case_insensitive(self):
        assert period_label(1, "nba") == "Q1"


class TestPeriodLabelNHL:
    def test_periods(self):
        assert period_label(1, "NHL") == "P1"
        assert period_label(2, "NHL") == "P2"
        assert period_label(3, "NHL") == "P3"

    def test_regular_season_overtime_and_shootout(self):
        # period_type from the source feed disambiguates: regular-season
        # period 5 is the shootout; playoff period 5 is the second OT.
        assert period_label(4, "NHL", "OT") == "OT"
        assert period_label(5, "NHL", "SO") == "SO"

    def test_playoff_multi_overtime(self):
        # Playoffs have no shootout; consecutive OTs increment the count.
        assert period_label(4, "NHL", "OT") == "OT"
        assert period_label(5, "NHL", "OT") == "2OT"
        assert period_label(6, "NHL", "OT") == "3OT"
        assert period_label(7, "NHL", "OT") == "4OT"

    def test_overtime_default_when_period_type_missing(self):
        # Without period_type, default to OT-numbering rather than guessing
        # shootout — wrong on regular-season period 5, but the source feed
        # always supplies period_type for NHL post-overtime plays.
        assert period_label(4, "NHL") == "OT"
        assert period_label(5, "NHL") == "2OT"


class TestPeriodLabelNCAAB:
    def test_halves(self):
        assert period_label(1, "NCAAB") == "H1"
        assert period_label(2, "NCAAB") == "H2"

    def test_overtime(self):
        assert period_label(3, "NCAAB") == "OT"
        assert period_label(4, "NCAAB") == "2OT"
        assert period_label(5, "NCAAB") == "3OT"


class TestPeriodLabelMLB:
    def test_regulation_innings(self):
        assert period_label(1, "MLB") == "1st"
        assert period_label(2, "MLB") == "2nd"
        assert period_label(3, "MLB") == "3rd"
        assert period_label(4, "MLB") == "4th"
        assert period_label(9, "MLB") == "9th"

    def test_extra_innings(self):
        assert period_label(10, "MLB") == "10th"
        assert period_label(11, "MLB") == "11th"
        assert period_label(12, "MLB") == "12th"

    def test_period_zero_clamped(self):
        """period=0 should be clamped to 1, not produce '0th'."""
        assert period_label(0, "MLB") == "1st"
        assert period_label(0, "NBA") == "Q1"


class TestPeriodLabelUnknownLeague:
    def test_defaults_to_nba_style(self):
        assert period_label(1, "WNBA") == "Q1"
        assert period_label(5, "WNBA") == "OT"


# ---------------------------------------------------------------------------
# time_label
# ---------------------------------------------------------------------------


class TestTimeLabel:
    def test_with_clock(self):
        assert time_label(4, "2:35", "NBA") == "Q4 2:35"
        assert time_label(3, "12:00", "NHL") == "P3 12:00"
        assert time_label(2, "5:15", "NCAAB") == "H2 5:15"

    def test_without_clock(self):
        assert time_label(1, None, "NBA") == "Q1"
        assert time_label(4, "", "NHL") == "OT"
