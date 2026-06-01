#!/usr/bin/env python3
"""Validate the Scroll Down consumer card-feed contract against a live API."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


ALLOWED_GENERATION_STATUSES = {
    "ready",
    "no_pbp_yet",
    "unsupported_sport",
    "generation_pending",
    "validation_blocked",
    "stale_regenerating",
}
ALLOWED_IMPORTANCE_LEVELS = {"primary", "secondary", "tertiary"}
ALLOWED_VISUAL_IMPORTANCE = {"critical", "high", "medium", "low"}
IMPORTANT_LEVELS = {"primary"}
IMPORTANT_VISUALS = {"critical", "high"}


class ValidationError(RuntimeError):
    """Raised when the API data does not satisfy the frontend contract."""


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
    for key in ("CONSUMER_API_KEY", "SDA_CONSUMER_API_KEY"):
        if env_values.get(key):
            return env_values[key]
    for key in ("CONSUMER_API_KEY", "SDA_CONSUMER_API_KEY"):
        if os.getenv(key):
            return os.environ[key]
    for key in ("API_KEY", "SPORTS_API_KEY"):
        if env_values.get(key):
            return env_values[key]
    for key in ("API_KEY", "SPORTS_API_KEY"):
        if os.getenv(key):
            return os.environ[key]
    return None


def _request_json(base_url: str, path: str, api_key: str | None) -> dict[str, Any]:
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "ScrollDownDeployValidator/1.0",
        },
    )
    if api_key:
        request.add_header("X-API-Key", api_key)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            status = response.status
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ValidationError(f"{path} returned HTTP {exc.code}: {detail[:300]}") from exc
    except urllib.error.URLError as exc:
        raise ValidationError(f"{path} request failed: {exc}") from exc
    if status != 200:
        raise ValidationError(f"{path} returned HTTP {status}")
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"{path} did not return valid JSON") from exc
    if not isinstance(data, dict):
        raise ValidationError(f"{path} returned a non-object JSON payload")
    return data


def _select_game_targets(
    *,
    base_url: str,
    api_key: str | None,
    explicit_ids: list[int],
    limit: int,
    lookback_days: int,
    lookahead_days: int,
    max_pages: int,
) -> list[int]:
    if explicit_ids:
        return explicit_ids
    today = datetime.now(UTC).date()
    start_date = today - timedelta(days=max(0, lookback_days))
    end_date = today + timedelta(days=max(0, lookahead_days))
    all_games: list[dict[str, Any]] = []
    pbp_ids: list[int] = []
    pages_scanned = 0
    for page in range(max(1, max_pages)):
        offset = page * limit
        query = urllib.parse.urlencode(
            {
                "limit": limit,
                "offset": offset,
                "startDate": start_date.isoformat(),
                "endDate": end_date.isoformat(),
                "sort": "chronological",
            }
        )
        payload = _request_json(base_url, f"/api/v1/games?{query}", api_key)
        games = payload.get("games")
        if not isinstance(games, list):
            raise ValidationError("/api/v1/games payload missing games[]")
        pages_scanned += 1
        all_games.extend(game for game in games if isinstance(game, dict))
        pbp_ids.extend(
            int(game["id"])
            for game in games
            if isinstance(game, dict)
            and isinstance(game.get("id"), int)
            and bool(game.get("hasPbp"))
            and int(game.get("playCount") or 0) > 0
        )
        next_offset = payload.get("nextOffset")
        if not next_offset or not games:
            break
    if pbp_ids:
        return pbp_ids
    raise ValidationError(
        "no games with hasPbp=true and playCount>0 found "
        f"from {start_date.isoformat()} through {end_date.isoformat()} "
        f"after scanning {len(all_games)} games across {pages_scanned} page(s). "
        "Run poll_live_pbp/backfill or widen --lookback-days and retry."
    )


def _require_keys(source: dict[str, Any], keys: set[str], *, scope: str) -> None:
    missing = sorted(keys - set(source))
    if missing:
        raise ValidationError(f"{scope} missing keys: {', '.join(missing)}")


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_card(card: dict[str, Any], *, game_id: int, index: int) -> None:
    scope = f"game {game_id} card[{index}]"
    _require_keys(
        card,
        {
            "id",
            "gameId",
            "sourcePlayId",
            "playIndex",
            "sport",
            "league",
            "tier",
            "contentDepth",
            "modeEligibility",
            "importance",
            "visualImportance",
            "period",
            "team",
            "situation",
            "leadIn",
            "stageSetting",
            "headline",
            "description",
            "spoilerLevel",
            "textFieldSpoilerLevels",
        },
        scope=scope,
    )
    if card["gameId"] != game_id:
        raise ValidationError(f"{scope} gameId mismatch: {card['gameId']}")
    if not _non_empty_string(card.get("leadIn")):
        raise ValidationError(f"{scope} leadIn is empty")
    if not _non_empty_string(card.get("stageSetting")):
        raise ValidationError(f"{scope} stageSetting is empty")
    if not _non_empty_string(card.get("headline")):
        raise ValidationError(f"{scope} headline is empty")
    if not _non_empty_string(card.get("description")):
        raise ValidationError(f"{scope} description is empty")

    mode = card.get("modeEligibility")
    if not isinstance(mode, dict) or mode.get("all") is not True:
        raise ValidationError(f"{scope} modeEligibility.all must be true")

    importance = card.get("importance")
    if not isinstance(importance, dict):
        raise ValidationError(f"{scope} importance must be an object")
    level = importance.get("level")
    if level not in ALLOWED_IMPORTANCE_LEVELS:
        raise ValidationError(f"{scope} has invalid importance level {level!r}")
    visual = card.get("visualImportance")
    if visual not in ALLOWED_VISUAL_IMPORTANCE:
        raise ValidationError(f"{scope} has invalid visualImportance {visual!r}")

    if level in IMPORTANT_LEVELS or visual in IMPORTANT_VISUALS:
        if card["stageSetting"].strip() == card["leadIn"].strip():
            raise ValidationError(f"{scope} important card duplicates leadIn as stageSetting")


def _validate_feed(
    payload: dict[str, Any],
    *,
    game_id: int,
    min_cards: int,
) -> tuple[int, str]:
    _require_keys(payload, {"contractVersion", "game", "generation", "reveal", "cards"}, scope="feed")
    if int(payload["contractVersion"]) < 1:
        raise ValidationError(f"game {game_id} contractVersion must be >= 1")
    game = payload["game"]
    if not isinstance(game, dict) or game.get("gameId") != game_id:
        raise ValidationError(f"game {game_id} feed game identity mismatch")
    generation = payload["generation"]
    if not isinstance(generation, dict):
        raise ValidationError(f"game {game_id} generation must be an object")
    status = generation.get("status")
    if status not in ALLOWED_GENERATION_STATUSES:
        raise ValidationError(f"game {game_id} invalid generation.status {status!r}")
    cards = payload["cards"]
    if not isinstance(cards, list):
        raise ValidationError(f"game {game_id} cards must be a list")
    if len(cards) < min_cards:
        raise ValidationError(f"game {game_id} returned {len(cards)} cards, expected >= {min_cards}")
    expected_count = generation.get("cardCount")
    if isinstance(expected_count, int) and expected_count != len(cards):
        raise ValidationError(
            f"game {game_id} generation.cardCount={expected_count} but cards={len(cards)}"
        )
    for index, card in enumerate(cards):
        if not isinstance(card, dict):
            raise ValidationError(f"game {game_id} card[{index}] must be an object")
        _validate_card(card, game_id=game_id, index=index)
    return len(cards), str(status)


def _validate_debug(payload: dict[str, Any], *, game_id: int) -> None:
    _require_keys(
        payload,
        {"available", "status", "cardCount", "cacheState", "warnings", "errors"},
        scope=f"game {game_id} debug",
    )
    if payload["status"] not in {"available", "not_available", "blocked"}:
        raise ValidationError(f"game {game_id} debug status is invalid: {payload['status']!r}")
    errors = payload.get("errors")
    if errors:
        raise ValidationError(f"game {game_id} debug returned errors: {errors}")


def _validate_summary(
    *,
    base_url: str,
    api_key: str | None,
    game_id: int,
    require_summary: bool,
) -> str:
    payload = _request_json(base_url, f"/api/v1/games/{game_id}/summary", api_key)
    if "summary" not in payload:
        status = payload.get("status")
        if require_summary:
            raise ValidationError(f"game {game_id} summary not generated; status={status!r}")
        return f"summary_status={status}"
    summary = payload.get("summary")
    if not isinstance(summary, list) or not all(_non_empty_string(item) for item in summary):
        raise ValidationError(f"game {game_id} summary must be a non-empty list of strings")
    if payload.get("storyVersion") != "v3-summary":
        raise ValidationError(f"game {game_id} summary storyVersion must be v3-summary")
    if not _non_empty_string(payload.get("modelUsed")):
        raise ValidationError(f"game {game_id} summary missing modelUsed")
    return f"summary_paragraphs={len(summary)} model={payload['modelUsed']}"


def validate(args: argparse.Namespace) -> list[str]:
    api_key = _resolve_api_key(args)
    targets = _select_game_targets(
        base_url=args.base_url,
        api_key=api_key,
        explicit_ids=args.game_id,
        limit=args.limit,
        lookback_days=args.lookback_days,
        lookahead_days=args.lookahead_days,
        max_pages=args.max_pages,
    )
    lines: list[str] = []
    for game_id in targets[: args.max_games]:
        feed = _request_json(
            args.base_url,
            f"/api/v1/feed/games/{game_id}/cards?spoilerPolicy=pre_reveal",
            api_key,
        )
        card_count, status = _validate_feed(feed, game_id=game_id, min_cards=args.min_cards)
        if args.debug:
            debug = _request_json(
                args.base_url,
                f"/api/v1/feed/games/{game_id}/cards/debug?spoilerPolicy=pre_reveal&includeFeed=false",
                api_key,
            )
            _validate_debug(debug, game_id=game_id)
        summary_note = ""
        if args.check_summary:
            summary_note = " " + _validate_summary(
                base_url=args.base_url,
                api_key=api_key,
                game_id=game_id,
                require_summary=args.require_summary,
            )
        lines.append(f"OK game={game_id} cards={card_count} generation={status}{summary_note}")
    return lines


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("API_BASE_URL", "http://localhost:8000"))
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--env-file", default=os.getenv("DEPLOY_ENV_FILE", "infra/.env"))
    parser.add_argument("--game-id", type=int, action="append", default=[])
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--lookahead-days", type=int, default=2)
    parser.add_argument("--max-pages", type=int, default=5)
    parser.add_argument("--max-games", type=int, default=2)
    parser.add_argument("--min-cards", type=int, default=1)
    parser.add_argument("--no-debug", dest="debug", action="store_false", default=True)
    parser.add_argument("--check-summary", action="store_true")
    parser.add_argument("--require-summary", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        for line in validate(args):
            print(line)
    except ValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
