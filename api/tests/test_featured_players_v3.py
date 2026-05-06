"""Tests for featured_players_v3 — the v3 player-evidence bridge."""

from __future__ import annotations

from app.services.pipeline.helpers.evidence_selection import (
    FeaturedPlayer,
    SegmentEvidence,
)
from app.services.pipeline.stages.featured_players_v3 import (
    annotate_blocks_with_featured_players,
    derive_featured_players,
)


def _evidence(*players: tuple[str, str | None, int]) -> SegmentEvidence:
    return SegmentEvidence(
        featured_players=[
            FeaturedPlayer(name=name, team=team, delta_contribution=delta)
            for name, team, delta in players
        ]
    )


class TestDeriveFeaturedPlayers:
    """Each story_role yields a payload with a non-empty reason for every entry."""

    def test_opening_block_skips_callouts(self) -> None:
        block = {"block_index": 0, "story_role": "opening"}
        evidence = _evidence(("LeBron James", "LAL", 8))
        assert derive_featured_players(block, evidence, "NBA") is None

    def test_blowout_compression_skips_callouts(self) -> None:
        block = {"block_index": 1, "story_role": "blowout_compression"}
        evidence = _evidence(("Aaron Judge", "NYY", 2))
        assert derive_featured_players(block, evidence, "MLB") is None

    def test_first_separation_emits_one_entry_with_reason(self) -> None:
        block = {"block_index": 0, "story_role": "first_separation"}
        evidence = _evidence(("Aaron Judge", "NYY", 1))
        out = derive_featured_players(block, evidence, "MLB")
        assert out is not None
        assert len(out) == 1
        assert out[0]["name"] == "Aaron Judge"
        assert out[0]["team"] == "NYY"
        assert out[0]["role"] == "first_separation_scorer"
        assert out[0]["reason"]
        assert "1 runs" in out[0]["reason"] or "1 run" in out[0]["reason"]

    def test_lead_change_uses_lead_change_role(self) -> None:
        block = {"block_index": 1, "story_role": "lead_change"}
        evidence = _evidence(("Anthony Edwards", "MIN", 6))
        out = derive_featured_players(block, evidence, "NBA")
        assert out is not None
        assert out[0]["role"] == "lead_change_scorer"
        assert "Lead-change" in out[0]["reason"] or "lead-change" in out[0]["reason"].lower()

    def test_response_emits_up_to_two_with_distinct_roles(self) -> None:
        block = {"block_index": 2, "story_role": "response"}
        evidence = _evidence(
            ("Player A", "MIN", 8),
            ("Player B", "MIN", 4),
            ("Player C", "MIN", 2),  # third should be dropped
        )
        out = derive_featured_players(block, evidence, "NBA")
        assert out is not None
        assert len(out) == 2
        assert out[0]["role"] == "response_owner"
        assert out[1]["role"] == "response_supporter"

    def test_turning_point_uses_run_owner_then_supporter(self) -> None:
        block = {"block_index": 3, "story_role": "turning_point"}
        evidence = _evidence(("Star", "MIN", 11), ("Helper", "MIN", 4))
        out = derive_featured_players(block, evidence, "NBA")
        assert out is not None
        assert [p["role"] for p in out] == ["run_owner", "run_supporter"]

    def test_closeout_uses_late_closer_then_supporter(self) -> None:
        block = {"block_index": 4, "story_role": "closeout"}
        evidence = _evidence(("Closer", "MIN", 8), ("Helper", "MIN", 3))
        out = derive_featured_players(block, evidence, "NBA")
        assert out is not None
        assert [p["role"] for p in out] == ["late_closer", "closeout_supporter"]
        assert "Iced" in out[0]["reason"] or "iced" in out[0]["reason"].lower()

    def test_nhl_reasons_use_goals_unit(self) -> None:
        block = {"block_index": 1, "story_role": "lead_change"}
        evidence = _evidence(("Connor McDavid", "EDM", 1))
        out = derive_featured_players(block, evidence, "NHL")
        assert out is not None
        # The lead_change template uses unit[:-1] → "goal".
        assert "goal" in out[0]["reason"].lower()

    def test_mlb_reasons_use_runs_unit(self) -> None:
        block = {"block_index": 0, "story_role": "first_separation"}
        evidence = _evidence(("Aaron Judge", "NYY", 2))
        out = derive_featured_players(block, evidence, "MLB")
        assert out is not None
        assert "runs" in out[0]["reason"].lower()

    def test_stat_summary_format_is_compact_and_signed(self) -> None:
        block = {"block_index": 1, "story_role": "lead_change"}
        evidence = _evidence(("Player", "X", 11))
        out = derive_featured_players(block, evidence, "NBA")
        assert out is not None
        assert out[0]["stat_summary"] == "+11 pts (segment)"

    def test_singular_unit_is_used_for_delta_one(self) -> None:
        block = {"block_index": 1, "story_role": "first_separation"}
        evidence = _evidence(("Solo", "X", 1))
        out_nhl = derive_featured_players(block, evidence, "NHL")
        out_mlb = derive_featured_players(block, evidence, "MLB")
        out_nba = derive_featured_players(block, evidence, "NBA")
        assert out_nhl is not None and out_nhl[0]["stat_summary"] == "+1 goal (segment)"
        assert out_mlb is not None and out_mlb[0]["stat_summary"] == "+1 run (segment)"
        assert out_nba is not None and out_nba[0]["stat_summary"] == "+1 pt (segment)"

    def test_empty_evidence_returns_none(self) -> None:
        block = {"block_index": 1, "story_role": "lead_change"}
        assert derive_featured_players(block, None, "NBA") is None
        assert derive_featured_players(block, SegmentEvidence(), "NBA") is None

    def test_missing_story_role_returns_none(self) -> None:
        block = {"block_index": 1}
        evidence = _evidence(("X", "X", 5))
        assert derive_featured_players(block, evidence, "NBA") is None

    def test_player_with_blank_name_is_dropped(self) -> None:
        block = {"block_index": 1, "story_role": "response"}
        evidence = _evidence(("", "X", 8), ("Real", "X", 4))
        out = derive_featured_players(block, evidence, "NBA")
        assert out is not None
        assert all(p["name"] for p in out)
        assert out[0]["name"] == "Real"


