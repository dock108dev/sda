"""Canonical Celery task registry for the catch-up-only scraper."""

from __future__ import annotations

from .polling_tasks import poll_live_pbp_task

__all__ = ["poll_live_pbp_task"]
