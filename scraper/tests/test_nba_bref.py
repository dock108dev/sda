"""Tests for NBA Basketball Reference scraper and helpers."""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRAPER_ROOT = REPO_ROOT / "scraper"
if str(SCRAPER_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRAPER_ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/test_db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ENVIRONMENT", "development")

from bs4 import BeautifulSoup

from sports_scraper.models import TeamIdentity
from sports_scraper.scrapers.nba_bref import NBABasketballReferenceScraper
from sports_scraper.scrapers.base import ScraperError
from sports_scraper.scrapers.nba_bref_helpers import (
    _classify_play,
    _detect_period_from_text,
    _parse_minutes,
    _parse_pbp_row,
    extract_player_stats,
    extract_team_stats,
    parse_pbp_table,
)


# ── Sample HTML fixtures ──


SAMPLE_SCOREBOARD_HTML = """
<html><body>
<div class="game_summary">
  <table class="teams">
    <tr><td><a href="/teams/NYK/2025.html">New York Knicks</a></td><td>109</td></tr>
    <tr><td><a href="/teams/BOS/2025.html">Boston Celtics</a></td><td>132</td></tr>
  </table>
  <p class="links"><a href="/boxscores/202410220BOS.html">Box Score</a></p>
</div>
<div class="game_summary">
  <table class="teams">
    <tr><td><a href="/teams/MIN/2025.html">Minnesota Timberwolves</a></td><td>110</td></tr>
    <tr><td><a href="/teams/LAL/2025.html">Los Angeles Lakers</a></td><td>103</td></tr>
  </table>
  <p class="links"><a href="/boxscores/202410220LAL.html">Box Score</a></p>
</div>
</body></html>
"""


SAMPLE_BOXSCORE_HTML = """
<html><body>
<div class="scorebox">
  <div><strong><a href="/teams/NYK/2025.html" itemprop="name">New York Knicks</a></strong></div>
  <div><strong><a href="/teams/BOS/2025.html" itemprop="name">Boston Celtics</a></strong></div>
</div>
<table id="box-NYK-game-basic">
  <thead><tr><th>Starters</th><th data-stat="mp">MP</th><th data-stat="fg">FG</th><th data-stat="fga">FGA</th><th data-stat="fg_pct">FG%</th><th data-stat="fg3">3P</th><th data-stat="fg3a">3PA</th><th data-stat="fg3_pct">3P%</th><th data-stat="ft">FT</th><th data-stat="fta">FTA</th><th data-stat="ft_pct">FT%</th><th data-stat="orb">ORB</th><th data-stat="drb">DRB</th><th data-stat="trb">TRB</th><th data-stat="ast">AST</th><th data-stat="stl">STL</th><th data-stat="blk">BLK</th><th data-stat="tov">TOV</th><th data-stat="pf">PF</th><th data-stat="pts">PTS</th><th data-stat="plus_minus">+/-</th></tr></thead>
  <tbody>
    <tr><th data-stat="player"><a href="/players/b/bridgmi01.html">Mikal Bridges</a></th><td data-stat="mp">34:37</td><td data-stat="fg">5</td><td data-stat="fga">18</td><td data-stat="fg_pct">.278</td><td data-stat="fg3">2</td><td data-stat="fg3a">8</td><td data-stat="fg3_pct">.250</td><td data-stat="ft">0</td><td data-stat="fta">0</td><td data-stat="ft_pct"></td><td data-stat="orb">0</td><td data-stat="drb">5</td><td data-stat="trb">5</td><td data-stat="ast">3</td><td data-stat="stl">0</td><td data-stat="blk">0</td><td data-stat="tov">1</td><td data-stat="pf">2</td><td data-stat="pts">12</td><td data-stat="plus_minus">-33</td></tr>
    <tr><th data-stat="player"><a href="/players/t/townska01.html">Karl-Anthony Towns</a></th><td data-stat="mp">28:15</td><td data-stat="fg">7</td><td data-stat="fga">12</td><td data-stat="fg_pct">.583</td><td data-stat="fg3">1</td><td data-stat="fg3a">3</td><td data-stat="fg3_pct">.333</td><td data-stat="ft">1</td><td data-stat="fta">1</td><td data-stat="ft_pct">1.000</td><td data-stat="orb">2</td><td data-stat="drb">10</td><td data-stat="trb">12</td><td data-stat="ast">0</td><td data-stat="stl">0</td><td data-stat="blk">3</td><td data-stat="tov">2</td><td data-stat="pf">4</td><td data-stat="pts">16</td><td data-stat="plus_minus">-25</td></tr>
    <tr><th data-stat="player">Did Not Play</th></tr>
  </tbody>
  <tfoot>
    <tr><td data-stat="player">Team Totals</td><td data-stat="mp">240</td><td data-stat="fg">37</td><td data-stat="fga">89</td><td data-stat="fg_pct">.416</td><td data-stat="fg3">12</td><td data-stat="fg3a">37</td><td data-stat="fg3_pct">.324</td><td data-stat="ft">23</td><td data-stat="fta">28</td><td data-stat="ft_pct">.821</td><td data-stat="orb">7</td><td data-stat="drb">30</td><td data-stat="trb">37</td><td data-stat="ast">22</td><td data-stat="stl">5</td><td data-stat="blk">4</td><td data-stat="tov">15</td><td data-stat="pf">20</td><td data-stat="pts">109</td><td data-stat="plus_minus"></td></tr>
  </tfoot>
</table>
<table id="box-BOS-game-basic">
  <thead><tr><th>Starters</th><th data-stat="mp">MP</th><th data-stat="pts">PTS</th><th data-stat="trb">TRB</th><th data-stat="ast">AST</th></tr></thead>
  <tbody>
    <tr><th data-stat="player"><a href="/players/t/tatMDJ01.html">Jayson Tatum</a></th><td data-stat="mp">32:00</td><td data-stat="pts">37</td><td data-stat="trb">10</td><td data-stat="ast">5</td></tr>
  </tbody>
  <tfoot>
    <tr><td data-stat="player">Team Totals</td><td data-stat="mp">240</td><td data-stat="pts">132</td><td data-stat="trb">52</td><td data-stat="ast">30</td></tr>
  </tfoot>
</table>
</body></html>
"""


SAMPLE_PBP_HTML = """
<html><body>
<div id="all_pbp">
<table id="pbp">
  <tbody>
    <tr id="q1"><td colspan="6"><b>1st Quarter</b></td></tr>
    <tr><td>12:00.0</td><td>Jump ball: K. Towns vs. A. Horford</td><td></td><td></td><td></td><td></td></tr>
    <tr><td>11:48.0</td><td></td><td></td><td>2-0</td><td>J. Tatum makes 2-pt shot from 15 ft</td><td></td></tr>
    <tr><td>11:30.0</td><td>M. Bridges misses 3-pt shot from 27 ft</td><td></td><td></td><td></td><td></td></tr>
    <tr><td>11:22.0</td><td></td><td></td><td></td><td>D. White defensive rebound</td><td></td></tr>
    <tr id="q2"><td colspan="6"><b>2nd Quarter</b></td></tr>
    <tr><td>12:00.0</td><td></td><td></td><td>30-25</td><td>J. Brown makes free throw 1 of 2</td><td></td></tr>
  </tbody>
</table>
</div>
</body></html>
"""


# ── Helper tests ──


class TestParseMinutes:
    def test_mm_ss_format(self):
        assert _parse_minutes("36:12") == 36.2

    def test_mm_ss_zero_seconds(self):
        assert _parse_minutes("28:00") == 28.0

    def test_plain_number(self):
        assert _parse_minutes("40") == 40.0

    def test_none(self):
        assert _parse_minutes(None) is None

    def test_empty(self):
        assert _parse_minutes("") is None


class TestClassifyPlay:
    def test_three_pointer(self):
        assert _classify_play("J. Tatum makes 3-pt shot") == "3pt"

    def test_two_pointer(self):
        assert _classify_play("J. Tatum makes 2-pt shot from 15 ft") == "2pt"

    def test_free_throw(self):
        assert _classify_play("J. Brown makes free throw 1 of 2") == "ft"

    def test_miss(self):
        assert _classify_play("M. Bridges misses 3-pt shot") == "miss"

    def test_rebound(self):
        assert _classify_play("D. White defensive rebound") == "rebound"

    def test_turnover(self):
        assert _classify_play("K. Towns bad pass turnover") == "turnover"

    def test_foul(self):
        assert _classify_play("M. Bridges personal foul") == "foul"

    def test_substitution(self):
        assert _classify_play("J. Sims enters the game for K. Towns") == "substitution"

    def test_timeout(self):
        assert _classify_play("Boston timeout") == "timeout"

    def test_unknown(self):
        assert _classify_play("some other play") is None


class TestDetectPeriodFromText:
    def test_first_quarter(self):
        assert _detect_period_from_text("1st Quarter") == 1

    def test_fourth_quarter(self):
        assert _detect_period_from_text("4th quarter") == 4

    def test_overtime(self):
        assert _detect_period_from_text("Overtime") == 5

    def test_second_overtime(self):
        assert _detect_period_from_text("2nd Overtime") == 6

    def test_unrelated(self):
        assert _detect_period_from_text("something else") is None


# ── Team stats extraction ──


class TestExtractTeamStats:
    def test_extract_from_tfoot(self):
        soup = BeautifulSoup(SAMPLE_BOXSCORE_HTML, "lxml")
        stats = extract_team_stats(soup, "NYK")
        assert stats["fg"] == 37
        assert stats["fga"] == 89
        assert stats["pts"] == 109
        assert stats["trb"] == 37
        assert stats["ast"] == 22

    def test_missing_table(self):
        soup = BeautifulSoup("<html></html>", "lxml")
        stats = extract_team_stats(soup, "XYZ")
        assert stats == {}


# ── Player stats extraction ──


class TestExtractPlayerStats:
    def test_extract_players(self):
        soup = BeautifulSoup(SAMPLE_BOXSCORE_HTML, "lxml")
        team = TeamIdentity(league_code="NBA", name="New York Knicks", abbreviation="NYK")
        players = extract_player_stats(soup, "NYK", team)
        assert len(players) == 2  # Bridges + Towns (DNP row skipped)

        bridges = players[0]
        assert bridges.player_name == "Mikal Bridges"
        assert bridges.player_id == "bridgmi01"
        assert bridges.points == 12
        assert bridges.rebounds == 5
        assert bridges.assists == 3
        assert bridges.minutes == 34.6  # 34:37 → 34.6

        towns = players[1]
        assert towns.player_name == "Karl-Anthony Towns"
        assert towns.points == 16
        assert towns.rebounds == 12

    def test_missing_table(self):
        soup = BeautifulSoup("<html></html>", "lxml")
        team = TeamIdentity(league_code="NBA", name="Test", abbreviation="TST")
        players = extract_player_stats(soup, "TST", team)
        assert players == []

    def test_bos_players(self):
        soup = BeautifulSoup(SAMPLE_BOXSCORE_HTML, "lxml")
        team = TeamIdentity(league_code="NBA", name="Boston Celtics", abbreviation="BOS")
        players = extract_player_stats(soup, "BOS", team)
        assert len(players) == 1
        assert players[0].player_name == "Jayson Tatum"
        assert players[0].points == 37


# ── PBP parsing ──


class TestParsePbpTable:
    def test_parse_plays(self):
        soup = BeautifulSoup(SAMPLE_PBP_HTML, "lxml")
        plays = parse_pbp_table(soup)
        assert len(plays) >= 4  # At least the non-header rows

        # First play should be jump ball (Q1)
        assert plays[0].quarter == 1
        assert plays[0].game_clock == "12:00"
        assert "jump ball" in plays[0].description.lower()

        # Second play — Tatum 2pt
        tatum_play = plays[1]
        assert tatum_play.quarter == 1
        assert tatum_play.game_clock == "11:48"
        assert tatum_play.play_type == "2pt"
        assert tatum_play.home_score == 0  # Score is away-home: 2-0
        assert tatum_play.away_score == 2

    def test_period_changes(self):
        soup = BeautifulSoup(SAMPLE_PBP_HTML, "lxml")
        plays = parse_pbp_table(soup)
        # Last play should be in Q2
        q2_plays = [p for p in plays if p.quarter == 2]
        assert len(q2_plays) >= 1
        assert q2_plays[0].play_type == "ft"

    def test_empty_page(self):
        soup = BeautifulSoup("<html></html>", "lxml")
        plays = parse_pbp_table(soup)
        assert plays == []

    def test_play_index_ordering(self):
        soup = BeautifulSoup(SAMPLE_PBP_HTML, "lxml")
        plays = parse_pbp_table(soup)
        indices = [p.play_index for p in plays]
        # Q1 plays should be 10000+, Q2 should be 20000+
        q1_indices = [i for i in indices if 10000 <= i < 20000]
        q2_indices = [i for i in indices if 20000 <= i < 30000]
        assert len(q1_indices) >= 1
        assert len(q2_indices) >= 1


# ── Scraper class tests ──


class TestNBABasketballReferenceScraper:
    def test_scoreboard_url(self):
        scraper = NBABasketballReferenceScraper()
        url = scraper.scoreboard_url(date(2024, 10, 22))
        assert url == "https://www.basketball-reference.com/boxscores/?month=10&day=22&year=2024"

    def test_pbp_url(self):
        scraper = NBABasketballReferenceScraper()
        url = scraper.pbp_url("202410220BOS")
        assert url == "https://www.basketball-reference.com/boxscores/pbp/202410220BOS.html"

    def test_parse_team_row(self):
        html = '<tr><td><a href="/teams/BOS/2025.html">Boston Celtics</a></td><td>132</td></tr>'
        row = BeautifulSoup(html, "lxml").find("tr")
        scraper = NBABasketballReferenceScraper()
        identity, score = scraper._parse_team_row(row)
        assert identity.name == "Boston Celtics"
        assert identity.abbreviation == "BOS"
        assert score == 132

    def test_parse_team_row_missing_link(self):
        html = "<tr><td>No Team</td><td>100</td></tr>"
        row = BeautifulSoup(html, "lxml").find("tr")
        scraper = NBABasketballReferenceScraper()
        try:
            scraper._parse_team_row(row)
            assert False, "Should have raised ScraperError"
        except Exception:
            pass

    def test_unwrap_commented_tables(self):
        html = """
        <html><body>
        <!-- <table id="box-BOS-game-basic"><tbody><tr><th data-stat="player"><a href="/p/test.html">Test Player</a></th></tr></tbody></table> -->
        </body></html>
        """
        soup = BeautifulSoup(html, "lxml")
        scraper = NBABasketballReferenceScraper()
        scraper._unwrap_commented_tables(soup)
        table = soup.find("table", id="box-BOS-game-basic")
        assert table is not None

    @patch.object(NBABasketballReferenceScraper, "fetch_html")
    def test_fetch_games_for_date(self, mock_fetch):
        """Test full game parsing with mocked HTML."""
        scoreboard_soup = BeautifulSoup(SAMPLE_SCOREBOARD_HTML, "lxml")
        boxscore_soup = BeautifulSoup(SAMPLE_BOXSCORE_HTML, "lxml")

        # First call is scoreboard, second is boxscore for game 1, third for game 2
        mock_fetch.side_effect = [scoreboard_soup, boxscore_soup, boxscore_soup]

        scraper = NBABasketballReferenceScraper()
        games = scraper.fetch_games_for_date(date(2024, 10, 22))

        assert len(games) == 2

        game1 = games[0]
        assert game1.identity.source_game_key == "202410220BOS"
        assert game1.home_score == 132
        assert game1.away_score == 109
        assert game1.identity.home_team.abbreviation == "BOS"
        assert game1.identity.away_team.abbreviation == "NYK"
        assert len(game1.team_boxscores) == 2
        assert len(game1.player_boxscores) >= 2

    def test_parse_scorebox_abbreviations(self):
        soup = BeautifulSoup(SAMPLE_BOXSCORE_HTML, "lxml")
        scraper = NBABasketballReferenceScraper()
        away, home = scraper._parse_scorebox_abbreviations(soup)
        assert away == "NYK"
        assert home == "BOS"

    # ── Coverage: nba_bref.py line 87 — score is None raises ScraperError ──

    def test_parse_team_row_no_score(self):
        """Row has a team link but no parseable score in td cells."""
        html = '<tr><td><a href="/teams/BOS/2025.html">Boston Celtics</a></td><td>N/A</td></tr>'
        row = BeautifulSoup(html, "lxml").find("tr")
        scraper = NBABasketballReferenceScraper()
        import pytest

        with pytest.raises(ScraperError, match="Could not parse score"):
            scraper._parse_team_row(row)

    # ── Coverage: nba_bref.py lines 102, 106 — scorebox edge cases ──

    def test_parse_scorebox_no_scorebox(self):
        """No scorebox div at all → (None, None)."""
        soup = BeautifulSoup("<html><body></body></html>", "lxml")
        scraper = NBABasketballReferenceScraper()
        assert scraper._parse_scorebox_abbreviations(soup) == (None, None)

    def test_parse_scorebox_fewer_than_2_divs(self):
        """Scorebox with only one direct child div → (None, None)."""
        html = '<html><body><div class="scorebox"><div>Only one</div></div></body></html>'
        soup = BeautifulSoup(html, "lxml")
        scraper = NBABasketballReferenceScraper()
        assert scraper._parse_scorebox_abbreviations(soup) == (None, None)

    # ── Coverage: nba_bref.py lines 112-113 — strong>a fallback ──

    def test_parse_scorebox_strong_a_fallback(self):
        """No itemprop='name' but has strong>a with /teams/ href."""
        html = """
        <html><body><div class="scorebox">
          <div><strong><a href="/teams/LAL/2025.html">Los Angeles Lakers</a></strong></div>
          <div><strong><a href="/teams/GSW/2025.html">Golden State Warriors</a></strong></div>
        </div></body></html>
        """
        soup = BeautifulSoup(html, "lxml")
        scraper = NBABasketballReferenceScraper()
        away, home = scraper._parse_scorebox_abbreviations(soup)
        assert away == "LAL"
        assert home == "GSW"

    # ── Coverage: nba_bref.py lines 116-120 — /teams/ link fallback ──

    def test_parse_scorebox_teams_link_fallback(self):
        """No itemprop, no strong, but has an <a> with /teams/ in href."""
        html = """
        <html><body><div class="scorebox">
          <div><a href="/teams/MIA/2025.html">Miami Heat</a></div>
          <div><a href="/teams/CHI/2025.html">Chicago Bulls</a></div>
        </div></body></html>
        """
        soup = BeautifulSoup(html, "lxml")
        scraper = NBABasketballReferenceScraper()
        away, home = scraper._parse_scorebox_abbreviations(soup)
        assert away == "MIA"
        assert home == "CHI"

    # ── Coverage: nba_bref.py line 122 — no link at all → None ──

    def test_parse_scorebox_no_links(self):
        """Scorebox divs with no links at all → parse_abbr returns None."""
        html = """
        <html><body><div class="scorebox">
          <div><span>Team A</span></div>
          <div><span>Team B</span></div>
        </div></body></html>
        """
        soup = BeautifulSoup(html, "lxml")
        scraper = NBABasketballReferenceScraper()
        away, home = scraper._parse_scorebox_abbreviations(soup)
        assert away is None
        assert home is None

    # ── Coverage: nba_bref.py lines 130-132 — href without /teams/ falls back to normalize ──

    def test_parse_scorebox_no_teams_in_href(self):
        """Link href doesn't contain /teams/ → falls back to normalize_team_name."""
        html = """
        <html><body><div class="scorebox">
          <div><a itemprop="name" href="/other/Boston-Celtics">Boston Celtics</a></div>
          <div><a itemprop="name" href="/other/New-York-Knicks">New York Knicks</a></div>
        </div></body></html>
        """
        soup = BeautifulSoup(html, "lxml")
        scraper = NBABasketballReferenceScraper()
        away, home = scraper._parse_scorebox_abbreviations(soup)
        assert away == "BOS"
        assert home == "NYK"

    # ── Coverage: nba_bref.py lines 163-164 — fewer than 2 team rows → skip ──

    @patch.object(NBABasketballReferenceScraper, "fetch_html")
    def test_fetch_games_skips_incomplete_game_div(self, mock_fetch):
        """Game div with < 2 team rows should be skipped."""
        html = """
        <html><body>
        <div class="game_summary">
          <table class="teams">
            <tr><td><a href="/teams/BOS/2025.html">Boston Celtics</a></td><td>100</td></tr>
          </table>
        </div>
        </body></html>
        """
        mock_fetch.return_value = BeautifulSoup(html, "lxml")
        scraper = NBABasketballReferenceScraper()
        games = scraper.fetch_games_for_date(date(2024, 10, 22))
        assert len(games) == 0

    # ── Coverage: nba_bref.py lines 169-172 — ScraperError in _parse_team_row → skip ──

    @patch.object(NBABasketballReferenceScraper, "fetch_html")
    def test_fetch_games_skips_on_parse_error(self, mock_fetch):
        """If _parse_team_row raises ScraperError, the game is skipped."""
        html = """
        <html><body>
        <div class="game_summary">
          <table class="teams">
            <tr><td><a href="/teams/BOS/2025.html">Boston Celtics</a></td><td>N/A</td></tr>
            <tr><td><a href="/teams/NYK/2025.html">New York Knicks</a></td><td>110</td></tr>
          </table>
        </div>
        </body></html>
        """
        mock_fetch.return_value = BeautifulSoup(html, "lxml")
        scraper = NBABasketballReferenceScraper()
        games = scraper.fetch_games_for_date(date(2024, 10, 22))
        assert len(games) == 0

    # ── Coverage: nba_bref.py lines 180-181 — no boxscore link → skip ──

    @patch.object(NBABasketballReferenceScraper, "fetch_html")
    def test_fetch_games_skips_no_boxscore_link(self, mock_fetch):
        """Game div with valid teams but no boxscore link should be skipped."""
        html = """
        <html><body>
        <div class="game_summary">
          <table class="teams">
            <tr><td><a href="/teams/BOS/2025.html">Boston Celtics</a></td><td>100</td></tr>
            <tr><td><a href="/teams/NYK/2025.html">New York Knicks</a></td><td>110</td></tr>
          </table>
          <p class="links"><a href="/some-other-page.html">Recap</a></p>
        </div>
        </body></html>
        """
        mock_fetch.return_value = BeautifulSoup(html, "lxml")
        scraper = NBABasketballReferenceScraper()
        games = scraper.fetch_games_for_date(date(2024, 10, 22))
        assert len(games) == 0

    # ── Coverage: nba_bref.py lines 195-196 — fallback abbreviations ──

    @patch.object(NBABasketballReferenceScraper, "fetch_html")
    def test_fetch_games_fallback_abbreviations(self, mock_fetch):
        """When scorebox parse returns None, identity abbreviations are used."""
        scoreboard_html = """
        <html><body>
        <div class="game_summary">
          <table class="teams">
            <tr><td><a href="/teams/NYK/2025.html">New York Knicks</a></td><td>109</td></tr>
            <tr><td><a href="/teams/BOS/2025.html">Boston Celtics</a></td><td>132</td></tr>
          </table>
          <p class="links"><a href="/boxscores/202410220BOS.html">Box Score</a></p>
        </div>
        </body></html>
        """
        # Boxscore page without a scorebox → will fall back to identity abbreviations
        boxscore_html = """
        <html><body>
        <table id="box-NYK-game-basic">
          <tfoot><tr><td data-stat="player">Team Totals</td><td data-stat="pts">109</td></tr></tfoot>
        </table>
        <table id="box-BOS-game-basic">
          <tfoot><tr><td data-stat="player">Team Totals</td><td data-stat="pts">132</td></tr></tfoot>
        </table>
        </body></html>
        """
        mock_fetch.side_effect = [
            BeautifulSoup(scoreboard_html, "lxml"),
            BeautifulSoup(boxscore_html, "lxml"),
        ]
        scraper = NBABasketballReferenceScraper()
        games = scraper.fetch_games_for_date(date(2024, 10, 22))
        assert len(games) == 1
        assert games[0].identity.away_team.abbreviation == "NYK"
        assert games[0].identity.home_team.abbreviation == "BOS"

    # ── Coverage: nba_bref.py lines 238-247 — fetch_play_by_play ──

    @patch.object(NBABasketballReferenceScraper, "fetch_html")
    def test_fetch_play_by_play(self, mock_fetch):
        mock_fetch.return_value = BeautifulSoup(SAMPLE_PBP_HTML, "lxml")
        scraper = NBABasketballReferenceScraper()
        pbp = scraper.fetch_play_by_play("202410220BOS", date(2024, 10, 22))
        assert pbp.source_game_key == "202410220BOS"
        assert len(pbp.plays) >= 4

    # ── Coverage: _unwrap_commented_tables with box- comment ──

    def test_unwrap_commented_tables_box_comment(self):
        """Commented table with box- prefix should be unwrapped into DOM."""
        html = """<html><body>
        <!--
        <table id="box-NYK-game-basic"><tbody>
        <tr><th data-stat="player"><a href="/p/test.html">Test</a></th></tr>
        </tbody></table>
        -->
        </body></html>"""
        soup = BeautifulSoup(html, "lxml")
        scraper = NBABasketballReferenceScraper()
        # Before unwrap, table should not be found
        assert soup.find("table", id="box-NYK-game-basic") is None
        scraper._unwrap_commented_tables(soup)
        assert soup.find("table", id="box-NYK-game-basic") is not None


# ── Additional helper coverage tests ──


class TestExtractTeamStatsCaseInsensitive:
    """Coverage for nba_bref_helpers.py lines 40-43: case-insensitive table lookup."""

    def test_case_insensitive_table_id(self):
        """Table with different casing should still be found."""
        html = """<html><body>
        <table id="box-bos-game-basic">
          <tfoot><tr>
            <td data-stat="player">Team Totals</td>
            <td data-stat="pts">100</td>
            <td data-stat="trb">40</td>
          </tr></tfoot>
        </table>
        </body></html>"""
        soup = BeautifulSoup(html, "lxml")
        stats = extract_team_stats(soup, "BOS")
        assert stats["pts"] == 100

    def test_extract_team_stats_value_types(self):
        """Coverage for lines 55, 60-64: empty, float (via parse_float), and string values."""
        html = """<html><body>
        <table id="box-TST-game-basic">
          <tfoot><tr>
            <td data-stat="player">Team Totals</td>
            <td data-stat="pts">100</td>
            <td data-stat="mp">32:45</td>
            <td data-stat="empty_stat"></td>
            <td data-stat="note">some text value</td>
          </tr></tfoot>
        </table>
        </body></html>"""
        soup = BeautifulSoup(html, "lxml")
        stats = extract_team_stats(soup, "TST")
        assert stats["pts"] == 100
        # "32:45" fails parse_int (ValueError on ":"), hits parse_float path → 32.75
        assert stats["mp"] == 32.75
        # Empty stat should not be in the result
        assert "empty_stat" not in stats
        # Non-numeric string that fails both parse_int and parse_float → stored as string
        assert stats["note"] == "some text value"


class TestExtractPlayerStatsCaseInsensitive:
    """Coverage for nba_bref_helpers.py lines 81-84: case-insensitive player table lookup."""

    def test_case_insensitive_player_table(self):
        html = """<html><body>
        <table id="box-bos-game-basic">
          <tbody>
            <tr><th data-stat="player"><a href="/players/t/tatumja01.html">Jayson Tatum</a></th>
            <td data-stat="mp">32:00</td><td data-stat="pts">30</td></tr>
          </tbody>
        </table>
        </body></html>"""
        soup = BeautifulSoup(html, "lxml")
        team = TeamIdentity(league_code="NBA", name="Boston Celtics", abbreviation="BOS")
        players = extract_player_stats(soup, "BOS", team)
        assert len(players) == 1
        assert players[0].player_name == "Jayson Tatum"


class TestExtractPlayerStatsEdgeCases:
    """Coverage for nba_bref_helpers.py lines 93, 98, 103, 112, 122, 129."""

    def test_no_tbody(self):
        """Table with no tbody → empty player list (line 93)."""
        html = """<html><body>
        <table id="box-TST-game-basic">
          <thead><tr><th>Header</th></tr></thead>
        </table>
        </body></html>"""
        soup = BeautifulSoup(html, "lxml")
        team = TeamIdentity(league_code="NBA", name="Test", abbreviation="TST")
        players = extract_player_stats(soup, "TST", team)
        assert players == []

    def test_thead_row_skipped(self):
        """Rows with class 'thead' should be skipped (line 98)."""
        html = """<html><body>
        <table id="box-TST-game-basic">
          <tbody>
            <tr class="thead"><th data-stat="player">Reserves</th></tr>
            <tr><th data-stat="player"><a href="/players/x/xxx01.html">Player A</a></th>
            <td data-stat="mp">10:00</td><td data-stat="pts">5</td></tr>
          </tbody>
        </table>
        </body></html>"""
        soup = BeautifulSoup(html, "lxml")
        team = TeamIdentity(league_code="NBA", name="Test", abbreviation="TST")
        players = extract_player_stats(soup, "TST", team)
        assert len(players) == 1

    def test_no_player_cell(self):
        """Row with no th[data-stat='player'] is skipped (line 103)."""
        html = """<html><body>
        <table id="box-TST-game-basic">
          <tbody>
            <tr><td>Some random cell</td></tr>
            <tr><th data-stat="player"><a href="/players/x/xxx01.html">Player A</a></th>
            <td data-stat="mp">10:00</td><td data-stat="pts">5</td></tr>
          </tbody>
        </table>
        </body></html>"""
        soup = BeautifulSoup(html, "lxml")
        team = TeamIdentity(league_code="NBA", name="Test", abbreviation="TST")
        players = extract_player_stats(soup, "TST", team)
        assert len(players) == 1

    def test_dnp_text_in_player_cell(self):
        """Player cell with text but no link (DNP entry) is skipped (line 112)."""
        html = """<html><body>
        <table id="box-TST-game-basic">
          <tbody>
            <tr><th data-stat="player">Did Not Play</th></tr>
            <tr><th data-stat="player">Did Not Dress</th></tr>
            <tr><th data-stat="player"><a href="/players/x/xxx01.html">Player A</a></th>
            <td data-stat="mp">20:00</td><td data-stat="pts">10</td></tr>
          </tbody>
        </table>
        </body></html>"""
        soup = BeautifulSoup(html, "lxml")
        team = TeamIdentity(league_code="NBA", name="Test", abbreviation="TST")
        players = extract_player_stats(soup, "TST", team)
        assert len(players) == 1
        assert players[0].player_name == "Player A"

    def test_reason_cell_skips_player(self):
        """Row with a reason cell (DNP/DND detail) is skipped (line 122)."""
        html = """<html><body>
        <table id="box-TST-game-basic">
          <tbody>
            <tr><th data-stat="player"><a href="/players/x/xxx01.html">Injured Player</a></th>
            <td data-stat="reason">Left Knee Injury</td></tr>
            <tr><th data-stat="player"><a href="/players/y/yyy01.html">Active Player</a></th>
            <td data-stat="mp">25:00</td><td data-stat="pts">15</td></tr>
          </tbody>
        </table>
        </body></html>"""
        soup = BeautifulSoup(html, "lxml")
        team = TeamIdentity(league_code="NBA", name="Test", abbreviation="TST")
        players = extract_player_stats(soup, "TST", team)
        assert len(players) == 1
        assert players[0].player_name == "Active Player"

    def test_mp_did_not_play_skipped(self):
        """Row where mp cell says 'Did Not Play' is skipped (line 129)."""
        html = """<html><body>
        <table id="box-TST-game-basic">
          <tbody>
            <tr><th data-stat="player"><a href="/players/x/xxx01.html">Benched</a></th>
            <td data-stat="mp">Did Not Play</td></tr>
            <tr><th data-stat="player"><a href="/players/y/yyy01.html">Active</a></th>
            <td data-stat="mp">30:00</td><td data-stat="pts">20</td></tr>
          </tbody>
        </table>
        </body></html>"""
        soup = BeautifulSoup(html, "lxml")
        team = TeamIdentity(league_code="NBA", name="Test", abbreviation="TST")
        players = extract_player_stats(soup, "TST", team)
        assert len(players) == 1
        assert players[0].player_name == "Active"

    def test_mp_not_with_team_skipped(self):
        """Row where mp cell says 'Not With Team' is skipped (line 129)."""
        html = """<html><body>
        <table id="box-TST-game-basic">
          <tbody>
            <tr><th data-stat="player"><a href="/players/x/xxx01.html">Traded</a></th>
            <td data-stat="mp">Not With Team</td></tr>
          </tbody>
        </table>
        </body></html>"""
        soup = BeautifulSoup(html, "lxml")
        team = TeamIdentity(league_code="NBA", name="Test", abbreviation="TST")
        players = extract_player_stats(soup, "TST", team)
        assert len(players) == 0

    def test_player_no_href(self):
        """Player link with no href → player_id defaults to name (line 116-117)."""
        html = """<html><body>
        <table id="box-TST-game-basic">
          <tbody>
            <tr><th data-stat="player"><a>Mystery Player</a></th>
            <td data-stat="mp">5:00</td><td data-stat="pts">2</td></tr>
          </tbody>
        </table>
        </body></html>"""
        soup = BeautifulSoup(html, "lxml")
        team = TeamIdentity(league_code="NBA", name="Test", abbreviation="TST")
        players = extract_player_stats(soup, "TST", team)
        assert len(players) == 1
        assert players[0].player_id == "Mystery Player"


class TestParseMinutesEdgeCases:
    """Coverage for nba_bref_helpers.py lines 172-173."""

    def test_invalid_mm_ss(self):
        """Non-numeric parts in MM:SS format → None."""
        assert _parse_minutes("abc:def") is None

    def test_colon_only(self):
        """Just a colon → ValueError → None."""
        assert _parse_minutes(":") is None


class TestDetectPeriodFromTextEdgeCases:
    """Coverage for nba_bref_helpers.py lines 258, 260."""

    def test_second_quarter(self):
        assert _detect_period_from_text("2nd Quarter") == 2

    def test_third_quarter(self):
        assert _detect_period_from_text("3rd Quarter") == 3

    def test_first_q_short(self):
        assert _detect_period_from_text("1st Q") == 1

    def test_second_q_short(self):
        assert _detect_period_from_text("2nd Q") == 2

    def test_third_q_short(self):
        assert _detect_period_from_text("3rd Q") == 3

    def test_fourth_q_short(self):
        assert _detect_period_from_text("4th Q") == 4

    def test_third_overtime(self):
        assert _detect_period_from_text("3rd Overtime") == 7


class TestClassifyPlayEdgeCases:
    """Coverage for nba_bref_helpers.py lines 382-387."""

    def test_jump_ball(self):
        assert _classify_play("Jump ball: A vs B") == "jump_ball"

    def test_violation(self):
        assert _classify_play("Defensive 3-second violation") == "violation"

    def test_makes_three_alternate(self):
        assert _classify_play("Player makes three pointer") == "3pt"

    def test_makes_two_alternate(self):
        assert _classify_play("Player makes two point shot") == "2pt"

    def test_substitution_keyword(self):
        assert _classify_play("Substitution: A for B") == "substitution"


class TestParsePbpTableEdgeCases:
    """Coverage for nba_bref_helpers.py lines 199-202, 226-227, 232-236, 279, 293-315, 326."""

    def test_pbp_table_fallback_by_id(self):
        """No all_pbp div, no table#pbp, but a table with 'pbp' in id (lines 199-202)."""
        html = """<html><body>
        <table id="game_pbp">
          <tbody>
            <tr id="q1"><td colspan="6">1st Quarter</td></tr>
            <tr><td>12:00.0</td><td>Away action</td><td></td><td>50-48</td><td></td><td></td></tr>
          </tbody>
        </table>
        </body></html>"""
        soup = BeautifulSoup(html, "lxml")
        plays = parse_pbp_table(soup)
        assert len(plays) >= 1

    def test_period_detection_from_text(self):
        """Period header detection via 'Start of' text (lines 232-236)."""
        html = """<html><body>
        <table id="pbp">
          <tbody>
            <tr><td colspan="6">Start of 3rd Quarter</td></tr>
            <tr><td>12:00</td><td>Away shot</td><td></td><td>60-55</td><td></td><td></td></tr>
            <tr><td colspan="6">End of 3rd Quarter</td></tr>
          </tbody>
        </table>
        </body></html>"""
        soup = BeautifulSoup(html, "lxml")
        plays = parse_pbp_table(soup)
        assert len(plays) == 1
        assert plays[0].quarter == 3

    def test_invalid_q_row_id(self):
        """Row id like 'qabc' should not crash (line 226-227, ValueError)."""
        html = """<html><body>
        <table id="pbp">
          <tbody>
            <tr id="qabc"><td colspan="6">Something</td></tr>
            <tr><td>10:00</td><td>Away play</td><td></td><td>5-3</td><td></td><td></td></tr>
          </tbody>
        </table>
        </body></html>"""
        soup = BeautifulSoup(html, "lxml")
        plays = parse_pbp_table(soup)
        # The qabc row should be skipped (falls through to text check), play still parsed
        assert len(plays) >= 1

    def test_two_cell_row_neutral_play(self):
        """Row with exactly 2 cells → neutral play (lines 293-315)."""
        html = """<html><body>
        <table id="pbp">
          <tbody>
            <tr id="q1"><td colspan="2">1st Q</td></tr>
            <tr><td>12:00</td><td>Jump ball: A vs B</td></tr>
          </tbody>
        </table>
        </body></html>"""
        soup = BeautifulSoup(html, "lxml")
        plays = parse_pbp_table(soup)
        assert len(plays) == 1
        assert plays[0].description == "Jump ball: A vs B"
        assert plays[0].play_type is None
        assert plays[0].home_score is None

    def test_three_cell_row_returns_none(self):
        """Row with exactly 3 cells → _parse_pbp_row returns None (line 315)."""
        html = """<html><body>
        <table id="pbp">
          <tbody>
            <tr><td>10:00</td><td>Something</td><td>Else</td></tr>
          </tbody>
        </table>
        </body></html>"""
        soup = BeautifulSoup(html, "lxml")
        plays = parse_pbp_table(soup)
        assert len(plays) == 0

    def test_four_cell_layout(self):
        """Row with 4 cells uses Time|Away|Score|Home layout."""
        html = """<html><body>
        <table id="pbp">
          <tbody>
            <tr><td>8:30</td><td>Away makes 3-pt shot</td><td>10-8</td><td></td></tr>
          </tbody>
        </table>
        </body></html>"""
        soup = BeautifulSoup(html, "lxml")
        plays = parse_pbp_table(soup)
        assert len(plays) == 1
        assert plays[0].away_score == 10
        assert plays[0].home_score == 8
        assert plays[0].play_type == "3pt"

    def test_empty_description_returns_none(self):
        """Row where both away and home actions are empty → None (line 326)."""
        html = """<html><body>
        <table id="pbp">
          <tbody>
            <tr><td>5:00</td><td></td><td></td><td>30-28</td><td></td><td></td></tr>
          </tbody>
        </table>
        </body></html>"""
        soup = BeautifulSoup(html, "lxml")
        plays = parse_pbp_table(soup)
        assert len(plays) == 0

    def test_no_tbody_uses_table_rows(self):
        """When table has no tbody, rows from table directly are used (line 213)."""
        html = """<html><body>
        <table id="pbp">
          <tr id="q1"><td colspan="6">1st Quarter</td></tr>
          <tr><td>12:00</td><td>Action</td><td></td><td>2-0</td><td></td><td></td></tr>
        </table>
        </body></html>"""
        soup = BeautifulSoup(html, "lxml")
        plays = parse_pbp_table(soup)
        assert len(plays) >= 1

    def test_one_cell_row_returns_none(self):
        """Row with just 1 cell → _parse_pbp_row returns None (line 279)."""
        html = """<html><body>
        <table id="pbp">
          <tbody>
            <tr><td>12:00</td></tr>
          </tbody>
        </table>
        </body></html>"""
        soup = BeautifulSoup(html, "lxml")
        plays = parse_pbp_table(soup)
        assert len(plays) == 0

    def test_score_without_dash(self):
        """Score text without a dash → no score parsed."""
        html = """<html><body>
        <table id="pbp">
          <tbody>
            <tr><td>7:00</td><td>Away rebound</td><td></td><td>N/A</td><td></td><td></td></tr>
          </tbody>
        </table>
        </body></html>"""
        soup = BeautifulSoup(html, "lxml")
        plays = parse_pbp_table(soup)
        assert len(plays) == 1
        assert plays[0].home_score is None
        assert plays[0].away_score is None

    def test_row_with_only_th_no_td_cells(self):
        """Row with <th> cells but no <td> cells should be skipped (line 240)."""
        html = """<html><body>
        <table id="pbp">
          <tbody>
            <tr><th>Time</th><th>Away</th><th>Score</th><th>Home</th></tr>
            <tr><td>10:00</td><td>Shot made</td><td></td><td>5-3</td><td></td><td></td></tr>
          </tbody>
        </table>
        </body></html>"""
        soup = BeautifulSoup(html, "lxml")
        plays = parse_pbp_table(soup)
        # First row (th-only) should be skipped, second row parsed
        assert len(plays) == 1


class TestExtractPlayerStatsEmptyPlayerCell:
    """Coverage for nba_bref_helpers.py line 112: empty player_cell with no text and no link."""

    def test_empty_player_cell_no_text_no_link(self):
        """Player cell that is empty (no text, no link) → continue (line 112)."""
        html = """<html><body>
        <table id="box-TST-game-basic">
          <tbody>
            <tr><th data-stat="player"></th></tr>
            <tr><th data-stat="player"><a href="/players/x/xxx01.html">Active Player</a></th>
            <td data-stat="mp">20:00</td><td data-stat="pts">10</td></tr>
          </tbody>
        </table>
        </body></html>"""
        soup = BeautifulSoup(html, "lxml")
        team = TeamIdentity(league_code="NBA", name="Test", abbreviation="TST")
        players = extract_player_stats(soup, "TST", team)
        assert len(players) == 1
        assert players[0].player_name == "Active Player"


class TestExtractTeamStatsNoneValues:
    """Coverage for nba_bref_helpers.py line 55: stats dict containing None values."""

    def test_stats_with_none_value_from_table(self):
        """When extract_team_stats_from_table returns None values, they are skipped (line 55)."""
        html = """<html><body>
        <table id="box-TST-game-basic">
          <tfoot><tr>
            <td data-stat="player">Team Totals</td>
            <td data-stat="pts">100</td>
            <td data-stat="plus_minus"></td>
          </tr></tfoot>
        </table>
        </body></html>"""
        soup = BeautifulSoup(html, "lxml")
        stats = extract_team_stats(soup, "TST")
        assert stats["pts"] == 100
        # plus_minus should be absent since its value is empty
        assert "plus_minus" not in stats

    @patch("sports_scraper.scrapers.nba_bref_helpers.extract_team_stats_from_table")
    def test_stats_with_none_value_skipped(self, mock_extract):
        """When underlying function returns None values, they are skipped (line 55)."""
        mock_extract.return_value = {"pts": "100", "fg": None, "ast": ""}
        html = """<html><body>
        <table id="box-TST-game-basic">
          <tfoot><tr><td data-stat="player">Team Totals</td></tr></tfoot>
        </table>
        </body></html>"""
        soup = BeautifulSoup(html, "lxml")
        stats = extract_team_stats(soup, "TST")
        assert stats["pts"] == 100
        assert "fg" not in stats
        assert "ast" not in stats
