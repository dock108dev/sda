"""Sports Reference scrapers for supported leagues."""

from __future__ import annotations

from .base import BaseSportsReferenceScraper, ScraperError
from .nba_bref import NBABasketballReferenceScraper
from .ncaab_sportsref import NCAABSportsReferenceScraper

__all__ = [
    "BaseSportsReferenceScraper",
    "ScraperError",
    "NBABasketballReferenceScraper",
    "NCAABSportsReferenceScraper",
    "get_scraper",
    "get_all_scrapers",
]


# Scraper registry — maps league codes to Sports Reference scraper classes.
# Used by the daily ingestion pipeline (run_manager → boxscore/pbp phases).
#
# NOT registered here (they have dedicated ingestion paths):
#   NBA: CDN API for current season (live/nba.py), Basketball Reference
#        for historical backfill (scrapers/nba_bref.py → ingest_nba_historical task)
#   NHL: Official NHL API (live/nhl.py)
#   MLB: MLB Stats API (live/mlb.py)
#   NFL: ESPN API (live/nfl.py)
_SCRAPER_REGISTRY: dict[str, type[BaseSportsReferenceScraper]] = {
    "NCAAB": NCAABSportsReferenceScraper,
}


def get_scraper(league_code: str) -> BaseSportsReferenceScraper | None:
    """Get a scraper instance for a league code.

    Args:
        league_code: League code (NBA, NCAAB, etc.)

    Returns:
        Scraper instance or None if not found
    """
    scraper_class = _SCRAPER_REGISTRY.get(league_code.upper())
    if scraper_class:
        return scraper_class()
    return None


def get_all_scrapers() -> dict[str, BaseSportsReferenceScraper]:
    """Get all registered scrapers as a dictionary.

    Returns:
        Dictionary mapping league codes to scraper instances
    """
    return {code: get_scraper(code) for code in _SCRAPER_REGISTRY if get_scraper(code) is not None}
