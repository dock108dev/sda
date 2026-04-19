"""Consumer v1 API router bundle.

All routes under /api/v1/ are consumer-facing with read-only auth scope.
"""

from fastapi import APIRouter, Depends

from app.dependencies.consumer_auth import verify_consumer_api_key

from . import games

router = APIRouter(
    prefix="/api/v1",
    tags=["v1"],
    dependencies=[Depends(verify_consumer_api_key)],
)
router.include_router(games.router)

__all__ = ["router"]
