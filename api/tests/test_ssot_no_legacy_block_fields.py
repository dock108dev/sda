"""SSOT regression guard: legacy block-shape symbols must not reappear.

The v3 segmentation/voice contract is the single source of truth for
narrative blocks. The destructive cleanup pass removed:

  - GameFlowBlock / NarrativeBlock fields: ``reason``, ``label``,
    ``lead_before``, ``lead_after``, ``evidence``.
  - ScoreContext subfields: ``start_score`` / ``end_score`` (duplicated
    block-level ``score_before`` / ``score_after``).
  - Helpers: ``compute_block_label``, ``_signed_lead``,
    ``_ensure_v2_block_fields``.
  - Validators: ``validate_lead_consistency`` (Rule 12),
    ``validate_reason_present`` (Rule 15),
    ``validate_evidence_present`` (Rule 16).

These tests fail loudly if anything reintroduces them so a future PR
can't silently put us back on the v2 path.
"""

from __future__ import annotations


class TestLegacyBlockHelpersAbsent:
    def test_compute_block_label_is_gone(self) -> None:
        from app.services.pipeline.stages import group_helpers

        assert not hasattr(group_helpers, "compute_block_label"), (
            "compute_block_label was removed in the v3 SSOT cleanup. "
            "story_role (set by classify_blocks) is the SSOT for the "
            "narrative-job concept."
        )

    def test_signed_lead_helper_is_gone(self) -> None:
        from app.services.pipeline.stages import finalize_moments

        assert not hasattr(finalize_moments, "_signed_lead"), (
            "_signed_lead was removed; leadBefore/leadAfter no longer exist "
            "on the block schema. Derive from score_before/score_after."
        )

    def test_ensure_v2_block_fields_helper_is_gone(self) -> None:
        from app.services.pipeline.stages import finalize_moments

        assert not hasattr(finalize_moments, "_ensure_v2_block_fields"), (
            "_ensure_v2_block_fields was removed; the v3 contract is the "
            "single source of truth for block fields."
        )


class TestLegacyValidatorsAbsent:
    def test_rule_12_lead_consistency_validator_is_gone(self) -> None:
        from app.services.pipeline.stages import validate_blocks_segments

        assert not hasattr(validate_blocks_segments, "validate_lead_consistency"), (
            "validate_lead_consistency (Rule 12) was removed. Score "
            "continuity is enforced by Rule 4 (validate_score_continuity) "
            "via score_before/score_after."
        )

    def test_rule_15_reason_validator_is_gone(self) -> None:
        from app.services.pipeline.stages import validate_blocks_segments

        assert not hasattr(validate_blocks_segments, "validate_reason_present"), (
            "validate_reason_present (Rule 15) was removed. The 'block must "
            "explain why' contract is owned by Rule 18 "
            "(validate_featured_players_have_reason)."
        )

    def test_rule_16_evidence_validator_is_gone(self) -> None:
        from app.services.pipeline.stages import validate_blocks_segments

        assert not hasattr(validate_blocks_segments, "validate_evidence_present"), (
            "validate_evidence_present (Rule 16) was removed. Structured "
            "player evidence lives in featured_players (set by "
            "featured_players_v3.derive_featured_players)."
        )

    def test_validate_blocks_does_not_alias_removed_validators(self) -> None:
        from app.services.pipeline.stages import validate_blocks

        for name in (
            "_validate_lead_consistency",
            "_validate_reason_present",
            "_validate_evidence_present",
        ):
            assert not hasattr(validate_blocks, name), (
                f"{name} was a back-compat alias for a removed validator; "
                f"delete it instead of reintroducing the underlying rule."
            )


class TestSchemaLegacyFieldsAbsent:
    def test_game_flow_block_does_not_declare_v2_fields(self) -> None:
        from app.routers.sports.schemas.game_flow import GameFlowBlock

        legacy = {"reason", "label", "lead_before", "lead_after", "evidence"}
        present = legacy & set(GameFlowBlock.model_fields.keys())
        assert present == set(), (
            f"GameFlowBlock declares legacy v2 fields {sorted(present)}; "
            f"they were removed in the SSOT cleanup. story_role / "
            f"featured_players[*].reason are the v3 replacements."
        )

    def test_score_context_does_not_duplicate_block_score_fields(self) -> None:
        from app.routers.sports.schemas.game_flow import ScoreContext

        for name in ("start_score", "end_score"):
            assert name not in ScoreContext.model_fields, (
                f"ScoreContext.{name} was removed; the SSOT for segment "
                f"endpoints is GameFlowBlock.score_before / score_after. "
                f"Re-adding it would create a sync hazard."
            )

    def test_narrative_block_dataclass_does_not_carry_v2_label(self) -> None:
        from app.services.pipeline.stages.block_types import NarrativeBlock
        import dataclasses

        field_names = {f.name for f in dataclasses.fields(NarrativeBlock)}
        assert "label" not in field_names, (
            "NarrativeBlock.label was removed; story_role (set by "
            "segment_classification.classify_blocks) is the SSOT for the "
            "narrative-job concept."
        )
        # Ensure v3 fields are present so deletion didn't go too far.
        assert "story_role" in field_names
        assert "leverage" in field_names
        assert "score_context" in field_names
        assert "featured_players" in field_names


class TestRule19IsStrict:
    """story_role required (FAIL, not WARNING). Promotes from Pass 3 must hold."""

    def test_missing_story_role_returns_errors_not_warnings(self) -> None:
        from app.services.pipeline.stages.validate_blocks_voice import (
            validate_story_role_present,
        )

        errors, warnings = validate_story_role_present([{"block_index": 0}])
        assert errors, "Rule 19 must FAIL when story_role is missing"
        assert warnings == [], (
            "Rule 19 was promoted to ERROR in Pass 3 — warnings would "
            "demote it back to soft-mode."
        )
