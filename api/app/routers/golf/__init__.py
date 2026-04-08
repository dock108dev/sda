from fastapi import APIRouter

router = APIRouter(prefix="/api/golf", tags=["golf"])

from . import tournaments, players, odds, dfs, pools_admin, pools  # noqa: E402, F401
