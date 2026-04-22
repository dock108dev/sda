"""Pydantic discriminated union for pool rules_json validation.

This schema is the Python mirror of the Zod discriminated union in
packages/js-core/src/pool-config.ts.  Both must stay in sync.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError


class RvccPoolConfig(BaseModel):
    """Rules for RVCC variant: 7 picks, best 5 count, min 5 cuts, no buckets."""

    model_config = ConfigDict(extra="forbid")

    variant: Literal["rvcc"]
    pick_count: Literal[7] = 7
    count_best: Literal[5] = 5
    min_cuts_to_qualify: Literal[5] = 5
    uses_buckets: Literal[False] = False


class CrestmontPoolConfig(BaseModel):
    """Rules for Crestmont variant: 6 picks, best 4 count, min 4 cuts, 6 buckets."""

    model_config = ConfigDict(extra="forbid")

    variant: Literal["crestmont"]
    pick_count: Literal[6] = 6
    count_best: Literal[4] = 4
    min_cuts_to_qualify: Literal[4] = 4
    uses_buckets: Literal[True] = True
    bucket_count: Literal[6]  # required — no default enforces explicit declaration


PoolConfig = Annotated[
    Union[RvccPoolConfig, CrestmontPoolConfig],
    Field(discriminator="variant"),
]

_POOL_CONFIG_ADAPTER: TypeAdapter[PoolConfig] = TypeAdapter(PoolConfig)


class PoolConfigValidator:
    """Validates pool rules_json against the known pool variants.

    Acts as the single enforcement point so create and update paths
    share identical validation semantics.
    """

    @staticmethod
    def validate(rules_json: dict[str, Any]) -> None:
        """Validate rules_json against the discriminated union.

        Raises ValueError with a dotted field path prefix on failure so
        callers (and FastAPI field validators) can surface actionable errors.
        """
        try:
            _POOL_CONFIG_ADAPTER.validate_python(rules_json)
        except ValidationError as exc:
            errors = exc.errors(include_url=False)
            first = errors[0] if errors else {}
            loc_parts = [str(p) for p in first.get("loc", [])]
            loc = ".".join(loc_parts) if loc_parts else ""
            msg = first.get("msg", "Invalid pool configuration")
            field_path = f"rules_json.{loc}" if loc else "rules_json"
            raise ValueError(f"{field_path}: {msg}") from exc
