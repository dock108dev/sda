"""Admin realtime endpoints — test tooling for SSE load tests."""
from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, field_validator
from pydantic.alias_generators import to_camel

from app.realtime.manager import realtime_manager
from app.realtime.models import is_valid_channel

router = APIRouter()


class TestEmitRequest(BaseModel):
    channel: str
    event_type: str = "patch"
    payload: dict[str, Any] = {}

    @field_validator("channel")
    @classmethod
    def channel_must_be_valid(cls, v: str) -> str:
        if not is_valid_channel(v):
            raise ValueError(f"Invalid channel format: {v!r}")
        return v


class TestEmitResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    channel: str
    event_type: str
    seq: int
    published_at: float


@router.post(
    "/realtime/test-emit",
    response_model=TestEmitResponse,
    summary="Publish a synthetic SSE event (load-test use only)",
)
async def test_emit(body: TestEmitRequest) -> TestEmitResponse:
    """Write a synthetic event to Redis Streams.

    Intended exclusively for SSE load-test harnesses.  Returns 403 in
    production and staging so the endpoint cannot be abused in live environments.
    """
    from app.config import settings

    if settings.environment in ("production", "staging"):
        raise HTTPException(status_code=403, detail="Not available in production")

    payload = {**body.payload, "_publish_ts": time.time()}
    seq = await realtime_manager.publish(body.channel, body.event_type, payload)

    return TestEmitResponse(
        channel=body.channel,
        event_type=body.event_type,
        seq=seq,
        published_at=time.time(),
    )