class TestAnnotateBlocksWithFeaturedPlayers:
    def test_attaches_featured_players_to_eligible_blocks(self) -> None:
        blocks = [
            {"block_index": 0, "story_role": "opening"},
            {"block_index": 1, "story_role": "lead_change"},
            {"block_index": 2, "story_role": "blowout_compression"},
            {"block_index": 3, "story_role": "closeout"},
        ]
        evidence_by_block = {
            0: _evidence(("Setter Upper", "X", 6)),
            1: _evidence(("Flipper", "X", 7)),
            2: _evidence(("Padded", "X", 1)),
            3: _evidence(("Closer", "X", 8), ("Helper", "X", 3)),
        }

        annotate_blocks_with_featured_players(blocks, evidence_by_block, "NBA")

        # Opening + blowout_compression are skipped → field stays absent.
        assert "featured_players" not in blocks[0]
        assert "featured_players" not in blocks[2]

        # Lead-change + closeout are populated.
        assert len(blocks[1]["featured_players"]) == 1
        assert blocks[1]["featured_players"][0]["role"] == "lead_change_scorer"
        assert len(blocks[3]["featured_players"]) == 2
        assert blocks[3]["featured_players"][0]["role"] == "late_closer"

    def test_missing_evidence_for_block_leaves_field_unset(self) -> None:
        blocks = [{"block_index": 0, "story_role": "lead_change"}]
        annotate_blocks_with_featured_players(blocks, {}, "NBA")
        assert "featured_players" not in blocks[0]


class TestRule18CompatibilityByConstruction:
    """Every featured_players entry produced by the bridge carries a non-empty
    reason — the validator from Pass 1 (Rule 18) passes for any block we emit."""

    def test_every_role_yields_non_empty_reasons(self) -> None:
        from app.services.pipeline.stages.validate_blocks_voice import (
            validate_featured_players_have_reason,
        )

        evidence = _evidence(("Star", "X", 9), ("Helper", "X", 3))
        for story_role in [
            "first_separation",
            "response",
            "lead_change",
            "turning_point",
            "closeout",
        ]:
            block = {"block_index": 0, "story_role": story_role}
            block["featured_players"] = derive_featured_players(
                block, evidence, "NBA"
            )
            errors, _ = validate_featured_players_have_reason([block])
            assert errors == [], f"role {story_role} produced reason violations"
