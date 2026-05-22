"""Docker container log viewer endpoint.

Fetches logs from the log-relay sidecar, which is the only container
with Docker socket access. This keeps the API container free of
host-level privileges.
"""

from __future__ import annotations

import logging
import os

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()

ALLOWED_CONTAINERS: set[str] = {
    "sports-api",
    "sports-api-training-worker",
    "sports-api-worker",
    "sports-scraper",
    "sports-scraper-beat",
    "sports-social-scraper",
}

LOG_RELAY_URL = os.getenv("LOG_RELAY_URL", "http://log-relay:9999")


class DockerLogsResponse(BaseModel):
    container: str
    lines: int
    logs: str


@router.get("/logs", response_model=DockerLogsResponse)
async def get_docker_logs(
    container: str = Query(..., description="Container name"),
    lines: int = Query(1000, ge=1, le=10000, description="Number of tail lines"),
) -> DockerLogsResponse:
    """Fetch recent logs from an allowed Docker container."""
    if container not in ALLOWED_CONTAINERS:
        raise HTTPException(
            status_code=400,
            detail=f"Container '{container}' is not in the allow list. "
            f"Allowed: {', '.join(sorted(ALLOWED_CONTAINERS))}",
        )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{LOG_RELAY_URL}/logs",
                params={"container": container, "lines": lines},
            )
    except (OSError, httpx.ConnectError) as exc:
        logger.warning("Log relay service unavailable: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Log relay service is not available. Is the sidecar running?",
        )

    if resp.status_code == 404:
        raise HTTPException(
            status_code=404,
            detail=f"Container '{container}' not found. Is it running?",
        )

    if resp.status_code != 200:
        body = (
            resp.json()
            if resp.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        logger.error(
            "Log relay error %s for container %s: %s",
            resp.status_code,
            container,
            body.get("error", resp.text),
        )
        raise HTTPException(
            status_code=502,
            detail=f"Log relay returned status {resp.status_code}",
        )

    data = resp.json()

    return DockerLogsResponse(
        container=data["container"],
        lines=data["lines"],
        logs=data["logs"],
    )
