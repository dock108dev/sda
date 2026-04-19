"""Tests for JSONB shape validation on external_ids / external_codes columns."""

from __future__ import annotations

import pytest

from app.db.external_id_validators import _validate_flat_str_or_int_dict


class TestValidateFlatStrOrIntDict:
    """Unit tests for the core validation function."""

    # --- Valid inputs ---

    def test_empty_dict_is_valid(self) -> None:
        _validate_flat_str_or_int_dict({}, "col")

    def test_string_values_are_valid(self) -> None:
        _validate_flat_str_or_int_dict(
            {"nba_game_id": "0022400123", "odds_api_event_id": "evt_abc"}, "col"
        )

    def test_int_values_are_valid(self) -> None:
        _validate_flat_str_or_int_dict({"cbb_game_id": 401547123}, "col")

    def test_mixed_str_and_int_values_are_valid(self) -> None:
        _validate_flat_str_or_int_dict(
            {"nba_game_id": "0022400123", "cbb_game_id": 401547123}, "col"
        )

    def test_all_known_game_id_keys_pass(self) -> None:
        payload = {
            "nba_game_id": "0022400123",
            "mlb_game_pk": "651785",
            "espn_game_id": "12345",
            "cbb_game_id": 401547123,
            "ncaa_game_id": "202412340002",
            "nhl_game_pk": "2024020001",
            "odds_api_event_id": "evt_abc123",
        }
        _validate_flat_str_or_int_dict(payload, "SportsGame.external_ids")

    def test_unknown_keys_are_permitted(self) -> None:
        _validate_flat_str_or_int_dict({"future_provider_id": "xyz"}, "col")

    # --- Invalid inputs — structure ---

    def test_list_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be a JSON object"):
            _validate_flat_str_or_int_dict([], "col")

    def test_string_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be a JSON object"):
            _validate_flat_str_or_int_dict("bad", "col")

    def test_int_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be a JSON object"):
            _validate_flat_str_or_int_dict(42, "col")

    def test_none_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be a JSON object"):
            _validate_flat_str_or_int_dict(None, "col")

    # --- Invalid inputs — values ---

    def test_nested_dict_value_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be a string or integer"):
            _validate_flat_str_or_int_dict({"key": {"nested": "obj"}}, "col")

    def test_list_value_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be a string or integer"):
            _validate_flat_str_or_int_dict({"key": [1, 2, 3]}, "col")

    def test_float_value_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be a string or integer"):
            _validate_flat_str_or_int_dict({"key": 1.5}, "col")

    def test_null_value_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be a string or integer"):
            _validate_flat_str_or_int_dict({"key": None}, "col")

    def test_bool_value_is_rejected(self) -> None:
        # bool is a subclass of int — must be explicitly rejected
        with pytest.raises(ValueError, match="must be a string or integer"):
            _validate_flat_str_or_int_dict({"key": True}, "col")

    # --- Error message includes field name ---

    def test_error_message_includes_field_name(self) -> None:
        with pytest.raises(ValueError, match="SportsGame.external_ids"):
            _validate_flat_str_or_int_dict([], "SportsGame.external_ids")

    def test_error_message_includes_offending_key(self) -> None:
        with pytest.raises(ValueError, match="bad_key"):
            _validate_flat_str_or_int_dict({"bad_key": {"nested": True}}, "col")


class TestSportsGameEventHook:
    """Verify that the mapper event hooks are registered on the ORM classes."""

    def test_game_hook_fires_on_invalid_external_ids(self) -> None:
        """Assigning an invalid payload to SportsGame.external_ids raises ValueError."""
        from unittest.mock import MagicMock

        from app.db.external_id_validators import _validate_game_external_ids

        game = MagicMock()
        game.external_ids = [{"bad": "list"}]

        with pytest.raises(ValueError, match="SportsGame.external_ids"):
            _validate_game_external_ids(None, None, game)

    def test_game_hook_accepts_valid_external_ids(self) -> None:
        from unittest.mock import MagicMock

        from app.db.external_id_validators import _validate_game_external_ids

        game = MagicMock()
        game.external_ids = {"nba_game_id": "0022400123"}

        # Should not raise
        _validate_game_external_ids(None, None, game)

    def test_game_hook_skips_none(self) -> None:
        """None external_ids (not yet set) should not raise."""
        from unittest.mock import MagicMock

        from app.db.external_id_validators import _validate_game_external_ids

        game = MagicMock()
        game.external_ids = None

        # Should not raise
        _validate_game_external_ids(None, None, game)

    def test_team_hook_fires_on_invalid_external_codes(self) -> None:
        from unittest.mock import MagicMock

        from app.db.external_id_validators import _validate_team_external_codes

        team = MagicMock()
        team.external_codes = ["not", "a", "dict"]

        with pytest.raises(ValueError, match="SportsTeam.external_codes"):
            _validate_team_external_codes(None, None, team)

    def test_team_hook_accepts_valid_external_codes(self) -> None:
        from unittest.mock import MagicMock

        from app.db.external_id_validators import _validate_team_external_codes

        team = MagicMock()
        team.external_codes = {"cbb_team_id": 1234}

        # Should not raise
        _validate_team_external_codes(None, None, team)
