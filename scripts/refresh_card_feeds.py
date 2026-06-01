#!/usr/bin/env python3
"""Refresh materialized Scroll Down card feeds through the live API."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REQUEST_TIMEOUT_SECONDS = 180


class RefreshError(RuntimeError):
    """Raised when card-feed refresh cannot complete."""


def _env_file_values(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _resolve_api_key(args: argparse.Namespace) -> str | None:
    if args.api_key:
        return args.api_key
    env_values = _env_file_values(Path(args.env_file))
    for key in ("API_KEY", "SPORTS_API_KEY"):
        if env_values.get(key):
            return env_values[key]
    for key in ("API_KEY", "SPORTS_API_KEY"):
        if os.getenv(key):
            return os.environ[key]
    return None


def _request_refresh(args: argparse.Namespace) -> dict[str, Any]:
    query = urllib.parse.urlencode(
        {
            "lookbackHours": args.lookback_hours,
            "lookaheadHours": args.lookahead_hours,
            "force": str(args.force).lower(),
            "spoilerPolicy": args.spoiler_policy,
        }
    )
    path = f"/api/admin/sports/card-feeds/refresh?{query}"
    url = urllib.parse.urljoin(args.base_url.rstrip("/") + "/", path.lstrip("/"))
    request = urllib.request.Request(
        url,
        method="POST",
        headers={
            "Accept": "application/json",
            "User-Agent": "ScrollDownCardFeedRefresh/1.0",
        },
    )
    api_key = _resolve_api_key(args)
    if api_key:
        request.add_header("X-API-Key", api_key)
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            status = response.status
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RefreshError(f"{path} returned HTTP {exc.code}: {detail[:300]}") from exc
    except urllib.error.URLError as exc:
        raise RefreshError(f"{path} request failed: {exc}") from exc
    except TimeoutError as exc:
        raise RefreshError(
            f"{path} request timed out after {REQUEST_TIMEOUT_SECONDS}s"
        ) from exc
    if status != 200:
        raise RefreshError(f"{path} returned HTTP {status}")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RefreshError(f"{path} did not return valid JSON") from exc
    if not isinstance(payload, dict):
        raise RefreshError(f"{path} returned a non-object JSON payload")
    return payload


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("API_BASE_URL", "http://localhost:8000"))
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--env-file", default=os.getenv("DEPLOY_ENV_FILE", "infra/.env"))
    parser.add_argument("--lookback-hours", type=int, default=72)
    parser.add_argument("--lookahead-hours", type=int, default=72)
    parser.add_argument("--spoiler-policy", default="pre_reveal")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        payload = _request_refresh(args)
    except RefreshError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(
        "card_feed_refresh "
        f"scanned={payload.get('scannedGames')} "
        f"eligible={payload.get('eligibleGames')} "
        f"generated={payload.get('generated')} "
        f"skipped_current={payload.get('skippedCurrent')} "
        f"failed={payload.get('failed')}"
    )
    errors = payload.get("errors") or []
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    if payload.get("failed"):
        print("ERROR: card feed refresh reported failures", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
