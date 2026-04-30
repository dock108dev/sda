"""Unit tests for sport-specific narrative fallback templates (ISSUE-046).

Coverage:
- TemplateEngine.render() for NFL, NBA, MLB, NHL
- Output structure: 4 blocks, correct roles, score continuity
- validate_blocks_* pipeline constraints (block count, word counts,
  role ordering, mini_box population, moment coverage)
- Coverage constraints: final score present, winning team present, OT term (when applicable)
- Edge cases: zero scores, overtime, tied game (OT)
"""

from __future__ import annotations

import re
import sys
import types

import pytest


def _clear_sports_scraper_stubs() -> None:
    """Remove stub entries for sports_scraper installed by other test modules.

    test_flow_trigger_lock.py registers fake types.ModuleType objects for
    sports_scraper.* to avoid importing heavy dependencies. Those stubs have no
    __file__ attribute (real packages always do). Remove them so the real
    package can be imported below.
    """
    to_remove = [
        key for key, mod in list(sys.modules.items())
        if (key == "sports_scraper" or key.startswith("sports_scraper."))
        and isinstance(mod, types.ModuleType)
        and not getattr(mod, "__file__", None)
    ]
    for key in to_remove:
        del sys.modules[key]


_clear_sports_scraper_stubs()

from sports_scraper.pipeline.templates import (  # noqa: E402
    GameMiniBox,
    TemplateEngine,
    block_scores,
    distribute_moments,
)

# ── Constants (mirrored from validate_blocks.py) ─────────────────────────────

MIN_BLOCKS = 3
MAX_BLOCKS = 7
MIN_WORDS = 30
MAX_WORDS = 120
MAX_TOTAL_WORDS = 600
OT_TERMS = frozenset(["overtime", " ot ", "ot.", "ot,", "extra time", "sudden death"])

# ── Helpers ───────────────────────────────────────────────────────────────────


def _count_words(text: str) -> int:
    return len(text.split())


def _count_sentences(text: str) -> int:
    return len([s for s in re.split(r"[.!?]+", text) if s.strip()])


def _full_text(blocks: list[dict]) -> str:
    return " ".join(b.get("narrative", "") for b in blocks).lower()


def _score_in_text(text: str, home: int, away: int) -> bool:
    sep = r"\s*[-\u2013\u2014]\s*|\s+to\s+"
    for a, b in [(home, away), (away, home)]:
        if re.search(rf"\b{a}(?:{sep}){b}\b", text):
            return True
    return False


def _team_in_text(text: str, team: str) -> bool:
    parts = team.split()
    checks = [team.lower()]
    if len(parts) > 1:
        checks.append(parts[-1].lower())
    return any(c in text for c in checks)


def _ot_in_text(text: str) -> bool:
    padded = f" {text} "
    return any(t in padded for t in OT_TERMS)


# ── Shared structural assertion ───────────────────────────────────────────────


