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


# Current-season NBA/NHL/MLB/NFL ingestion uses dedicated live API clients.
_SCRAPER_REGISTRY: dict[str, type[BaseSportsReferenceScraper]] = {
    "NCAAB": NCAABSportsReferenceScraper,
}


def get_scraper(league_code: str) -> BaseSportsReferenceScraper | None:
    """Get a Sports Reference scraper instance for a league code."""
    scraper_class = _SCRAPER_REGISTRY.get(league_code.upper())
    return scraper_class() if scraper_class else None


def get_all_scrapers() -> dict[str, BaseSportsReferenceScraper]:
    """Get all registered Sports Reference scrapers."""
    return {code: scraper_class() for code, scraper_class in _SCRAPER_REGISTRY.items()}
