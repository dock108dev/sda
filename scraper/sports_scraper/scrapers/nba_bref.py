"""NBA historical scraper using basketball-reference.com.

Used for backfilling historical NBA data (boxscores, player stats, PBP)
for seasons where the NBA CDN API is no longer available. The CDN API
only serves current-season data.

Live/current data continues to use the NBA CDN API (see live/nba.py).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Comment

from ..logging import logger
from ..models import (
    GameIdentification,
    NormalizedGame,
    NormalizedPlayByPlay,
    NormalizedTeamBoxscore,
    TeamIdentity,
)
from ..normalization import normalize_team_name
from ..utils.datetime_utils import date_to_utc_datetime
from ..utils.parsing import parse_int
from .base import BaseSportsReferenceScraper, ScraperError
from .nba_bref_helpers import extract_player_stats, extract_team_stats, parse_pbp_table


class NBABasketballReferenceScraper(BaseSportsReferenceScraper):
    """Scraper for historical NBA data from basketball-reference.com.

    Politely scrapes boxscores, player stats, and play-by-play data.
    Uses the shared BaseSportsReferenceScraper infrastructure for:
    - 5-9 second random delays between requests
    - Local HTML caching (only fetch each page once)
    - Automatic retry with exponential backoff on errors
    """

    sport = "nba"
    league_code = "NBA"
    base_url = "https://www.basketball-reference.com/boxscores/"

    def scoreboard_url(self, day: date) -> str:
        return f"{self.base_url}?month={day.month}&day={day.day}&year={day.year}"

    def pbp_url(self, source_game_key: str) -> str:
        return f"https://www.basketball-reference.com/boxscores/pbp/{source_game_key}.html"

    def _unwrap_commented_tables(self, soup: BeautifulSoup) -> None:
        """Basketball Reference wraps some tables in HTML comments.

        This finds commented-out tables and injects them into the DOM
        so they can be found by normal BeautifulSoup queries.
        """
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment_text = str(comment)
            if "<table" in comment_text and "box-" in comment_text:
                fragment = BeautifulSoup(comment_text, "lxml")
                for table in fragment.find_all("table"):
                    comment.replace_with(table)
                    break  # Only replace with first table per comment

    def _parse_team_row(self, row) -> tuple[TeamIdentity, int]:
        """Parse a team row from the scoreboard page.

        NBA scoreboard rows have: team link + score cells.
        """
        team_link = row.find("a")
        if not team_link:
            raise ScraperError("Missing team link in scoreboard row")

        team_name = team_link.text.strip()
        canonical_name, abbreviation = normalize_team_name(self.league_code, team_name)

        # Score is in the last td cell
        score = None
        for cell in reversed(row.find_all("td")):
            score = parse_int(cell.text.strip())
            if score is not None:
                break

        if score is None:
            raise ScraperError(f"Could not parse score for {team_name}")

        identity = TeamIdentity(
            league_code=self.league_code,
            name=canonical_name,
            short_name=canonical_name,
            abbreviation=abbreviation,
            external_ref=abbreviation.upper() if abbreviation else None,
        )
        return identity, score

    def _parse_scorebox_abbreviations(self, soup: BeautifulSoup) -> tuple[str | None, str | None]:
        """Extract away/home team abbreviations from the boxscore scorebox."""
        scorebox = soup.find("div", class_="scorebox")
        if not scorebox:
            return None, None

        team_divs = scorebox.find_all("div", recursive=False)
        if len(team_divs) < 2:
            return None, None

        def parse_abbr(div) -> str | None:
            # Look for team link in strong > a or itemprop="name"
            team_link = div.find("a", itemprop="name")
            if not team_link:
                strong = div.find("strong")
                team_link = strong.find("a") if strong else None
            if not team_link:
                # Fallback: any link to /teams/
                for a in div.find_all("a"):
                    href = a.get("href", "")
                    if "/teams/" in href:
                        team_link = a
                        break
            if not team_link:
                return None
            # Extract abbreviation from href: /teams/BOS/2025.html → BOS
            href = team_link.get("href", "")
            parts = href.strip("/").split("/")
            for i, part in enumerate(parts):
                if part == "teams" and i + 1 < len(parts):
                    return parts[i + 1].upper()
            # Fallback: normalize team name
            team_name = team_link.text.strip()
            _, abbr = normalize_team_name(self.league_code, team_name)
            return abbr

        away_abbr = parse_abbr(team_divs[0])
        home_abbr = parse_abbr(team_divs[1])
        return away_abbr, home_abbr

    def _build_team_boxscore(
        self, identity: TeamIdentity, is_home: bool, score: int, stats: dict
    ) -> NormalizedTeamBoxscore:
        return NormalizedTeamBoxscore(
            team=identity,
            is_home=is_home,
            points=score,
            rebounds=parse_int(stats.get("trb")),
            assists=parse_int(stats.get("ast")),
            turnovers=parse_int(stats.get("tov")),
            raw_stats=stats,
        )

    def fetch_games_for_date(self, day: date) -> Sequence[NormalizedGame]:
        """Fetch all NBA games for a given date from Basketball Reference."""
        soup = self.fetch_html(self.scoreboard_url(day), game_date=day)
        game_divs = soup.select("div.game_summary")
        logger.info("nba_bref_fetch_start", day=str(day), game_divs=len(game_divs))

        games: list[NormalizedGame] = []
        skipped = 0

        for div in game_divs:
            team_rows = div.select("table.teams tr")
            if len(team_rows) < 2:
                skipped += 1
                continue

            try:
                away_identity, away_score = self._parse_team_row(team_rows[0])
                home_identity, home_score = self._parse_team_row(team_rows[1])
            except ScraperError as exc:
                logger.warning("nba_bref_game_parse_error", day=str(day), error=str(exc))
                skipped += 1
                continue

            # Find boxscore link
            boxscore_link = (
                div.select_one("p.links a[href*='/boxscores/']")
                or div.select_one("a[href*='/boxscores/']")
            )
            if not boxscore_link:
                skipped += 1
                continue

            boxscore_href = boxscore_link["href"]
            source_game_key = boxscore_href.split("/")[-1].replace(".html", "")

            # Fetch and parse boxscore page
            boxscore_url = urljoin(self.base_url, boxscore_href)
            box_soup = self.fetch_html(boxscore_url, game_date=day)
            self._unwrap_commented_tables(box_soup)

            # Get team abbreviations from scorebox for table matching
            away_abbr, home_abbr = self._parse_scorebox_abbreviations(box_soup)
            if not away_abbr or not home_abbr:
                # Fallback to identity abbreviations
                away_abbr = away_abbr or away_identity.abbreviation
                home_abbr = home_abbr or home_identity.abbreviation

            # Extract stats
            away_stats = extract_team_stats(box_soup, away_abbr)
            home_stats = extract_team_stats(box_soup, home_abbr)
            away_players = extract_player_stats(box_soup, away_abbr, away_identity)
            home_players = extract_player_stats(box_soup, home_abbr, home_identity)

            identity = GameIdentification(
                league_code=self.league_code,
                season=self._season_from_date(day),
                season_type="regular",
                game_date=date_to_utc_datetime(day),
                home_team=home_identity,
                away_team=away_identity,
                source_game_key=source_game_key,
            )

            games.append(
                NormalizedGame(
                    identity=identity,
                    status="completed",
                    home_score=home_score,
                    away_score=away_score,
                    team_boxscores=[
                        self._build_team_boxscore(away_identity, False, away_score, away_stats),
                        self._build_team_boxscore(home_identity, True, home_score, home_stats),
                    ],
                    player_boxscores=away_players + home_players,
                )
            )

        logger.info(
            "nba_bref_fetch_complete",
            day=str(day),
            games_parsed=len(games),
            games_skipped=skipped,
        )
        return games

    def fetch_play_by_play(self, source_game_key: str, game_date: date) -> NormalizedPlayByPlay:
        """Fetch play-by-play data from Basketball Reference."""
        url = self.pbp_url(source_game_key)
        soup = self.fetch_html(url, game_date=game_date)

        plays = parse_pbp_table(soup)
        logger.info(
            "nba_bref_pbp_fetched",
            game_key=source_game_key,
            plays=len(plays),
        )
        return NormalizedPlayByPlay(
            source_game_key=source_game_key,
            plays=plays,
        )
