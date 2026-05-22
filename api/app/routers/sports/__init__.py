"""Sports admin router bundle."""

from fastapi import APIRouter

from . import catchup

router = APIRouter(prefix="/api/admin/sports", tags=["sports-data"])

router.include_router(catchup.router)

__all__ = ["router"]
