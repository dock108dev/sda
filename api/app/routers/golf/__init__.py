from fastapi import APIRouter

router = APIRouter(prefix="/api/golf", tags=["golf"])

from . import dfs, odds, players, pools, pools_admin, tournaments  # noqa: E402, F401
