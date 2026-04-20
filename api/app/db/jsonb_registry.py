"""Central registry of Pydantic schemas for every JSONB column in the ORM.

Each entry maps "table_name.column_name" to a Pydantic model that validates
the expected shape of the column.  Validation is enforced via SQLAlchemy
mapper events (see jsonb_validators.py and external_id_validators.py).

JSON Schema draft-7 files in api/app/db/schemas/jsonb/ are the authoritative
specification; the Pydantic models below are translations of those files.

Usage::

    from app.db.jsonb_registry import validate_jsonb_column
    validate_jsonb_column("sports_games", "external_ids", value)

Raises JsonbValidationError on schema violation.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator, model_validator
from pydantic.alias_generators import to_camel


# ---------------------------------------------------------------------------
# Typed error
# ---------------------------------------------------------------------------


class JsonbValidationError(ValueError):
    """Schema validation failed for a JSONB column."""

    def __init__(self, column_name: str, message: str, field_path: str = "") -> None:
        self.column_name = column_name
        self.field_path = field_path
        super().__init__(f"{column_name}: {message}")


# ---------------------------------------------------------------------------
# Generic structural schemas
# ---------------------------------------------------------------------------


class ExternalIdsSchema(RootModel[dict[str, Any]]):
    """Flat dict[str, str | int] — no nested objects, arrays, booleans, or nulls."""

    @model_validator(mode="after")
    def _check_flat_str_or_int(self) -> "ExternalIdsSchema":
        for key, val in self.root.items():
            if not isinstance(key, str):
                raise ValueError(
                    f"all keys must be strings, got key {key!r} ({type(key).__name__})"
                )
            if isinstance(val, bool) or not isinstance(val, (str, int)):
                raise ValueError(
                    f"[{key!r}] must be str or int, got {type(val).__name__!r}"
                )
        return self


class DictJsonSchema(RootModel[dict[str, Any]]):
    """Any JSON object.  Validates top-level type is object, not array/scalar."""


class ListOfDictsSchema(RootModel[list[dict[str, Any]]]):
    """Any JSON array of objects.  Validates top-level type is array."""


# ---------------------------------------------------------------------------
# Pipeline-specific schemas
# ---------------------------------------------------------------------------

_BLOCK_ROLES = frozenset(
    {"SETUP", "MOMENTUM_SHIFT", "RESPONSE", "DECISION_POINT", "RESOLUTION"}
)
_LOG_LEVELS = frozenset({"info", "warning", "error", "debug"})


class MomentEntrySchema(BaseModel):
    """A single moment object within moments_json.

    Only `play_ids` is required; all other fields are optional since the
    shape may evolve across pipeline versions.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="allow",
    )

    play_ids: list[int]
    explicitly_narrated_play_ids: list[int] = Field(default_factory=list)
    period: int | None = None
    start_clock: str | None = None
    end_clock: str | None = None
    score_before: list[int] | None = None
    score_after: list[int] | None = None


class MomentsJsonSchema(RootModel[list[MomentEntrySchema]]):
    """Validates moments_json: ordered list of MomentEntry objects."""


class BlockEntrySchema(BaseModel):
    """A single narrative block within blocks_json."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="allow",
    )

    block_index: int = Field(ge=0, le=6)
    role: str
    narrative: str = Field(min_length=1)
    moment_indices: list[int] = Field(default_factory=list)
    play_ids: list[int] = Field(default_factory=list)
    key_play_ids: list[int] = Field(default_factory=list)
    period_start: int | None = None
    period_end: int | None = None
    score_before: list[int] | None = None
    score_after: list[int] | None = None
    mini_box: dict[str, Any] | None = None
    peak_margin: int = 0
    peak_leader: int = 0
    start_clock: str | None = None
    end_clock: str | None = None
    resolution_specificity_warning: bool = False
    embedded_social_post_id: int | None = None

    @field_validator("role")
    @classmethod
    def _valid_role(cls, v: str) -> str:
        if v not in _BLOCK_ROLES:
            raise ValueError(
                f"role must be one of {sorted(_BLOCK_ROLES)}, got {v!r}"
            )
        return v


class BlocksJsonSchema(RootModel[list[BlockEntrySchema]]):
    """Validates blocks_json: ordered list of BlockEntry objects."""


class PipelineLogEntrySchema(BaseModel):
    """A single log entry within pipeline_stage.logs_json."""

    model_config = {"extra": "allow"}

    timestamp: str
    level: str
    message: str = Field(min_length=1)

    @field_validator("level")
    @classmethod
    def _valid_level(cls, v: str) -> str:
        if v not in _LOG_LEVELS:
            raise ValueError(
                f"level must be one of {sorted(_LOG_LEVELS)}, got {v!r}"
            )
        return v


class PipelineLogsJsonSchema(RootModel[list[PipelineLogEntrySchema]]):
    """Validates logs_json: ordered list of PipelineLogEntry objects."""


# ---------------------------------------------------------------------------
# Registry — keyed by "table_name.column_name"
# ---------------------------------------------------------------------------

JSONB_REGISTRY: dict[str, type[BaseModel]] = {
    # sports_games.external_ids, sports_teams.external_codes
    "sports_games.external_ids": ExternalIdsSchema,
    "sports_teams.external_codes": ExternalIdsSchema,
    # boxscores — permissive object blob
    "sports_team_boxscores.raw_stats_json": DictJsonSchema,
    "sports_player_boxscores.raw_stats_json": DictJsonSchema,
    # play-by-play raw event payload
    "sports_game_plays.raw_data": DictJsonSchema,
    # game flow / story — detailed structural schemas
    "sports_game_stories.moments_json": MomentsJsonSchema,
    "sports_game_stories.blocks_json": BlocksJsonSchema,
    # pipeline stage execution records
    "sports_game_pipeline_stages.output_json": DictJsonSchema,
    "sports_game_pipeline_stages.logs_json": PipelineLogsJsonSchema,
    # timeline artifacts
    "sports_game_timeline_artifacts.timeline_json": ListOfDictsSchema,
    "sports_game_timeline_artifacts.game_analysis_json": DictJsonSchema,
    "sports_game_timeline_artifacts.summary_json": DictJsonSchema,
}


# ---------------------------------------------------------------------------
# Public helper
# ---------------------------------------------------------------------------


def validate_jsonb_column(table_name: str, column_name: str, value: Any) -> None:
    """Validate *value* against the registered schema for (table_name, column_name).

    No-ops when no schema is registered.  Raises JsonbValidationError on failure.
    """
    schema_cls = JSONB_REGISTRY.get(f"{table_name}.{column_name}")
    if schema_cls is None or value is None:
        return

    try:
        schema_cls.model_validate(value)
    except Exception as exc:
        # Extract the first field location from pydantic ValidationError when available
        field_path = ""
        if hasattr(exc, "errors"):
            errors = exc.errors()
            if errors:
                loc = errors[0].get("loc", ())
                field_path = ".".join(str(p) for p in loc)
        raise JsonbValidationError(
            column_name=column_name,
            message=str(exc),
            field_path=field_path,
        ) from exc
