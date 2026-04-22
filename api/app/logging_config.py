"""Logging helpers for structured application logs."""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any

from .utils.datetime_utils import now_utc

_SENSITIVE_EXTRA_FIELDS = {
    "email",
    "password",
    "token",
    "access_token",
    "refresh_token",
    "api_key",
    "apikey",
    "secret",
    "authorization",
    "raw_token",
}

_RESERVED_LOG_RECORD_KEYS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
}


class JSONFormatter(logging.Formatter):
    def __init__(self, service: str, environment: str) -> None:
        super().__init__()
        self._service = service
        self._environment = environment

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": now_utc().isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "service": self._service,
            "environment": self._environment,
            "message": record.getMessage(),
        }
        extras = {
            key: ("[REDACTED]" if key.lower() in _SENSITIVE_EXTRA_FIELDS else value)
            for key, value in record.__dict__.items()
            if key not in _RESERVED_LOG_RECORD_KEYS
        }
        if extras:
            payload.update(extras)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _normalize_log_level(level: str | None, environment: str) -> int:
    env = environment.lower()
    if level:
        normalized = level.strip().upper()
    else:
        normalized = "INFO" if env == "production" else "DEBUG"
    return logging._nameToLevel.get(normalized, logging.INFO)


def configure_logging(
    service: str, environment: str, log_level: str | None = None
) -> None:
    resolved_level = _normalize_log_level(
        log_level or os.getenv("LOG_LEVEL"), environment
    )
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JSONFormatter(service=service, environment=environment))
    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(resolved_level)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
