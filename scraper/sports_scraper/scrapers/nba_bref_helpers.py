"""Helper functions for NBA basketball-reference.com scraping.

Parsing logic for boxscore tables, player stats, and play-by-play.
Basketball Reference uses `data-stat` attributes on cells, so we
reuse the shared `extract_all_stats_from_row` / `get_stat_from_row`
utilities from the HTML parsing module.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..logging import logger
from ..models import NormalizedPlay, NormalizedPlayerBoxscore, TeamIdentity
from ..utils import extract_all_stats_from_row, get_stat_from_row, parse_float, parse_int
from ..utils.html_parsing import extract_team_stats_from_table

# Basketball Reference stat column → our raw_stats key mapping.
# Most BR columns use data-stat attributes that we store directly.
# The shared extract_all_stats_from_row() captures them all.
# This mapping is for documentation — the actual keys come from data-stat attrs:
#   fg, fga, fg_pct, fg3, fg3a, fg3_pct, ft, fta, ft_pct,
#   orb, drb, trb, ast, stl, blk, tov, pf, pts, plus_minus, mp


def extract_team_stats(soup: BeautifulSoup, team_abbr: str) -> dict:
    """Extract team totals from NBA boxscore page.

    Finds the basic stats table by ID pattern `box-{ABBR}-game-basic`
    and extracts the tfoot (team totals) row.
    """
    table_id = f"box-{team_abbr}-game-basic"
    table = soup.find("table", id=table_id)

    if not table:
        # Try case variations
        for t in soup.find_all("table", id=True):
            tid = t.get("id", "")
            if tid.lower() == table_id.lower():
                table = t
                break

    if not table:
        logger.warning("nba_bref_team_stats_table_not_found", team_abbr=team_abbr, table_id=table_id)
        return {}

    stats = extract_team_stats_from_table(table, team_abbr, table_id)

    # Parse numeric values
    parsed: dict[str, int | float | str] = {}
    for key, value in stats.items():
        if value in (None, ""):
            continue
        parsed_int = parse_int(value)
        if parsed_int is not None:
            parsed[key] = parsed_int
            continue
        parsed_float = parse_float(value)
        if parsed_float is not None:
            parsed[key] = parsed_float
            continue
        parsed[key] = value
    return parsed


def extract_player_stats(
    soup: BeautifulSoup, team_abbr: str, team_identity: TeamIdentity
) -> list[NormalizedPlayerBoxscore]:
    """Extract player stats from NBA boxscore page.

    Finds `table#box-{ABBR}-game-basic` and parses each player row.
    Skips "Did Not Play", "Did Not Dress", "Not With Team" rows.
    """
    table_id = f"box-{team_abbr}-game-basic"
    table = soup.find("table", id=table_id)

    if not table:
        for t in soup.find_all("table", id=True):
            tid = t.get("id", "")
            if tid.lower() == table_id.lower():
                table = t
                break

    if not table:
        logger.warning("nba_bref_player_table_not_found", team_abbr=team_abbr)
        return []

    players: list[NormalizedPlayerBoxscore] = []
    tbody = table.find("tbody")
    if not tbody:
        return players

    for row in tbody.find_all("tr"):
        row_classes = row.get("class", [])
        if "thead" in row_classes:
            continue

        # Player name is in th[data-stat="player"]
        player_cell = row.find("th", {"data-stat": "player"})
        if not player_cell:
            continue

        player_link = player_cell.find("a")
        if not player_link:
            # Check for DNP/DND rows — these have text like "Did Not Play"
            cell_text = player_cell.get_text(strip=True)
            if cell_text:
                # Skip reserve separator rows and DNP entries
                continue
            continue

        player_name = player_link.text.strip()
        href = player_link.get("href", "")
        # Extract player ID from href: /players/x/xxxxx01.html → xxxxx01
        player_id = href.split("/")[-1].replace(".html", "") if href else player_name

        # Check if this is a DNP row (reason cell spans multiple columns)
        reason_cell = row.find("td", {"data-stat": "reason"})
        if reason_cell:
            continue

        # Check minutes — if empty or "Did Not Play", skip
        mp_cell = row.find("td", {"data-stat": "mp"})
        if mp_cell:
            mp_text = mp_cell.get_text(strip=True)
            if not mp_text or "did not" in mp_text.lower() or "not with" in mp_text.lower():
                continue

        raw_stats = extract_all_stats_from_row(row)

        # Parse minutes from MM:SS format → float
        minutes_str = get_stat_from_row(row, "mp")
        minutes = _parse_minutes(minutes_str) if minutes_str else None

        players.append(
            NormalizedPlayerBoxscore(
                player_id=player_id,
                player_name=player_name,
                team=team_identity,
                minutes=minutes,
                points=parse_int(get_stat_from_row(row, "pts")),
                rebounds=parse_int(get_stat_from_row(row, "trb")),
                assists=parse_int(get_stat_from_row(row, "ast")),
                raw_stats=raw_stats,
            )
        )

    logger.info(
        "nba_bref_player_stats_extracted",
        team_abbr=team_abbr,
        players=len(players),
    )
    return players


def _parse_minutes(mp_str: str) -> float | None:
    """Parse minutes from Basketball Reference format.

    Formats: "36:12" (MM:SS) or "36" (just minutes).
    Returns float minutes (e.g., 36.2).
    """
    if not mp_str:
        return None
    if ":" in mp_str:
        parts = mp_str.split(":")
        try:
            mins = int(parts[0])
            secs = int(parts[1]) if len(parts) > 1 else 0
            return round(mins + secs / 60, 1)
        except (ValueError, IndexError):
            return None
    return parse_float(mp_str)


# PBP period detection pattern
_PERIOD_PATTERN = re.compile(
    r"(?:start\s+of\s+)?(\d+)(?:st|nd|rd|th)\s+(?:quarter|q)|"
    r"(?:start\s+of\s+)?(\d+)(?:st|nd|rd|th)\s+overtime|"
    r"(?:start\s+of\s+)?overtime",
    re.IGNORECASE,
)


def parse_pbp_table(soup: BeautifulSoup) -> list[NormalizedPlay]:
    """Parse play-by-play table from Basketball Reference.

    Structure: rows with 6 cells (Time | AwayCol1 | AwayCol2 | Score | HomeCol1 | HomeCol2)
    or 4 cells (Time | Away | Score | Home), plus period header rows.
    """
    # Find the PBP table — it may be in a div#all_pbp or directly as table#pbp
    pbp_div = soup.find("div", id="all_pbp")
    table = pbp_div.find("table") if pbp_div else soup.find("table", id="pbp")

    if not table:
        # Try finding any table with pbp-like content
        for t in soup.find_all("table"):
            tid = t.get("id", "")
            if "pbp" in tid.lower():
                table = t
                break

    if not table:
        logger.warning("nba_bref_pbp_table_not_found")
        return []

    plays: list[NormalizedPlay] = []
    current_period = 1
    play_seq = 0

    tbody = table.find("tbody")
    rows = tbody.find_all("tr") if tbody else table.find_all("tr")

    for row in rows:
        row_id = (row.get("id") or "").strip().lower()

        # Detect period headers
        if row_id and row_id.startswith("q"):
            # e.g., id="q1", "q2", "q3", "q4", "q5" (OT)
            try:
                period_num = int(row_id[1:])
                current_period = period_num
                play_seq = 0
                continue
            except ValueError:
                pass

        # Check for period marker text in header rows
        header_text = row.get_text(" ", strip=True).lower()
        if "start of" in header_text or "end of" in header_text:
            period = _detect_period_from_text(header_text)
            if period is not None:
                current_period = period
                play_seq = 0
            continue

        cells = row.find_all("td")
        if not cells:
            continue

        # Parse based on cell count
        play = _parse_pbp_row(cells, current_period, play_seq)
        if play:
            plays.append(play)
            play_seq += 1

    logger.info("nba_bref_pbp_parsed", total_plays=len(plays))
    return plays


def _detect_period_from_text(text: str) -> int | None:
    """Detect period number from header text."""
    text = text.lower()
    if "1st quarter" in text or "1st q" in text:
        return 1
    if "2nd quarter" in text or "2nd q" in text:
        return 2
    if "3rd quarter" in text or "3rd q" in text:
        return 3
    if "4th quarter" in text or "4th q" in text:
        return 4

    # Overtime periods
    ot_match = re.search(r"(\d+)(?:st|nd|rd|th)\s+overtime", text)
    if ot_match:
        return 4 + int(ot_match.group(1))
    if "overtime" in text:
        return 5  # First OT

    return None


def _parse_pbp_row(
    cells: list, period: int, seq: int
) -> NormalizedPlay | None:
    """Parse a single PBP row into a NormalizedPlay."""
    if len(cells) < 2:
        return None

    # First cell is always time
    game_clock = cells[0].get_text(strip=True) or None
    # Strip trailing ".0" from times like "11:48.0"
    if game_clock and game_clock.endswith(".0"):
        game_clock = game_clock[:-2]

    # Handle different column layouts
    if len(cells) >= 6:
        # 6-cell layout: Time | Away1 | Away2 | Score | Home1 | Home2
        away_action = cells[1].get_text(strip=True) or cells[2].get_text(strip=True)
        score_text = cells[3].get_text(strip=True)
        home_action = cells[4].get_text(strip=True) or cells[5].get_text(strip=True)
    elif len(cells) >= 4:
        # 4-cell layout: Time | Away | Score | Home
        away_action = cells[1].get_text(strip=True)
        score_text = cells[2].get_text(strip=True)
        home_action = cells[3].get_text(strip=True)
    elif len(cells) == 2:
        # Neutral play (jump ball, etc.)
        description = cells[1].get_text(strip=True)
        return NormalizedPlay(
            play_index=period * 10000 + seq,
            quarter=period,
            game_clock=game_clock,
            play_type=None,
            team_abbreviation=None,
            player_id=None,
            player_name=None,
            description=description,
            home_score=None,
            away_score=None,
            raw_data={"full_description": description},
        )
    else:
        return None

    # Build description
    description_parts = []
    if away_action:
        description_parts.append(away_action)
    if home_action:
        description_parts.append(home_action)
    description = " | ".join(description_parts) if description_parts else None

    if not description:
        return None

    # Determine which team acted
    team_abbr = None
    active_action = away_action or home_action

    # Parse score
    away_score = None
    home_score = None
    if score_text and "-" in score_text:
        parts = score_text.split("-")
        if len(parts) == 2:
            away_score = parse_int(parts[0].strip())
            home_score = parse_int(parts[1].strip())

    # Detect play type from description
    play_type = _classify_play(active_action) if active_action else None

    return NormalizedPlay(
        play_index=period * 10000 + seq,
        quarter=period,
        game_clock=game_clock,
        play_type=play_type,
        team_abbreviation=team_abbr,
        player_id=None,
        player_name=None,
        description=description,
        home_score=home_score,
        away_score=away_score,
        raw_data={
            "away_action": away_action,
            "home_action": home_action,
            "score": score_text,
        },
    )


def _classify_play(text: str) -> str | None:
    """Classify a play description into a normalized play type."""
    text_lower = text.lower()
    if "makes 3-pt" in text_lower or "makes three" in text_lower:
        return "3pt"
    if "makes 2-pt" in text_lower or "makes two" in text_lower:
        return "2pt"
    if "makes free throw" in text_lower:
        return "ft"
    if "misses" in text_lower:
        return "miss"
    if "rebound" in text_lower:
        return "rebound"
    if "turnover" in text_lower:
        return "turnover"
    if "foul" in text_lower:
        return "foul"
    if "jump ball" in text_lower:
        return "jump_ball"
    if "enters the game" in text_lower or "substitution" in text_lower:
        return "substitution"
    if "timeout" in text_lower:
        return "timeout"
    if "violation" in text_lower:
        return "violation"
    return None
