"""Shared Pydantic base for all API response models.

Use ``CamelResponse`` as the base class for any new response schema.
The alias_generator eliminates per-field ``Field(alias=...)`` declarations
and guarantees camelCase on the wire without per-field overhead.

Example::

    class GameSummary(CamelResponse):
        game_id: int          # serialized as "gameId"
        home_team: str        # serialized as "homeTeam"

Internal code can still access fields by their snake_case names because
``populate_by_name=True`` is set. The ``from_attributes=True`` flag allows
direct construction from ORM model instances.
"""

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelResponse(BaseModel):
    """Base class for camelCase JSON response models.

    Subclasses get automatic camelCase wire names without explicit
    ``Field(alias=...)`` on every field.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )
