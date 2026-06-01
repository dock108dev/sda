from __future__ import annotations

import importlib.util
import urllib.parse
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "validate_scroll_down_feed.py"
SPEC = importlib.util.spec_from_file_location("validate_scroll_down_feed", SCRIPT_PATH)
assert SPEC and SPEC.loader
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


def _card(**overrides):
    card = {
        "id": "game:1",
        "gameId": 42,
        "sourcePlayId": "provider-1",
        "playIndex": 1,
        "sport": "baseball",
        "league": "MLB",
        "tier": 1,
        "contentDepth": "extended",
        "modeEligibility": {"important": True, "standard": True, "all": True},
        "importance": {
            "schemaVersion": 1,
            "level": "primary",
            "rank": 1,
            "bucket": "scoring",
            "reasons": ["scoring"],
            "isKeyMoment": True,
            "isScoringPlay": True,
            "isLeadChange": False,
            "isTyingPlay": False,
            "isLateGame": False,
            "isFinalPlay": False,
            "isRunEnding": False,
        },
        "renderType": "important_narrative",
        "visualImportance": "high",
        "period": {"ordinal": 8, "label": "8th", "type": "inning"},
        "team": {"abbreviation": "ARI", "name": "Arizona", "side": "away"},
        "situation": {"summary": "Top 8, runner on 2nd, 1 out"},
        "leadIn": "8th - ARI",
        "stageSetting": "Top 8, runner on 2nd, 1 out",
        "headline": "RBI double",
        "description": "Arizona doubles into the gap.",
        "setupLine": "Arizona down 3-2, runner on 2nd, 1 out.",
        "playLine": "Arizona doubles into the gap.",
        "updateLine": "Arizona scores 1 run.",
        "spoilerLevel": "none",
        "textFieldSpoilerLevels": {
            "leadIn": "earnedAtPlay",
            "stageSetting": "earnedAtPlay",
            "headline": "earnedAtPlay",
            "description": "earnedAtPlay",
        },
    }
    card.update(overrides)
    return card


def _feed(card):
    return {
        "contractVersion": 2,
        "game": {"gameId": 42, "sport": "baseball", "league": "MLB"},
        "generation": {"status": "ready", "cardCount": 1},
        "reveal": {"available": True},
        "cards": [card],
    }


def test_validator_accepts_frontend_ready_card_feed() -> None:
    card_count, status = validator._validate_feed(_feed(_card()), game_id=42, min_cards=1)

    assert card_count == 1
    assert status == "ready"


def test_validator_rejects_old_card_feed_contract() -> None:
    feed = _feed(_card())
    feed["contractVersion"] = 1

    with pytest.raises(validator.ValidationError, match="contractVersion must be >= 2"):
        validator._validate_feed(feed, game_id=42, min_cards=1)


def test_validator_rejects_important_card_without_real_stage_setting() -> None:
    with pytest.raises(validator.ValidationError, match="duplicates leadIn"):
        validator._validate_feed(
            _feed(_card(stageSetting="8th - ARI")),
            game_id=42,
            min_cards=1,
        )


def test_validator_rejects_missing_mode_eligibility_all() -> None:
    with pytest.raises(validator.ValidationError, match="modeEligibility.all"):
        validator._validate_feed(
            _feed(_card(modeEligibility={"important": True, "standard": True, "all": False})),
            game_id=42,
            min_cards=1,
        )


def test_validator_prefers_env_file_consumer_key_over_process_admin_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("API_KEY=admin-key\nCONSUMER_API_KEY=consumer-key\n", encoding="utf-8")
    args = SimpleNamespace(api_key=None, env_file=str(env_file))
    monkeypatch.setenv("API_KEY", "process-admin-key")

    assert validator._resolve_api_key(args) == "consumer-key"


