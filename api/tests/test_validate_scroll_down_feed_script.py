from __future__ import annotations

import importlib.util
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
        "visualImportance": "high",
        "period": {"ordinal": 8, "label": "8th", "type": "inning"},
        "team": {"abbreviation": "ARI", "name": "Arizona", "side": "away"},
        "situation": {"summary": "Top 8, runner on 2nd, 1 out"},
        "leadIn": "8th - ARI",
        "stageSetting": "Top 8, runner on 2nd, 1 out",
        "headline": "RBI double",
        "description": "Arizona doubles into the gap.",
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
        "contractVersion": 1,
        "game": {"gameId": 42, "sport": "baseball", "league": "MLB"},
        "generation": {"status": "ready", "cardCount": 1},
        "reveal": {"available": True},
        "cards": [card],
    }


def test_validator_accepts_frontend_ready_card_feed() -> None:
    card_count, status = validator._validate_feed(_feed(_card()), game_id=42, min_cards=1)

    assert card_count == 1
    assert status == "ready"


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


def test_validator_loads_consumer_key_from_deploy_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("API_KEY=admin-key\nCONSUMER_API_KEY=consumer-key\n", encoding="utf-8")
    args = SimpleNamespace(api_key=None, env_file=str(env_file))

    assert validator._resolve_api_key(args) == "consumer-key"
