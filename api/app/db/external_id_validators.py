"""SQLAlchemy event hooks that enforce the shape of external_ids / external_codes JSONB columns.

Both columns store a flat dict[str, str | int] — no nested objects, no arrays.
Validation fires on every insert and update via mapper-level before_{insert,update} events.
Raises JsonbValidationError on invalid payloads so the DB write is aborted before any SQL is issued.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import event

from .jsonb_registry import JsonbValidationError
from .sports import SportsGame, SportsTeam


def _validate_flat_str_or_int_dict(value: Any, field_name: str) -> None:
    """Validate that *value* is a flat dict mapping str keys to str or int values.

    Raises:
        JsonbValidationError: if the value is not a dict, has non-string keys, or has
                    values that are not str or int (booleans are rejected because
                    bool is a subclass of int but semantically wrong here).
    """
    if not isinstance(value, dict):
        raise JsonbValidationError(
            column_name=field_name,
            message=f"must be a JSON object (dict), got {type(value).__name__!r}",
        )
    for key, val in value.items():
        if not isinstance(key, str):
            raise JsonbValidationError(
                column_name=field_name,
                message=f"all keys must be strings, got key {key!r} of type {type(key).__name__!r}",
                field_path=str(key),
            )
        if isinstance(val, bool) or not isinstance(val, (str, int)):
            raise JsonbValidationError(
                column_name=field_name,
                message=f"[{key!r}] must be a string or integer, got {type(val).__name__!r}",
                field_path=key,
            )


# ---------------------------------------------------------------------------
# Mapper-level event listeners — fire synchronously before INSERT / UPDATE SQL
# ---------------------------------------------------------------------------


@event.listens_for(SportsGame, "before_insert")
@event.listens_for(SportsGame, "before_update")
def _validate_game_external_ids(mapper, connection, target: SportsGame) -> None:
    if target.external_ids is not None:
        _validate_flat_str_or_int_dict(target.external_ids, "SportsGame.external_ids")


@event.listens_for(SportsTeam, "before_insert")
@event.listens_for(SportsTeam, "before_update")
def _validate_team_external_codes(mapper, connection, target: SportsTeam) -> None:
    if target.external_codes is not None:
        _validate_flat_str_or_int_dict(target.external_codes, "SportsTeam.external_codes")