def assert_blocks_valid(
    blocks: list[dict],
    home_team: str,
    away_team: str,
    home_score: int,
    away_score: int,
    has_overtime: bool = False,
    total_moments: int = 0,
) -> None:
    """Assert all validate_blocks.py structural constraints are satisfied."""
    # Block count
    assert MIN_BLOCKS <= len(blocks) <= MAX_BLOCKS, f"block count {len(blocks)}"

    # Roles
    roles = [b["role"] for b in blocks]
    assert roles[0] == "SETUP", f"first role must be SETUP, got {roles[0]}"
    assert roles[-1] == "RESOLUTION", f"last role must be RESOLUTION, got {roles[-1]}"
    from collections import Counter
    for role, cnt in Counter(roles).items():
        assert cnt <= 2, f"role {role} appears {cnt} times (max 2)"

    # Score continuity
    for i in range(len(blocks) - 1):
        after = blocks[i]["score_after"]
        before = blocks[i + 1]["score_before"]
        assert after == before, (
            f"score discontinuity between blocks {i} and {i + 1}: {after} → {before}"
        )

    # First block score_before == [0, 0]
    assert blocks[0]["score_before"] == [0, 0], "first block must start at 0-0"

    # Last block score_after == [home_score, away_score]
    assert blocks[-1]["score_after"] == [home_score, away_score], (
        f"last block score_after {blocks[-1]['score_after']} != [{home_score}, {away_score}]"
    )

    # Narrative word counts and sentences
    total_words = 0
    for b in blocks:
        narrative = b.get("narrative", "")
        assert narrative, f"block {b['block_index']} missing narrative"
        wc = _count_words(narrative)
        assert wc >= MIN_WORDS, f"block {b['block_index']} too short: {wc} words"
        assert wc <= MAX_WORDS, f"block {b['block_index']} too long: {wc} words"
        sc = _count_sentences(narrative)
        assert 1 <= sc <= 5, f"block {b['block_index']} has {sc} sentences"
        total_words += wc
    assert total_words <= MAX_TOTAL_WORDS, f"total words {total_words} > {MAX_TOTAL_WORDS}"

    # mini_box population
    for b in blocks:
        mb = b.get("mini_box")
        assert mb and isinstance(mb, dict), f"block {b['block_index']} missing mini_box"
        cum = mb.get("cumulative", {})
        assert cum.get("home"), f"block {b['block_index']} mini_box missing cumulative.home"
        assert cum.get("away"), f"block {b['block_index']} mini_box missing cumulative.away"
        assert mb.get("delta") and isinstance(mb["delta"], dict), (
            f"block {b['block_index']} mini_box missing delta"
        )

    # Moment coverage (all range(total_moments) covered exactly once)
    covered: set[int] = set()
    for b in blocks:
        for idx in b.get("moment_indices", []):
            assert idx not in covered, f"moment {idx} appears in multiple blocks"
            covered.add(idx)
    assert covered == set(range(total_moments)), (
        f"moment coverage mismatch: covered={sorted(covered)}, expected={list(range(total_moments))}"
    )

    # Narrative coverage (final score, winning team, OT if applicable)
    full = _full_text(blocks)
    if not (home_score == 0 and away_score == 0):
        assert _score_in_text(full, home_score, away_score), (
            f"final score {home_score}-{away_score} not found in narrative"
        )
        if home_score != away_score:
            winner = home_team if home_score > away_score else away_team
            assert _team_in_text(full, winner), (
                f"winning team '{winner}' not mentioned in narrative"
            )
    if has_overtime:
        assert _ot_in_text(full), "OT game but no overtime term in narrative"


# ── NFL tests ─────────────────────────────────────────────────────────────────


class TestNFLTemplate:
    def _render(self, **kwargs) -> list[dict]:
        mb = GameMiniBox(
            home_team=kwargs.get("home_team", "Buffalo Bills"),
            away_team=kwargs.get("away_team", "Miami Dolphins"),
            home_score=kwargs.get("home_score", 27),
            away_score=kwargs.get("away_score", 20),
            sport="NFL",
            has_overtime=kwargs.get("has_overtime", False),
            total_moments=kwargs.get("total_moments", 0),
        )
        return TemplateEngine.render("NFL", mb)

    def test_basic_output_structure(self):
        blocks = self._render()
        assert len(blocks) == 4
        assert blocks[0]["role"] == "SETUP"
        assert blocks[-1]["role"] == "RESOLUTION"

    def test_passes_validate_blocks_constraints(self):
        blocks = self._render(total_moments=12)
        assert_blocks_valid(
            blocks,
            home_team="Buffalo Bills",
            away_team="Miami Dolphins",
            home_score=27,
            away_score=20,
            total_moments=12,
        )

    def test_overtime_game(self):
        blocks = self._render(home_score=23, away_score=20, has_overtime=True)
        assert_blocks_valid(
            blocks,
            home_team="Buffalo Bills",
            away_team="Miami Dolphins",
            home_score=23,
            away_score=20,
            has_overtime=True,
        )

    def test_away_team_wins(self):
        blocks = self._render(home_score=14, away_score=28)
        assert_blocks_valid(
            blocks,
            home_team="Buffalo Bills",
            away_team="Miami Dolphins",
            home_score=14,
            away_score=28,
        )

    def test_no_moment_indices_when_zero_moments(self):
        blocks = self._render(total_moments=0)
        for b in blocks:
            assert b["moment_indices"] == []

    def test_moment_indices_coverage(self):
        blocks = self._render(total_moments=17)
        assert_blocks_valid(
            blocks,
            home_team="Buffalo Bills",
            away_team="Miami Dolphins",
            home_score=27,
            away_score=20,
            total_moments=17,
        )

    def test_low_scoring_game(self):
        blocks = self._render(home_score=3, away_score=6)
        assert_blocks_valid(
            blocks,
            home_team="Buffalo Bills",
            away_team="Miami Dolphins",
            home_score=3,
            away_score=6,
        )


