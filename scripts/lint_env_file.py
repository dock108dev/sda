#!/usr/bin/env python3
"""Lint deploy env files for unknown application variables."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

KNOWN_ENV_VARS = {
    "ADMIN_ORIGINS",
    "ADMIN_RATE_LIMIT_REQUESTS",
    "ADMIN_RATE_LIMIT_REQUESTS_KEYED",
    "ADMIN_RATE_LIMIT_WINDOW_SECONDS",
    "ADMIN_RATE_LIMIT_WINDOW_SECONDS_KEYED",
    "ALLOWED_CORS_ORIGINS",
    "API_INTERNAL_URL",
    "API_KEY",
    "AUTH_ENABLED",
    "AWS_REGION",
    "BASE_DOMAIN",
    "CBB_STATS_API_KEY",
    "CELERY_BROKER_URL",
    "CELERY_DEFAULT_QUEUE",
    "CELERY_RESULT_BACKEND",
    "CONSUMER_API_KEY",
    "DATABASE_URL",
    "DATAGOLF_API_KEY",
    "EMAIL_BACKEND",
    "ENVIRONMENT",
    "FAIRBET_ODDS_CACHE_ENABLED",
    "FAIRBET_ODDS_CACHE_TTL_SECONDS",
    "FAIRBET_ODDS_SNAPSHOT_TTL_SECONDS",
    "FRONTEND_URL",
    "JWT_ALGORITHM",
    "JWT_EXPIRE_MINUTES",
    "JWT_SECRET",
    "LOG_LEVEL",
    "MAIL_FROM",
    "ODDS_API_KEY",
    "ODDS_API_REGIONS",
    "ODDS_API_WEEKLY_CAP",
    "ONBOARDING_NOTIFICATION_EMAIL",
    "OPENAI_API_KEY",
    "OPENAI_MODEL_CLASSIFICATION",
    "OPENAI_MODEL_SUMMARY",
    "RATE_LIMIT_REQUESTS",
    "RATE_LIMIT_REQUESTS_KEYED",
    "RATE_LIMIT_USE_REDIS",
    "RATE_LIMIT_WINDOW_SECONDS",
    "RATE_LIMIT_WINDOW_SECONDS_KEYED",
    "REDIS_DB",
    "REDIS_HOST",
    "REDIS_PASSWORD",
    "REDIS_URL",
    "SCRAPER_FORCE_CACHE_REFRESH",
    "SCRAPER_HTML_CACHE_DIR",
    "SMTP_HOST",
    "SMTP_PASSWORD",
    "SMTP_PORT",
    "SMTP_USE_TLS",
    "SMTP_USER",
    "SQL_ECHO",
    "SUBDOMAIN_ROUTING",
    "TRUST_FORWARDED_ORIGIN",
}

REQUIRED_PRODUCTION_ENV_VARS = {
    "ALLOWED_CORS_ORIGINS",
    "API_KEY",
    "CONSUMER_API_KEY",
    "DATABASE_URL",
    "ENVIRONMENT",
    "JWT_SECRET",
    "REDIS_URL",
}

KEY_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")


def parse_env_keys(path: Path) -> set[str]:
    keys: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = KEY_RE.match(line)
        if not match:
            raise ValueError(f"{path}:{line_number}: unsupported env line format")
        keys.add(match.group(1))
    return keys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("env_file", type=Path)
    parser.add_argument(
        "--profile", choices=("development", "staging", "production"), default="production"
    )
    args = parser.parse_args()

    if not args.env_file.exists():
        print(f"ERROR: env file not found: {args.env_file}", file=sys.stderr)
        return 2

    try:
        keys = parse_env_keys(args.env_file)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    unknown = sorted(keys - KNOWN_ENV_VARS)
    missing = sorted(REQUIRED_PRODUCTION_ENV_VARS - keys) if args.profile == "production" else []

    for key in unknown:
        print(f"UNKNOWN: {key} is not a recognized sports-data-admin env var", file=sys.stderr)
    for key in missing:
        print(f"MISSING: {key} is required for production", file=sys.stderr)

    return 1 if unknown or missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
