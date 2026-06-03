"""FairBet odds query load options."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import selectinload

from ...db.odds import FairbetGameOddsWork
from ...db.sports import SportsGame

logger = logging.getLogger(__name__)


def _safe_game_load_options() -> tuple[Any, ...]:
    """Return eager-load options, tolerating partially initialized mappers in tests."""
    try:
        return (
            selectinload(FairbetGameOddsWork.game).selectinload(SportsGame.league),
            selectinload(FairbetGameOddsWork.game).selectinload(SportsGame.home_team),
            selectinload(FairbetGameOddsWork.game).selectinload(SportsGame.away_team),
        )
    except Exception:
        # See docs/audits/error-handling-report.md Appendix B. SQLAlchemy raises
        # InvalidRequestError / ArgumentError when mappers leak through in unit
        # tests; we tolerate that but still log because the same fallback in
        # prod silently degrades every odds query to N+1 lookups.
        logger.warning(
            "fairbet_eager_load_options_unavailable_falling_back_to_lazy",
            exc_info=True,
        )
        return ()