# ── NBA tests ─────────────────────────────────────────────────────────────────


class TestNBATemplate:
    def _render(self, **kwargs) -> list[dict]:
        mb = GameMiniBox(
            home_team=kwargs.get("home_team", "Boston Celtics"),
            away_team=kwargs.get("away_team", "Golden State Warriors"),
            home_score=kwargs.get("home_score", 115),
            away_score=kwargs.get("away_score", 108),
            sport="NBA",
            has_overtime=kwargs.get("has_overtime", False),
            total_moments=kwargs.get("total_moments", 0),
        )
        return TemplateEngine.render("NBA", mb)

    def test_basic_output_structure(self):
        blocks = self._render()
        assert len(blocks) == 4
        assert blocks[0]["role"] == "SETUP"
        assert blocks[-1]["role"] == "RESOLUTION"

    def test_passes_validate_blocks_constraints(self):
        blocks = self._render(total_moments=20)
        assert_blocks_valid(
            blocks,
            home_team="Boston Celtics",
            away_team="Golden State Warriors",
            home_score=115,
            away_score=108,
            total_moments=20,
        )

    def test_overtime_game(self):
        blocks = self._render(home_score=121, away_score=118, has_overtime=True)
        assert_blocks_valid(
            blocks,
            home_team="Boston Celtics",
            away_team="Golden State Warriors",
            home_score=121,
            away_score=118,
            has_overtime=True,
        )

    def test_blowout_game(self):
        blocks = self._render(home_score=140, away_score=100)
        assert_blocks_valid(
            blocks,
            home_team="Boston Celtics",
            away_team="Golden State Warriors",
            home_score=140,
            away_score=100,
        )

    def test_away_team_wins(self):
        blocks = self._render(home_score=105, away_score=112)
        assert_blocks_valid(
            blocks,
            home_team="Boston Celtics",
            away_team="Golden State Warriors",
            home_score=105,
            away_score=112,
        )


# ── MLB tests ─────────────────────────────────────────────────────────────────


class TestMLBTemplate:
    def _render(self, **kwargs) -> list[dict]:
        mb = GameMiniBox(
            home_team=kwargs.get("home_team", "New York Yankees"),
            away_team=kwargs.get("away_team", "Los Angeles Dodgers"),
            home_score=kwargs.get("home_score", 5),
            away_score=kwargs.get("away_score", 3),
            sport="MLB",
            has_overtime=kwargs.get("has_overtime", False),
            total_moments=kwargs.get("total_moments", 0),
        )
        return TemplateEngine.render("MLB", mb)

    def test_basic_output_structure(self):
        blocks = self._render()
        assert len(blocks) == 4
        assert blocks[0]["role"] == "SETUP"
        assert blocks[-1]["role"] == "RESOLUTION"

    def test_passes_validate_blocks_constraints(self):
        blocks = self._render(total_moments=9)
        assert_blocks_valid(
            blocks,
            home_team="New York Yankees",
            away_team="Los Angeles Dodgers",
            home_score=5,
            away_score=3,
            total_moments=9,
        )

    def test_period_mapping_uses_innings(self):
        blocks = self._render()
        assert blocks[0]["period_start"] == 1
        assert blocks[0]["period_end"] == 3
        assert blocks[1]["period_start"] == 4
        assert blocks[1]["period_end"] == 6
        assert blocks[2]["period_start"] == 7

    def test_extra_innings_game(self):
        blocks = self._render(home_score=4, away_score=3, has_overtime=True)
        assert_blocks_valid(
            blocks,
            home_team="New York Yankees",
            away_team="Los Angeles Dodgers",
            home_score=4,
            away_score=3,
            has_overtime=True,
        )

    def test_high_scoring_game(self):
        blocks = self._render(home_score=12, away_score=9)
        assert_blocks_valid(
            blocks,
            home_team="New York Yankees",
            away_team="Los Angeles Dodgers",
            home_score=12,
            away_score=9,
        )


# ── NHL tests ─────────────────────────────────────────────────────────────────


