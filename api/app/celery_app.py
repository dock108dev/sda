"""Celery application for background tasks."""

import os

from celery import Celery

# Redis connection from environment
# CELERY_BROKER_URL takes precedence if set (for separate broker database)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", REDIS_URL)

# Create Celery app
celery_app = Celery(
    "sports_data_admin",
    broker=CELERY_BROKER_URL,
    backend=REDIS_URL,  # Results can stay on main Redis database
    include=["app.tasks.bulk_flow_generation", "app.tasks.training_tasks"],
)

# Configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour max per task
    task_soft_time_limit=3300,  # 55 minutes soft limit
    result_expires=86400,  # Keep results for 24 hours
)