def test_selector_scans_dated_pages_for_pbp_games(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_paths: list[str] = []

    def fake_request_json(base_url: str, path: str, api_key: str | None):
        seen_paths.append(path)
        parsed = urllib.parse.urlparse(path)
        assert parsed.path == "/api/v1/games"
        query = urllib.parse.parse_qs(parsed.query)
        assert query["limit"] == ["200"]
        assert query["sort"] == ["chronological"]
        assert "startDate" in query
        assert "endDate" in query
        if query["offset"] == ["0"]:
            return {
                "games": [{"id": 99, "hasPbp": False, "playCount": 0}],
                "nextOffset": 200,
            }
        if query["offset"] == ["200"]:
            return {
                "games": [{"id": 100, "hasPbp": True, "playCount": 18}],
                "nextOffset": None,
            }
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(validator, "_request_json", fake_request_json)

    assert validator._select_game_targets(
        base_url="http://example.test",
        api_key="key",
        explicit_ids=[],
        limit=200,
        lookback_days=30,
        lookahead_days=2,
        max_pages=5,
    ) == [100]
    assert len(seen_paths) == 2


def test_selector_fails_when_dated_window_has_no_pbp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        validator,
        "_request_json",
        lambda base_url, path, api_key: {
            "games": [{"id": 99, "hasPbp": False, "playCount": 0}],
            "nextOffset": None,
        },
    )

    with pytest.raises(validator.ValidationError, match="Run poll_live_pbp/backfill"):
        validator._select_game_targets(
            base_url="http://example.test",
            api_key="key",
            explicit_ids=[],
            limit=200,
            lookback_days=30,
            lookahead_days=2,
            max_pages=5,
        )


def test_selector_keeps_explicit_game_ids_strict() -> None:
    assert validator._select_game_targets(
        base_url="http://example.test",
        api_key="key",
        explicit_ids=[190584, 190552],
        limit=200,
        lookback_days=30,
        lookahead_days=2,
        max_pages=5,
    ) == [190584, 190552]


def test_validate_skips_unmaterialized_candidates_until_feed_is_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_paths: list[str] = []

    monkeypatch.setattr(
        validator,
        "_select_game_targets",
        lambda **kwargs: [190094, 190584],
    )

    def fake_request_json(base_url: str, path: str, api_key: str | None):
        requested_paths.append(path)
        if path.startswith("/api/v1/feed/games/190094/cards?"):
            raise validator.HTTPValidationError(
                (
                    f"{path} returned HTTP 404: "
                    '{"detail":"Card feed has not been materialized for this game."}'
                ),
                status_code=404,
                detail='{"detail":"Card feed has not been materialized for this game."}',
            )
        if path.startswith("/api/v1/feed/games/190584/cards?"):
            feed = _feed(_card())
            feed["game"]["gameId"] = 190584
            feed["cards"][0]["gameId"] = 190584
            return feed
        if path.startswith("/api/v1/feed/games/190584/cards/debug?"):
            return {
                "available": True,
                "status": "available",
                "cardCount": 1,
                "cacheState": "current",
                "warnings": [],
                "errors": [],
            }
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(validator, "_request_json", fake_request_json)

    lines = validator.validate(
        SimpleNamespace(
            base_url="http://example.test",
            api_key=None,
            env_file="/missing/.env",
            game_id=[],
            limit=200,
            lookback_days=3,
            lookahead_days=3,
            max_pages=5,
            max_games=1,
            min_cards=1,
            debug=True,
            check_summary=False,
            require_summary=False,
        )
    )

    assert lines == ["OK game=190584 cards=1 generation=ready"]
    assert requested_paths[0].startswith("/api/v1/feed/games/190094/cards?")


def test_validate_fails_when_window_has_no_materialized_feeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        validator,
        "_select_game_targets",
        lambda **kwargs: [190094],
    )

    def fake_request_json(base_url: str, path: str, api_key: str | None):
        raise validator.HTTPValidationError(
            (
                f"{path} returned HTTP 404: "
                '{"detail":"Card feed has not been materialized for this game."}'
            ),
            status_code=404,
            detail='{"detail":"Card feed has not been materialized for this game."}',
        )

    monkeypatch.setattr(validator, "_request_json", fake_request_json)

    with pytest.raises(validator.ValidationError, match="no materialized card feeds"):
        validator.validate(
            SimpleNamespace(
                base_url="http://example.test",
                api_key=None,
                env_file="/missing/.env",
                game_id=[],
                limit=200,
                lookback_days=3,
                lookahead_days=3,
                max_pages=5,
                max_games=1,
                min_cards=1,
                debug=True,
                check_summary=False,
                require_summary=False,
            )
        )