class TestNHLTemplate:
    def _render(self, **kwargs) -> list[dict]:
        mb = GameMiniBox(
            home_team=kwargs.get("home_team", "Toronto Maple Leafs"),
            away_team=kwargs.get("away_team", "Montreal Canadiens"),
            home_score=kwargs.get("home_score", 4),
            away_score=kwargs.get("away_score", 2),
            sport="NHL",
            has_overtime=kwargs.get("has_overtime", False),
            total_moments=kwargs.get("total_moments", 0),
        )
        return TemplateEngine.render("NHL", mb)

    def test_basic_output_structure(self):
        blocks = self._render()
        assert len(blocks) == 4
        assert blocks[0]["role"] == "SETUP"
        assert blocks[-1]["role"] == "RESOLUTION"

    def test_passes_validate_blocks_constraints(self):
        blocks = self._render(total_moments=8)
        assert_blocks_valid(
            blocks,
            home_team="Toronto Maple Leafs",
            away_team="Montreal Canadiens",
            home_score=4,
            away_score=2,
            total_moments=8,
        )

    def test_overtime_game(self):
        blocks = self._render(home_score=3, away_score=2, has_overtime=True)
        assert_blocks_valid(
            blocks,
            home_team="Toronto Maple Leafs",
            away_team="Montreal Canadiens",
            home_score=3,
            away_score=2,
            has_overtime=True,
        )

    def test_1_0_game(self):
        blocks = self._render(home_score=1, away_score=0)
        assert_blocks_valid(
            blocks,
            home_team="Toronto Maple Leafs",
            away_team="Montreal Canadiens",
            home_score=1,
            away_score=0,
        )

    def test_away_team_wins(self):
        blocks = self._render(home_score=1, away_score=4)
        assert_blocks_valid(
            blocks,
            home_team="Toronto Maple Leafs",
            away_team="Montreal Canadiens",
            home_score=1,
            away_score=4,
        )


# ── TemplateEngine routing tests ─────────────────────────────────────────────


class TestTemplateEngineRouting:
    def test_case_insensitive_sport(self):
        mb = GameMiniBox("Lakers", "Celtics", 110, 105, "nba")
        blocks_lower = TemplateEngine.render("nba", mb)
        blocks_upper = TemplateEngine.render("NBA", mb)
        assert len(blocks_lower) == len(blocks_upper) == 4

    def test_unknown_sport_falls_back_to_nba_template(self):
        mb = GameMiniBox("Home", "Away", 10, 8, "UNKNOWN")
        blocks = TemplateEngine.render("UNKNOWN", mb)
        assert len(blocks) == 4
        assert blocks[0]["role"] == "SETUP"
        assert blocks[-1]["role"] == "RESOLUTION"

    def test_no_llm_calls(self):
        """TemplateEngine.render() must not invoke any external APIs."""
        import sys
        # If anthropic is imported during render, this test catches it
        pre_modules = set(sys.modules.keys())
        mb = GameMiniBox("Bulls", "Heat", 100, 95, "NBA")
        TemplateEngine.render("NBA", mb)
        new_modules = set(sys.modules.keys()) - pre_modules
        llm_modules = {m for m in new_modules if "anthropic" in m or "openai" in m}
        assert not llm_modules, f"LLM modules imported during render: {llm_modules}"


# ── Shared helper tests ───────────────────────────────────────────────────────


class TestHelpers:
    def test_distribute_moments_zero(self):
        result = distribute_moments(0, 4)
        assert result == [[], [], [], []]

    def test_distribute_moments_even(self):
        result = distribute_moments(8, 4)
        assert result == [[0, 1], [2, 3], [4, 5], [6, 7]]

    def test_distribute_moments_uneven(self):
        result = distribute_moments(9, 4)
        flat = [x for chunk in result for x in chunk]
        assert sorted(flat) == list(range(9))
        assert len(result) == 4

    def test_block_scores_final_is_exact(self):
        scores = block_scores(21, 17)
        assert scores[-1] == (21, 17)

    def test_block_scores_monotone(self):
        scores = block_scores(110, 105)
        home_vals = [s[0] for s in scores]
        away_vals = [s[1] for s in scores]
        assert home_vals == sorted(home_vals)
        assert away_vals == sorted(away_vals)
