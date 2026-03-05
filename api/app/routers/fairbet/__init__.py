"""FairBet router bundle."""

from fastapi import APIRouter

from . import live, odds, parlay

router = APIRouter(prefix="/api/fairbet", tags=["fairbet"])
router.include_router(odds.router)
router.include_router(parlay.router)
router.include_router(live.router)

__all__ = ["router"]
