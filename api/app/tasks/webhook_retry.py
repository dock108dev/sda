"""Celery task for async Stripe webhook processing with retry and dead-letter handling.

On the synchronous webhook path, if the DB write fails the route enqueues
``process_stripe_webhook_event`` and returns HTTP 202. This task re-runs the
same handler logic with up to MAX_RETRIES retries (exponential backoff), then
moves to dead-letter state and emits a structured log on final failure.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

import stripe
from sqlalchemy import select

from app.celery_app import celery_app
from app.metrics import stripe_webhook_dead_letter_total
from app.tasks._task_infra import _task_db

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3


def _parse_stripe_event(payload: str) -> Any:
    """Deserialise a Stripe event from its JSON payload without re-verifying the signature."""
    return stripe.Event.construct_from(json.loads(payload), key=None)
_BACKOFF_BASE_SECONDS = 60  # countdown = base * 2^retry_index  (60s, 120s, 240s)


@celery_app.task(name="process_stripe_webhook_event", bind=True, max_retries=_MAX_RETRIES)
def process_stripe_webhook_event(self, event_id: str, payload: str) -> dict:
    """Process a Stripe event asynchronously; idempotent and retry-safe.

    Idempotency: if ``event_id`` is already in ``processed_stripe_events``
    the task returns immediately without doing any work.

    Retry schedule (exponential backoff from ``_BACKOFF_BASE_SECONDS``):
      attempt 1  →  retry after 60 s
      attempt 2  →  retry after 120 s
      attempt 3  →  retry after 240 s
      attempt 4  →  dead-letter (structured log + DB flag, no further retry)
    """
    attempt_num = self.request.retries + 1
    is_last = self.request.retries >= self.max_retries

    loop = asyncio.new_event_loop()
    exc: Exception | None = None
    try:
        exc = loop.run_until_complete(
            _run_and_record(event_id, payload, attempt_num, is_last)
        )
    finally:
        loop.close()

    if exc is None:
        return {"status": "ok", "event_id": event_id}

    if is_last:
        stripe_webhook_dead_letter_total.inc()
        logger.error(
            "webhook_dead_letter",
            extra={
                "event": "webhook_dead_letter",
                "event_id": event_id,
                "attempts": attempt_num,
                "error": str(exc),
            },
        )
        return {"status": "dead_letter", "event_id": event_id}

    countdown = _BACKOFF_BASE_SECONDS * (2 ** self.request.retries)
    raise self.retry(exc=exc, countdown=countdown)


async def _run_and_record(
    event_id: str,
    payload: str,
    attempt_num: int,
    is_last: bool,
) -> Exception | None:
    """Try to process the event and record the attempt; returns None on success."""
    from app.db.stripe import ProcessedStripeEvent, WebhookDeliveryAttempt
    from app.routers.webhooks import _HANDLERS, _mark_processed

    async with _task_db() as sf:
        # Idempotency — bail out if a prior attempt (or the sync path) already committed.
        async with sf() as db:
            already = await db.scalar(
                select(ProcessedStripeEvent).where(
                    ProcessedStripeEvent.event_id == event_id
                )
            )
        if already is not None:
            logger.info("webhook_task_noop", extra={"event_id": event_id})
            return None

        # Parse the Stripe event from the stored payload (no signature re-check needed;
        # the synchronous route already verified the signature before enqueueing).
        try:
            event = _parse_stripe_event(payload)
        except Exception as parse_exc:
            logger.error(
                "webhook_payload_parse_error",
                extra={"event_id": event_id, "error": str(parse_exc)},
            )
            return parse_exc

        event_type: str = event.type
        handler = _HANDLERS.get(event_type)
        if handler is None:
            logger.debug(
                "webhook_task_unknown_type",
                extra={"event_id": event_id, "event_type": event_type},
            )
            return None

        error: Exception | None = None
        try:
            async with sf() as db:
                newly = await _mark_processed(db, event_id)
                if not newly:
                    # Concurrent duplicate processed between our check and here.
                    return None
                await handler(db, event)
        except Exception as handler_exc:
            error = handler_exc
            logger.warning(
                "webhook_task_handler_error",
                extra={"event_id": event_id, "event_type": event_type, "error": str(handler_exc)},
            )

        # Record attempt (best-effort — don't fail the task if this write fails).
        try:
            async with sf() as db:
                db.add(
                    WebhookDeliveryAttempt(
                        event_id=event_id,
                        event_type=event_type,
                        attempt_num=attempt_num,
                        attempted_at=datetime.now(UTC),
                        outcome="success" if error is None else "fail",
                        error_detail=str(error)[:2000] if error else None,
                        is_dead_letter=is_last and error is not None,
                    )
                )
                await db.commit()
        except Exception as rec_exc:
            logger.warning(
                "webhook_attempt_record_failed",
                extra={"event_id": event_id, "error": str(rec_exc)},
            )

        return error
