"""Unit tests for pool config discriminated union validation.

Covers PoolConfigValidator.validate() for all valid/invalid input combinations,
and verifies that PoolCreateRequest / PoolUpdateRequest field validators raise
the correct Pydantic ValidationError (which FastAPI converts to HTTP 422).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.pool_config import (
    CrestmontPoolConfig,
    PoolConfigValidator,
    RvccPoolConfig,
    _POOL_CONFIG_ADAPTER,
)
from app.routers.golf.pools_helpers import PoolCreateRequest, PoolUpdateRequest


# ---------------------------------------------------------------------------
# PoolConfigValidator.validate — valid inputs
# ---------------------------------------------------------------------------


class TestPoolConfigValidatorValid:
    def test_rvcc_minimal(self) -> None:
        PoolConfigValidator.validate({"variant": "rvcc"})

    def test_rvcc_full(self) -> None:
        PoolConfigValidator.validate({
            "variant": "rvcc",
            "pick_count": 7,
            "count_best": 5,
            "min_cuts_to_qualify": 5,
            "uses_buckets": False,
        })

    def test_crestmont_full(self) -> None:
        PoolConfigValidator.validate({
            "variant": "crestmont",
            "pick_count": 6,
            "count_best": 4,
            "min_cuts_to_qualify": 4,
            "uses_buckets": True,
            "bucket_count": 6,
        })

    def test_crestmont_minimal(self) -> None:
        # bucket_count has no default — must be explicit
        PoolConfigValidator.validate({
            "variant": "crestmont",
            "bucket_count": 6,
        })


# ---------------------------------------------------------------------------
# PoolConfigValidator.validate — invalid inputs
# ---------------------------------------------------------------------------


class TestPoolConfigValidatorInvalid:
    def test_unknown_variant_raises(self) -> None:
        with pytest.raises(ValueError, match="rules_json"):
            PoolConfigValidator.validate({"variant": "unknown_club"})

    def test_missing_variant_raises(self) -> None:
        with pytest.raises(ValueError, match="rules_json"):
            PoolConfigValidator.validate({"pick_count": 7})

    def test_rvcc_with_bucket_count_raises(self) -> None:
        with pytest.raises(ValueError, match="rules_json"):
            PoolConfigValidator.validate({
                "variant": "rvcc",
                "bucket_count": 6,
            })

    def test_crestmont_without_bucket_count_raises(self) -> None:
        with pytest.raises(ValueError, match="rules_json"):
            PoolConfigValidator.validate({
                "variant": "crestmont",
                "pick_count": 6,
                "count_best": 4,
                "min_cuts_to_qualify": 4,
                "uses_buckets": True,
                # bucket_count missing
            })

    def test_rvcc_wrong_pick_count_raises(self) -> None:
        with pytest.raises(ValueError, match="rules_json"):
            PoolConfigValidator.validate({"variant": "rvcc", "pick_count": 6})

    def test_crestmont_wrong_count_best_raises(self) -> None:
        with pytest.raises(ValueError, match="rules_json"):
            PoolConfigValidator.validate({
                "variant": "crestmont",
                "count_best": 5,
                "bucket_count": 6,
            })

    def test_error_includes_field_path(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            PoolConfigValidator.validate({"variant": "rvcc", "bucket_count": 6})
        assert "rules_json" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Pydantic model shapes
# ---------------------------------------------------------------------------


class TestPoolConfigModels:
    def test_rvcc_model_defaults(self) -> None:
        cfg = RvccPoolConfig(variant="rvcc")
        assert cfg.pick_count == 7
        assert cfg.count_best == 5
        assert cfg.min_cuts_to_qualify == 5
        assert cfg.uses_buckets is False

    def test_crestmont_model_requires_bucket_count(self) -> None:
        with pytest.raises(ValidationError):
            CrestmontPoolConfig(variant="crestmont")  # bucket_count missing

    def test_crestmont_model_valid(self) -> None:
        cfg = CrestmontPoolConfig(variant="crestmont", bucket_count=6)
        assert cfg.pick_count == 6
        assert cfg.count_best == 4
        assert cfg.uses_buckets is True
        assert cfg.bucket_count == 6

    def test_rvcc_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            RvccPoolConfig(variant="rvcc", bucket_count=6)

    def test_crestmont_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            CrestmontPoolConfig(variant="crestmont", bucket_count=6, extra_field="bad")


# ---------------------------------------------------------------------------
# PoolCreateRequest field validator integration (→ HTTP 422)
# ---------------------------------------------------------------------------


def _base_create_kwargs() -> dict:
    return {
        "code": "TEST-2026",
        "name": "Test Pool",
        "club_code": "rvcc",
        "tournament_id": 1,
    }


class TestPoolCreateRequestValidation:
    def test_valid_rvcc_rules_accepted(self) -> None:
        req = PoolCreateRequest(
            **_base_create_kwargs(),
            rules_json={"variant": "rvcc"},
        )
        assert req.rules_json == {"variant": "rvcc"}

    def test_valid_crestmont_rules_accepted(self) -> None:
        req = PoolCreateRequest(
            **_base_create_kwargs(),
            rules_json={"variant": "crestmont", "bucket_count": 6},
        )
        assert req.rules_json is not None

    def test_none_rules_json_accepted(self) -> None:
        req = PoolCreateRequest(**_base_create_kwargs(), rules_json=None)
        assert req.rules_json is None

    def test_unknown_variant_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            PoolCreateRequest(
                **_base_create_kwargs(),
                rules_json={"variant": "unknown"},
            )
        errors = exc_info.value.errors()
        assert any("rules_json" in str(e.get("loc", "")) for e in errors)

    def test_rvcc_with_bucket_fields_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            PoolCreateRequest(
                **_base_create_kwargs(),
                rules_json={"variant": "rvcc", "bucket_count": 6},
            )

    def test_crestmont_without_bucket_count_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            PoolCreateRequest(
                **_base_create_kwargs(),
                rules_json={"variant": "crestmont"},
            )


# ---------------------------------------------------------------------------
# PoolUpdateRequest field validator integration
# ---------------------------------------------------------------------------


class TestPoolUpdateRequestValidation:
    def test_none_rules_json_skips_validation(self) -> None:
        req = PoolUpdateRequest(rules_json=None)
        assert req.rules_json is None

    def test_valid_rvcc_update_accepted(self) -> None:
        req = PoolUpdateRequest(rules_json={"variant": "rvcc"})
        assert req.rules_json is not None

    def test_invalid_rules_json_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            PoolUpdateRequest(rules_json={"variant": "bad"})
