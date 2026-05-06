"""Pass 4 golden fixtures — end-to-end shape assertions for the v3
segmentation contract. Each fixture builds a realistic moment sequence
for a sport + game-shape pair, runs it through ``execute_group_blocks``,
and asserts on:

    - block count appropriate for the game shape
    - story_role distribution (opening, first_separation, …, closeout)
    - leverage tags (high in close clutch, low in blowout middles)
    - period_range strings render with the right sport prefix
    - banned phrases never sneak into block labels / narratives we control
    - blowout merge actually collapses adjacent compression blocks

LLM rendering is not exercised — these tests target the deterministic
segmentation + classification path. The brief's voice contract (banned
phrases, featured-player reasons) is covered by the dedicated unit tests
in ``test_validate_blocks.py`` and ``test_featured_players_v3.py``.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.services.pipeline.models import StageInput
from app.services.pipeline.stages.group_blocks import execute_group_blocks
from app.services.pipeline.stages.segment_classification import (
    VALID_LEVERAGE,
    VALID_STORY_ROLES,
)


# ---------------------------------------------------------------------------
# Moment-builder helpers — keep golden fixtures readable.
# ---------------------------------------------------------------------------


def _moment(
    play_id: int,
    period: int,
    home_before: int,
    away_before: int,
    home_after: int,
    away_after: int,
    *,
    start_clock: str | None = None,
    end_clock: str | None = None,
) -> dict[str, Any]:
    return {
        "play_ids": [play_id],
        "period": period,
        "score_before": [home_before, away_before],
        "score_after": [home_after, away_after],
        "start_clock": start_clock,
        "end_clock": end_clock,
    }


def _run(
    moments: list[dict[str, Any]],
    sport: str,
    *,
    archetype: str | None = None,
    home_team_name: str = "Home",
    away_team_name: str = "Away",
) -> dict[str, Any]:
    """Invoke execute_group_blocks and return the resulting data dict."""
    previous: dict[str, Any] = {
        "validated": True,
        "moments": moments,
        "pbp_events": [],
    }
    if archetype:
        previous["archetype"] = archetype

    stage_input = StageInput(
        game_id=1,
        run_id=1,
        previous_output=previous,
        game_context={
            "home_team": home_team_name,
            "away_team": away_team_name,
            "home_team_name": home_team_name,
            "away_team_name": away_team_name,
            "sport": sport,
        },
    )
    return asyncio.run(execute_group_blocks(stage_input)).data


def _block_assertions(blocks: list[dict[str, Any]]) -> None:
    """Universal checks every golden fixture should satisfy."""
    assert blocks, "expected at least one block"
    for block in blocks:
        story_role = block.get("story_role")
        leverage = block.get("leverage")
        period_range = block.get("period_range")
        score_context = block.get("score_context")

        assert story_role in VALID_STORY_ROLES, (
            f"block {block['block_index']} has invalid story_role={story_role!r}"
        )
        assert leverage in VALID_LEVERAGE, (
            f"block {block['block_index']} has invalid leverage={leverage!r}"
        )
        assert isinstance(period_range, str) and period_range, (
            f"block {block['block_index']} missing period_range"
        )
        assert score_context is not None, (
            f"block {block['block_index']} missing score_context"
        )
        assert "lead_change" in score_context
        assert "largest_lead_delta" in score_context

    # First block always opening, last always closeout.
    assert blocks[0]["story_role"] == "opening"
    assert blocks[-1]["story_role"] == "closeout"


# ---------------------------------------------------------------------------
# MLB BLOWOUT — Yankees 12, Orioles 1 (the screenshot fixture from the brief)
# ---------------------------------------------------------------------------
# Shape: HR in 1st creates first separation; multi-run inning in the 5th turns
# the lead into a rout; late innings pile on without drama. The blowout merger
# should collapse adjacent low-leverage middles so the flow doesn't read as
# "Inning 1 → Inning 1–7 → Inning 8–9".


def _mlb_blowout_moments() -> list[dict[str, Any]]:
    return [
        # Inning 1 — Judge solo HR puts NYY up 1-0
        _moment(1, 1, 0, 0, 1, 0),
        # Inning 2 — Wells RBI → 2-0
        _moment(2, 2, 1, 0, 2, 0),
        # Inning 3 — Bellinger sac fly → 3-0
        _moment(3, 3, 2, 0, 3, 0),
        # Inning 4 — Orioles solo HR (Cowser) → 3-1
        _moment(4, 4, 3, 0, 3, 1),
        # Inning 5 — 3-run inning by NYY → 6-1 (the rout starts)
        _moment(5, 5, 3, 1, 6, 1),
        # Inning 6 — McMahon RBI single → 7-1
        _moment(6, 6, 6, 1, 7, 1),
        # Inning 7 — Caballero single drives in 1 → 8-1
        _moment(7, 7, 7, 1, 8, 1),
        # Inning 8 — 2-run double → 10-1
        _moment(8, 8, 8, 1, 10, 1),
        # Inning 9 — Late insurance HR → 12-1 final
        _moment(9, 9, 10, 1, 12, 1),
    ]


class TestMLBBlowoutGolden:
    def test_shape(self) -> None:
        result = _run(_mlb_blowout_moments(), "MLB", archetype="blowout")
        blocks = result["blocks"]
        _block_assertions(blocks)

        assert result["is_blowout"] is True
        # 2-4 blocks for blowouts per the brief.
        assert 2 <= len(blocks) <= 4, f"got {len(blocks)} blocks: {[b['story_role'] for b in blocks]}"

    def test_no_dramatic_middle_roles(self) -> None:
        """Middle blocks in a blowout must never be lead_change, response, or
        turning_point — the brief explicitly forbids pretending it was
        dramatic. ``first_separation`` and ``blowout_compression`` are the
        only valid middle beats; the merger keeps the latter compact."""
        result = _run(_mlb_blowout_moments(), "MLB", archetype="blowout")
        blocks = result["blocks"]
        roles = [b["story_role"] for b in blocks]
        forbidden = {"lead_change", "response", "turning_point"}
        for role in roles[1:-1]:
            assert role not in forbidden, (
                f"middle role {role!r} in MLB blowout reads as drama. "
                f"Full roles={roles}"
            )

    def test_at_least_one_compression_or_merger_present(self) -> None:
        """The middle of a 12-1 game must show compression somewhere — either
        a ``blowout_compression`` block survives, or the classifier produced
        ≤1 middle blocks because the merger collapsed them."""
        result = _run(_mlb_blowout_moments(), "MLB", archetype="blowout")
        blocks = result["blocks"]
        middle = blocks[1:-1]
        has_compression = any(
            b["story_role"] == "blowout_compression" for b in middle
        )
        assert has_compression or len(middle) <= 1, (
            f"expected at least one compression block or a fully-merged "
            f"middle. Got {[b['story_role'] for b in blocks]}"
        )

    def test_period_range_uses_inning_label(self) -> None:
        result = _run(_mlb_blowout_moments(), "MLB", archetype="blowout")
        for block in result["blocks"]:
            assert "Inning" in block["period_range"]

    def test_compression_blocks_are_low_leverage(self) -> None:
        """Only ``blowout_compression`` middles must be low-leverage — the
        ``first_separation`` block legitimately earns medium because it's
        the beat that opened the gap."""
        result = _run(_mlb_blowout_moments(), "MLB", archetype="blowout")
        blocks = result["blocks"]
        for block in blocks:
            if block["story_role"] == "blowout_compression":
                assert block["leverage"] == "low", (
                    f"compression block {block['block_index']} has "
                    f"leverage={block['leverage']!r}; expected low"
                )


# ---------------------------------------------------------------------------
# MLB CLOSE GAME — 4-3 walk-off
# ---------------------------------------------------------------------------
# Shape: leadoff HR opens scoring, exchanges through the middle, late lead
# change, walk-off in the 9th.


def _mlb_close_moments() -> list[dict[str, Any]]:
    """A 4-3 walk-off with multiple lead-change beats. Plenty of moments so
    the segmenter has candidate boundaries — a too-thin fixture would
    collapse to ≤2 blocks regardless of game shape."""
    return [
        # Inning 1 — leadoff HR → 1-0 home (plus 2 non-scoring plays for density)
        _moment(1, 1, 0, 0, 1, 0),
        _moment(2, 1, 1, 0, 1, 0),
        _moment(3, 2, 1, 0, 1, 0),
        # Inning 3 — visitors tie 1-1
        _moment(4, 3, 1, 0, 1, 1),
        _moment(5, 3, 1, 1, 1, 1),
        # Inning 4 — visitors take lead 1-2
        _moment(6, 4, 1, 1, 1, 2),
        _moment(7, 4, 1, 2, 1, 2),
        _moment(8, 5, 1, 2, 1, 2),
        # Inning 6 — home re-takes lead 2-2 → 3-2
        _moment(9, 6, 1, 2, 2, 2),
        _moment(10, 6, 2, 2, 3, 2),
        _moment(11, 7, 3, 2, 3, 2),
        # Inning 8 — visitors tie 3-3
        _moment(12, 8, 3, 2, 3, 3),
        _moment(13, 8, 3, 3, 3, 3),
        # Inning 9 — walk-off → 4-3
        _moment(14, 9, 3, 3, 4, 3),
        _moment(15, 9, 4, 3, 4, 3),
    ]


class TestMLBCloseGolden:
    def test_shape(self) -> None:
        result = _run(_mlb_close_moments(), "MLB", archetype="back_and_forth")
        blocks = result["blocks"]
        _block_assertions(blocks)
        assert result["is_blowout"] is False
        # 4-7 blocks for competitive games per the brief; allow 3 minimum.
        assert 3 <= len(blocks) <= 7

    def test_lead_change_block_high_leverage(self) -> None:
        result = _run(_mlb_close_moments(), "MLB", archetype="back_and_forth")
        # At least one non-opening, non-closeout block should be high leverage
        # (multiple lead changes inside the game).
        middle = [b for b in result["blocks"] if b["story_role"] not in ("opening", "closeout")]
        if middle:
            assert any(b["leverage"] == "high" for b in middle), (
                "expected at least one high-leverage middle block in a "
                "lead-change-heavy MLB game"
            )

    def test_no_blowout_compression(self) -> None:
        result = _run(_mlb_close_moments(), "MLB", archetype="back_and_forth")
        for block in result["blocks"]:
            assert block["story_role"] != "blowout_compression"


# ---------------------------------------------------------------------------
# NBA CLOSE GAME — Timberwolves 104, Spurs 102 (the screenshot fixture)
# ---------------------------------------------------------------------------
# Shape: Q1 close, Q2 ends 50-48, Q3 lead changes, Q4 the Wolves flip a deficit
# into a 104-102 win.


def _nba_close_moments() -> list[dict[str, Any]]:
    return [
        # Q1 — back-and-forth, ends 25-22 home
        _moment(1, 1, 0, 0, 14, 12),
        _moment(2, 1, 14, 12, 25, 22),
        # Q2 — visitor extends, then home recovers; 50-48 home at half
        _moment(3, 2, 25, 22, 38, 38),
        _moment(4, 2, 38, 38, 50, 48),
        # Q3 — multiple lead changes, ends 75-73 home
        _moment(5, 3, 50, 48, 60, 58),
        _moment(6, 3, 60, 58, 65, 67),  # lead change visitor
        _moment(7, 3, 65, 67, 75, 73),  # lead change back home
        # Q4 — close clutch sequence
        _moment(
            8, 4, 75, 73, 88, 85,
            start_clock="12:00", end_clock="6:39",
        ),
        _moment(
            9, 4, 88, 85, 95, 95,
            start_clock="6:39", end_clock="3:30",
        ),
        _moment(
            10, 4, 95, 95, 104, 102,
            start_clock="3:30", end_clock="0:00",
        ),
    ]


class TestNBACloseGolden:
    def test_shape(self) -> None:
        result = _run(_nba_close_moments(), "NBA", archetype="back_and_forth")
        blocks = result["blocks"]
        _block_assertions(blocks)
        assert result["is_blowout"] is False
        assert 4 <= len(blocks) <= 7

    def test_late_blocks_high_leverage(self) -> None:
        """At least one Q4 block in a 104-102 game should be high-leverage."""
        result = _run(_nba_close_moments(), "NBA", archetype="back_and_forth")
        late_blocks = [b for b in result["blocks"] if b["period_end"] == 4]
        assert late_blocks, "expected at least one Q4 block"
        assert any(b["leverage"] == "high" for b in late_blocks), (
            f"no high-leverage Q4 blocks; saw "
            f"{[(b['story_role'], b['leverage']) for b in late_blocks]}"
        )

    def test_period_range_uses_quarter_prefix(self) -> None:
        result = _run(_nba_close_moments(), "NBA", archetype="back_and_forth")
        # First block's range must reference Q-prefixed periods.
        assert result["blocks"][0]["period_range"].startswith("Q")


# ---------------------------------------------------------------------------
# NBA BLOWOUT — Lakers 130, Celtics 95
# ---------------------------------------------------------------------------
# Shape: competitive opening through Q1, decisive Q2-Q3 pull-away, garbage
# time Q4. Blowout compression should collapse middles.


def _nba_blowout_moments() -> list[dict[str, Any]]:
    return [
        # Q1 — close opening 25-22
        _moment(1, 1, 0, 0, 14, 12),
        _moment(2, 1, 14, 12, 25, 22),
        # Q2 — Lakers pull away; ends 65-40 (decisive separation)
        _moment(3, 2, 25, 22, 45, 30),
        _moment(4, 2, 45, 30, 65, 40),
        # Q3 — Lakers extend further; ends 100-65
        _moment(5, 3, 65, 40, 85, 55),
        _moment(6, 3, 85, 55, 100, 65),
        # Q4 — garbage time padding
        _moment(7, 4, 100, 65, 120, 80),
        _moment(8, 4, 120, 80, 130, 95),
    ]


class TestNBABlowoutGolden:
    def test_shape(self) -> None:
        result = _run(_nba_blowout_moments(), "NBA", archetype="blowout")
        blocks = result["blocks"]
        _block_assertions(blocks)
        assert result["is_blowout"] is True
        assert 2 <= len(blocks) <= 4

    def test_no_high_leverage_in_middle(self) -> None:
        result = _run(_nba_blowout_moments(), "NBA", archetype="blowout")
        for block in result["blocks"][1:-1]:
            assert block["leverage"] != "high", (
                f"middle block {block['block_index']} is high-leverage "
                f"in a blowout; brief says do not pretend it was dramatic"
            )


# ---------------------------------------------------------------------------
# NHL CLOSE GAME — 3-2 OT
# ---------------------------------------------------------------------------
# Shape: tied through regulation, OT goal decides. Sport-specific period
# label OT and high leverage in OT block.


def _nhl_close_moments() -> list[dict[str, Any]]:
    return [
        # P1 — home opens 1-0
        _moment(1, 1, 0, 0, 1, 0),
        # P2 — visitor ties 1-1, then home goes 2-1
        _moment(2, 2, 1, 0, 1, 1),
        _moment(3, 2, 1, 1, 2, 1),
        # P3 — visitor ties 2-2 with under 5 min
        _moment(4, 3, 2, 1, 2, 2, start_clock="04:23", end_clock="00:00"),
        # OT — home wins 3-2
        _moment(5, 4, 2, 2, 3, 2),
    ]


class TestNHLCloseGolden:
    def test_shape(self) -> None:
        result = _run(_nhl_close_moments(), "NHL", archetype="back_and_forth")
        blocks = result["blocks"]
        _block_assertions(blocks)
        assert result["is_blowout"] is False

    def test_ot_block_uses_ot_label(self) -> None:
        result = _run(_nhl_close_moments(), "NHL", archetype="back_and_forth")
        ot_blocks = [b for b in result["blocks"] if b["period_end"] >= 4]
        if ot_blocks:
            assert any("OT" in b["period_range"] for b in ot_blocks), (
                f"OT block period_range should reference OT; saw "
                f"{[b['period_range'] for b in ot_blocks]}"
            )


# ---------------------------------------------------------------------------
# NHL BLOWOUT — 6-1
# ---------------------------------------------------------------------------
# Shape: 2 goals in P1 to open separation, pile-on through P2/P3, blowout
# compression on the middle.


def _nhl_blowout_moments() -> list[dict[str, Any]]:
    return [
        # P1 — home opens 2-0
        _moment(1, 1, 0, 0, 1, 0),
        _moment(2, 1, 1, 0, 2, 0),
        # P2 — pile on, 4-1 by end of period
        _moment(3, 2, 2, 0, 3, 0),
        _moment(4, 2, 3, 0, 3, 1),
        _moment(5, 2, 3, 1, 4, 1),
        # P3 — empty-net cosmetics, finish 6-1
        _moment(6, 3, 4, 1, 5, 1),
        _moment(7, 3, 5, 1, 6, 1),
    ]


class TestNHLBlowoutGolden:
    def test_shape(self) -> None:
        result = _run(_nhl_blowout_moments(), "NHL", archetype="blowout")
        blocks = result["blocks"]
        _block_assertions(blocks)
        assert result["is_blowout"] is True
        assert 2 <= len(blocks) <= 4

    def test_period_range_uses_period_prefix(self) -> None:
        result = _run(_nhl_blowout_moments(), "NHL", archetype="blowout")
        # NHL regulation blocks use P-prefix.
        for block in result["blocks"]:
            if block["period_end"] <= 3:
                assert block["period_range"].startswith("P"), (
                    f"block {block['block_index']} period_range "
                    f"{block['period_range']!r} should start with P"
                )


# ---------------------------------------------------------------------------
# Cross-cutting: blowout middles must always merge if classifier marks them.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fixture_name,sport,archetype",
    [
        ("mlb_blowout", "MLB", "blowout"),
        ("nba_blowout", "NBA", "blowout"),
        ("nhl_blowout", "NHL", "blowout"),
    ],
)
def test_blowout_compression_runs_are_merged(
    fixture_name: str, sport: str, archetype: str
) -> None:
    """No two adjacent blowout_compression blocks in any blowout output."""
    fixture_factory = {
        "mlb_blowout": _mlb_blowout_moments,
        "nba_blowout": _nba_blowout_moments,
        "nhl_blowout": _nhl_blowout_moments,
    }[fixture_name]

    result = _run(fixture_factory(), sport, archetype=archetype)
    roles = [b["story_role"] for b in result["blocks"]]
    for i in range(len(roles) - 1):
        assert not (
            roles[i] == "blowout_compression"
            and roles[i + 1] == "blowout_compression"
        ), f"adjacent compression blocks not merged in {fixture_name}: {roles}"
