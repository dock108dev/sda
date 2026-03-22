"""
Centralized structlog configuration for the sports scraper service.

Provides JSON-formatted logs consistent with other dock108 services.
Logs include environment context for better filtering in production.
"""

from __future__ import annotations

import logging

import structlog

from .config import settings


def _normalize_log_level(level: str | None, environment: str) -> int:
    env = environment.lower()
    if level:
        normalized = level.strip().upper()
    else:
        normalized = "INFO" if env == "production" else "DEBUG"
    return logging._nameToLevel.get(normalized, logging.INFO)


def configure_logging() -> None:
    """
    Configure structlog with JSON output.

    Uses the same processor chain as the API service for consistency.
    All logs are output as JSON to stdout for easy aggregation.
    """
    resolved_level = _normalize_log_level(settings.log_level, settings.environment)
    logging.basicConfig(level=resolved_level, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.EventRenamer("message"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configure the stdlib formatter to use structlog's JSON renderer
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(resolved_level)


# Configure logging at module import time
configure_logging()

# Global logger instance with service context
logger = structlog.get_logger("sports-scraper").bind(
    service="sports-scraper",
    environment=settings.environment,
)
