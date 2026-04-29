"""Sports admin router bundle."""

from fastapi import APIRouter

from . import (
    diagnostics,
    docker_logs,
    game_timeline,
    games,
    jobs,
    scraper_runs,
    season_audit,
    teams,
)

router = APIRouter(prefix="/api/admin/sports", tags=["sports-data"])
router.include_router(scraper_runs.router)
router.include_router(games.router)
router.include_router(game_timeline.router)
router.include_router(teams.router)
router.include_router(jobs.router)
router.include_router(diagnostics.router)
router.include_router(docker_logs.router)
router.include_router(season_audit.router)

__all__ = ["router"]
