"""Standalone golden corpus test runner for ISSUE-048.

Validates the 52 fixture files (4 sports × 13 shapes) under tests/golden/
without requiring the full pipeline stack.

Run with:
    pytest tests/golden/ -v

Checks enforced
---------------
- ≥ 50 fixtures total across NFL, NBA, MLB, NHL.
- ≥ 10 fixtures per sport.
- ≥ 2 TEMPLATE (flow_source=TEMPLATE) fixtures per sport.
- Required edge-case shapes present per sport (blowout, overtime,
  incomplete_pbp, postponement, …).
- Blowout fixtures have a margin consistent with the sport.
- Every fixture carries quality_score_floor, flow_source,
  expected_flow_skeleton, and forbidden_phrases == 0.
- TEMPLATE fixtures always declare block_count_range == [4, 4].
- incomplete_pbp and postponement fixtures have null final_score.
- postponement fixtures have an empty plays list.
- Play indexes are monotonically increasing from 1.
- corpus_id matches the filename stem; sport matches the parent directory.
- No generic phrases from ISSUE-047 appear in any fixture text field.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from tests.golden.loader import VALID_ROLES, load_all_fixtures, load_fixture, load_sport_fixtures

GOLDEN_DIR = Path(__file__).parent
SPORTS = ["nfl", "nba", "mlb", "nhl"]
MIN_FIXTURES_PER_SPORT = 10
MIN_TEMPLATE_PER_SPORT = 2

REQUIRED_SHAPES = frozenset(
    {
        "standard_win",
        "blowout",
        "comeback",
        "overtime",
        "incomplete_pbp",
        "postponement",
    }
)

# Sport-specific blowout margin thresholds (the sport's scoring unit).
BLOWOUT_MARGINS: dict[str, int] = {
    "nfl": 30,  # points
    "nba": 30,  # points
    "mlb": 8,   # runs
    "nhl": 4,   # goals
}

# ---------------------------------------------------------------------------
# Generic phrases from ISSUE-047.
# Loaded from grader_rules/generic_phrases.toml when available; falls back to
# this hardcoded subset so the test suite is fully standalone.
# ---------------------------------------------------------------------------
_HARDCODED_PHRASES: list[str] = [
    "gave it their all",
    "showed a lot of heart",
    "left it all on the floor",
    "left it all on the field",
    "left it all on the ice",
    "gave 110 percent",
    "played their hearts out",
    "gutsy performance",
    "dug deep",
    "answered the call",
    "rose to the occasion",
    "made their mark",
    "made a statement tonight",
    "the rest is history",
    "a hard-fought battle",
    "a closely contested",
    "when it mattered most",
    "proved too much",
    "stood tall",
    "in what was a",
    "none other than",
    "throughout the contest",
    "from start to finish",
    "stepped up to the plate",
    "it was a testament to",
    "was a testament to",
    "showcased their talent",
    "delivered a masterclass",
    "put on a show",
    "put on a display",
    "a masterful performance",
    "a dominant display",
    "put up a fight",
    "stole the show",
    "sparked by the energy",
]

_TOML_PATH = (
    GOLDEN_DIR.parents[1]
    / "scraper"
    / "sports_scraper"
    / "pipeline"
    / "grader_rules"
    / "generic_phrases.toml"
)


def _load_forbidden_phrases() -> list[str]:
    try:
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef]

        if not _TOML_PATH.is_file():
            return _HARDCODED_PHRASES

        with open(_TOML_PATH, "rb") as fh:
            data = tomllib.load(fh)

        phrases: list[str] = []
        for section in ("effort_cliches", "outcome_cliches", "narrative_filler"):
            phrases.extend(data.get(section, {}).get("phrases", []))
        return phrases or _HARDCODED_PHRASES
    except Exception:  # noqa: BLE001
        return _HARDCODED_PHRASES


FORBIDDEN_PHRASES: list[str] = _load_forbidden_phrases()

# ---------------------------------------------------------------------------
# Fixture discovery
# ---------------------------------------------------------------------------


def _all_fixture_paths() -> list[Path]:
    paths: list[Path] = []
    for sport in SPORTS:
        sport_dir = GOLDEN_DIR / sport
        if sport_dir.is_dir():
            paths.extend(sorted(sport_dir.glob("*.json")))
    return paths


def _fixture_id(path: Path) -> str:
    return path.stem


def load_fixture(path: Path) -> dict[str, Any]:
    with open(path) as fh:
        return json.load(fh)


def all_text(data: Any) -> str:
    """Recursively join all string values, lowercased, for phrase scanning."""
    parts: list[str] = []

    def walk(obj: Any) -> None:
        if isinstance(obj, str):
            parts.append(obj.lower())
        elif isinstance(obj, dict):
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(data)
    return " ".join(parts)


_ALL_FIXTURES = _all_fixture_paths()

# ---------------------------------------------------------------------------
# Required fixture-level keys and skeleton keys
# ---------------------------------------------------------------------------
REQUIRED_FIXTURE_KEYS = frozenset(
    {
        "corpus_id",
        "sport",
        "game_shape",
        "flow_source",
        "quality_score_floor",
        "forbidden_phrases",
        "source_game_key",
        "game_date",
        "home_team",
        "away_team",
        "expected_blocks",
        "expected_block_type_counts",
        "expected_flow_skeleton",
        "pbp",
    }
)

REQUIRED_SKELETON_KEYS = frozenset(
    {"block_count_range", "roles_required", "has_overtime"}
)


# ===========================================================================
# Coverage tests (non-parametrized — one failure reveals a gap in the corpus)
# ===========================================================================


class TestSportCoverage:
    def test_total_fixture_count_at_least_50(self) -> None:
        assert len(_ALL_FIXTURES) >= 50, (
            f"Expected ≥ 50 total fixtures, found {len(_ALL_FIXTURES)}"
        )

    @pytest.mark.parametrize("sport", SPORTS)
    def test_minimum_10_fixtures_per_sport(self, sport: str) -> None:
        sport_files = list((GOLDEN_DIR / sport).glob("*.json"))
        assert len(sport_files) >= MIN_FIXTURES_PER_SPORT, (
            f"{sport.upper()}: expected ≥ {MIN_FIXTURES_PER_SPORT} fixtures, "
            f"found {len(sport_files)}"
        )

    @pytest.mark.parametrize("sport", SPORTS)
    def test_required_shapes_present(self, sport: str) -> None:
        shapes = {
            p.stem[len(sport) + 1:]  # strip "{sport}_" prefix
            for p in (GOLDEN_DIR / sport).glob("*.json")
        }
        missing = REQUIRED_SHAPES - shapes
        assert not missing, (
            f"{sport.upper()} missing required edge-case shapes: {missing}"
        )

    @pytest.mark.parametrize("sport", SPORTS)
    def test_minimum_2_template_fixtures_per_sport(self, sport: str) -> None:
        count = sum(
            1
            for p in (GOLDEN_DIR / sport).glob("*.json")
            if load_fixture(p).get("flow_source") == "TEMPLATE"
        )
        assert count >= MIN_TEMPLATE_PER_SPORT, (
            f"{sport.upper()}: expected ≥ {MIN_TEMPLATE_PER_SPORT} TEMPLATE fixtures, "
            f"found {count}"
        )

    @pytest.mark.parametrize("sport", SPORTS)
    def test_blowout_margin_is_significant(self, sport: str) -> None:
        path = GOLDEN_DIR / sport / f"{sport}_blowout.json"
        if not path.exists():
            pytest.skip(f"No blowout fixture for {sport}")
        data = load_fixture(path)
        score = data.get("final_score")
        if score is None:
            pytest.fail(f"{sport}_blowout has null final_score")
        margin = abs(score["home"] - score["away"])
        threshold = BLOWOUT_MARGINS[sport]
        assert margin >= threshold, (
            f"{sport}_blowout margin={margin} must be ≥ {threshold}"
        )

    @pytest.mark.parametrize("sport", SPORTS)
    def test_overtime_fixture_marks_has_overtime(self, sport: str) -> None:
        path = GOLDEN_DIR / sport / f"{sport}_overtime.json"
        if not path.exists():
            pytest.skip(f"No overtime fixture for {sport}")
        data = load_fixture(path)
        assert data["expected_flow_skeleton"]["has_overtime"] is True, (
            f"{sport}_overtime: expected_flow_skeleton.has_overtime must be true"
        )

    @pytest.mark.parametrize("sport", SPORTS)
    def test_postponement_fixture_present(self, sport: str) -> None:
        path = GOLDEN_DIR / sport / f"{sport}_postponement.json"
        assert path.exists(), (
            f"Missing postponement fixture for {sport.upper()}: {path}"
        )


# ===========================================================================
# Fixture schema tests (parametrized over every fixture)
# ===========================================================================


class TestFixtureSchema:
    @pytest.mark.parametrize("fixture_path", _ALL_FIXTURES, ids=_fixture_id)
    def test_required_top_level_fields(self, fixture_path: Path) -> None:
        data = load_fixture(fixture_path)
        missing = REQUIRED_FIXTURE_KEYS - set(data.keys())
        assert not missing, f"{fixture_path.name}: missing fields {missing}"

    @pytest.mark.parametrize("fixture_path", _ALL_FIXTURES, ids=_fixture_id)
    def test_flow_source_valid_enum(self, fixture_path: Path) -> None:
        data = load_fixture(fixture_path)
        assert data.get("flow_source") in ("LLM", "TEMPLATE"), (
            f"{fixture_path.name}: flow_source must be 'LLM' or 'TEMPLATE', "
            f"got {data.get('flow_source')!r}"
        )

    @pytest.mark.parametrize("fixture_path", _ALL_FIXTURES, ids=_fixture_id)
    def test_quality_score_floor_is_numeric_in_range(self, fixture_path: Path) -> None:
        data = load_fixture(fixture_path)
        floor = data.get("quality_score_floor")
        assert isinstance(floor, (int, float)), (
            f"{fixture_path.name}: quality_score_floor must be numeric, got {floor!r}"
        )
        assert 0 <= floor <= 100, (
            f"{fixture_path.name}: quality_score_floor={floor} out of [0, 100]"
        )

    @pytest.mark.parametrize("fixture_path", _ALL_FIXTURES, ids=_fixture_id)
    def test_forbidden_phrases_field_equals_zero(self, fixture_path: Path) -> None:
        data = load_fixture(fixture_path)
        assert data.get("forbidden_phrases") == 0, (
            f"{fixture_path.name}: forbidden_phrases must be 0 "
            f"(any phrase found by the runner fails this fixture)"
        )

    @pytest.mark.parametrize("fixture_path", _ALL_FIXTURES, ids=_fixture_id)
    def test_expected_flow_skeleton_structure(self, fixture_path: Path) -> None:
        data = load_fixture(fixture_path)
        skeleton = data.get("expected_flow_skeleton", {})
        missing = REQUIRED_SKELETON_KEYS - set(skeleton.keys())
        assert not missing, (
            f"{fixture_path.name}: expected_flow_skeleton missing keys: {missing}"
        )
        bcr = skeleton.get("block_count_range", [])
        assert (
            isinstance(bcr, list)
            and len(bcr) == 2
            and all(isinstance(x, int) for x in bcr)
            and bcr[0] <= bcr[1]
        ), f"{fixture_path.name}: block_count_range must be [min, max] int pair"
        assert isinstance(skeleton.get("has_overtime"), bool), (
            f"{fixture_path.name}: has_overtime must be a boolean"
        )

    @pytest.mark.parametrize("fixture_path", _ALL_FIXTURES, ids=_fixture_id)
    def test_template_fixture_block_count_range_is_4_4(
        self, fixture_path: Path
    ) -> None:
        data = load_fixture(fixture_path)
        if data.get("flow_source") != "TEMPLATE":
            pytest.skip("LLM fixture — block count range is flexible")
        bcr = data["expected_flow_skeleton"]["block_count_range"]
        assert bcr == [4, 4], (
            f"{fixture_path.name}: TEMPLATE fixture must have block_count_range=[4,4], "
            f"got {bcr}"
        )

    @pytest.mark.parametrize("fixture_path", _ALL_FIXTURES, ids=_fixture_id)
    def test_template_quality_floor_is_zero(self, fixture_path: Path) -> None:
        data = load_fixture(fixture_path)
        if data.get("flow_source") != "TEMPLATE":
            pytest.skip("LLM fixture — quality floor varies")
        assert data.get("quality_score_floor") == 0, (
            f"{fixture_path.name}: TEMPLATE fixture quality_score_floor must be 0"
        )

    @pytest.mark.parametrize("fixture_path", _ALL_FIXTURES, ids=_fixture_id)
    def test_incomplete_and_postponement_have_null_final_score(
        self, fixture_path: Path
    ) -> None:
        data = load_fixture(fixture_path)
        shape = data.get("game_shape", "")
        if shape in ("incomplete_pbp", "postponement"):
            assert data.get("final_score") is None, (
                f"{fixture_path.name}: {shape} fixture must have null final_score"
            )

    @pytest.mark.parametrize("fixture_path", _ALL_FIXTURES, ids=_fixture_id)
    def test_postponement_has_empty_plays(self, fixture_path: Path) -> None:
        data = load_fixture(fixture_path)
        if data.get("game_shape") != "postponement":
            pytest.skip("Not a postponement fixture")
        plays = data.get("pbp", {}).get("plays", None)
        assert plays == [], (
            f"{fixture_path.name}: postponement fixture must have empty plays list"
        )

    @pytest.mark.parametrize("fixture_path", _ALL_FIXTURES, ids=_fixture_id)
    def test_non_null_score_fixtures_have_home_away_keys(
        self, fixture_path: Path
    ) -> None:
        data = load_fixture(fixture_path)
        score = data.get("final_score")
        if score is None:
            pytest.skip("Null final_score fixture")
        assert "home" in score and "away" in score, (
            f"{fixture_path.name}: final_score must have 'home' and 'away' keys"
        )

    @pytest.mark.parametrize("fixture_path", _ALL_FIXTURES, ids=_fixture_id)
    def test_play_indexes_start_at_1_and_increase(
        self, fixture_path: Path
    ) -> None:
        data = load_fixture(fixture_path)
        plays = data.get("pbp", {}).get("plays", [])
        if not plays:
            pytest.skip("No plays in fixture")
        idxs = [p["play_index"] for p in plays]
        assert idxs[0] == 1, (
            f"{fixture_path.name}: first play_index must be 1, got {idxs[0]}"
        )
        for i in range(1, len(idxs)):
            assert idxs[i] > idxs[i - 1], (
                f"{fixture_path.name}: play_index not monotonically increasing "
                f"at position {i} ({idxs[i - 1]} → {idxs[i]})"
            )

    @pytest.mark.parametrize("fixture_path", _ALL_FIXTURES, ids=_fixture_id)
    def test_corpus_id_matches_filename(self, fixture_path: Path) -> None:
        data = load_fixture(fixture_path)
        assert data.get("corpus_id") == fixture_path.stem, (
            f"{fixture_path.name}: corpus_id={data.get('corpus_id')!r} "
            f"must match filename stem {fixture_path.stem!r}"
        )

    @pytest.mark.parametrize("fixture_path", _ALL_FIXTURES, ids=_fixture_id)
    def test_sport_matches_parent_directory(self, fixture_path: Path) -> None:
        data = load_fixture(fixture_path)
        expected = fixture_path.parent.name.upper()
        assert data.get("sport") == expected, (
            f"{fixture_path.name}: sport={data.get('sport')!r} "
            f"must match parent directory name {expected!r}"
        )

    @pytest.mark.parametrize("fixture_path", _ALL_FIXTURES, ids=_fixture_id)
    def test_plays_have_required_keys(self, fixture_path: Path) -> None:
        data = load_fixture(fixture_path)
        plays = data.get("pbp", {}).get("plays", [])
        required = {
            "play_index", "quarter", "game_clock", "play_type",
            "team_abbreviation", "player_name", "description",
            "home_score", "away_score",
        }
        for play in plays:
            missing = required - set(play.keys())
            assert not missing, (
                f"{fixture_path.name}: play {play.get('play_index')} "
                f"missing keys {missing}"
            )

    @pytest.mark.parametrize("fixture_path", _ALL_FIXTURES, ids=_fixture_id)
    def test_scores_are_non_negative_integers(self, fixture_path: Path) -> None:
        data = load_fixture(fixture_path)
        plays = data.get("pbp", {}).get("plays", [])
        for play in plays:
            for key in ("home_score", "away_score"):
                val = play.get(key)
                assert isinstance(val, int) and val >= 0, (
                    f"{fixture_path.name}: play {play.get('play_index')} "
                    f"{key}={val!r} must be a non-negative integer"
                )

    @pytest.mark.parametrize("fixture_path", _ALL_FIXTURES, ids=_fixture_id)
    def test_expected_blocks_is_valid_role_list(self, fixture_path: Path) -> None:
        data = load_fixture(fixture_path)
        blocks = data.get("expected_blocks")
        assert isinstance(blocks, list) and len(blocks) >= 1, (
            f"{fixture_path.name}: expected_blocks must be a non-empty list"
        )
        for role in blocks:
            assert role in VALID_ROLES, (
                f"{fixture_path.name}: expected_blocks contains unknown role {role!r}; "
                f"valid roles: {sorted(VALID_ROLES)}"
            )
        if len(blocks) >= 2:
            assert blocks[0] == "SETUP", (
                f"{fixture_path.name}: expected_blocks first role must be SETUP, got {blocks[0]!r}"
            )
            assert blocks[-1] == "RESOLUTION", (
                f"{fixture_path.name}: expected_blocks last role must be RESOLUTION, "
                f"got {blocks[-1]!r}"
            )

    @pytest.mark.parametrize("fixture_path", _ALL_FIXTURES, ids=_fixture_id)
    def test_expected_block_type_counts_matches_expected_blocks(
        self, fixture_path: Path
    ) -> None:
        data = load_fixture(fixture_path)
        blocks: list[str] = data.get("expected_blocks", [])
        counts: dict[str, int] = data.get("expected_block_type_counts", {})
        # Recompute expected counts from the role list
        computed: dict[str, int] = {}
        for role in blocks:
            computed[role] = computed.get(role, 0) + 1
        assert counts == computed, (
            f"{fixture_path.name}: expected_block_type_counts {counts} "
            f"does not match counts derived from expected_blocks {computed}"
        )


class TestLoader:
    """Smoke-tests for the loader utility (ISSUE-003 acceptance criterion)."""

    def test_load_all_fixtures_returns_all(self) -> None:
        fixtures = load_all_fixtures()
        assert len(fixtures) >= 50, (
            f"load_all_fixtures() returned {len(fixtures)} fixtures; expected ≥ 50"
        )

    @pytest.mark.parametrize("sport", [s.upper() for s in SPORTS])
    def test_load_sport_fixtures_count(self, sport: str) -> None:
        fixtures = load_sport_fixtures(sport)
        assert len(fixtures) >= MIN_FIXTURES_PER_SPORT, (
            f"load_sport_fixtures({sport!r}) returned {len(fixtures)}; "
            f"expected ≥ {MIN_FIXTURES_PER_SPORT}"
        )

    @pytest.mark.parametrize("sport", [s.upper() for s in SPORTS])
    def test_load_sport_fixtures_typed_fields_present(self, sport: str) -> None:
        for fx in load_sport_fixtures(sport):
            assert "corpus_id" in fx
            assert "expected_blocks" in fx
            assert "expected_block_type_counts" in fx
            assert "pbp" in fx


# ===========================================================================
# Forbidden phrase tests (ISSUE-047 integration)
# ===========================================================================


class TestForbiddenPhrases:
    @pytest.mark.parametrize("fixture_path", _ALL_FIXTURES, ids=_fixture_id)
    def test_no_generic_phrases_in_fixture(self, fixture_path: Path) -> None:
        """ISSUE-047 generic phrases must not appear in any fixture text field.

        The forbidden_phrases field declares the expected count (always 0).
        A match here is a hard failure: fix the fixture text, not this test.
        """
        data = load_fixture(fixture_path)
        text = all_text(data)
        found = [p for p in FORBIDDEN_PHRASES if p in text]
        assert not found, (
            f"{fixture_path.name}: contains {len(found)} forbidden phrase(s) "
            f"from ISSUE-047:\n"
            + "\n".join(f"  - {p!r}" for p in found)
            + "\n\nRemove these phrases from the fixture text to fix this failure."
        )


# ===========================================================================
# RESOLUTION specificity baseline (ISSUE-026)
# ===========================================================================

# Shapes with meaningful endings where the RESOLUTION specificity check must
# have material to work with.  Postponed / incomplete games lack PBP data so
# are excluded — the backend skips the check for those too.
_SHAPES_REQUIRING_FINAL_WINDOW = frozenset(
    {"standard_win", "blowout", "comeback", "overtime"}
)

# Final-window definitions must match validate_blocks._get_final_window_plays.
# Maps sport → (min_quarter, clock_threshold_secs).  MLB uses max-inning logic.
_CLOCK_SPORTS_FINAL_QUARTER: dict[str, tuple[int, int]] = {
    "NBA": (4, 120),
    "NFL": (4, 120),
}
_MIN_PERIOD_SPORTS: dict[str, int] = {
    "NHL": 3,
    "NCAAB": 2,
}


def _final_window_plays(plays: list[dict[str, Any]], sport: str) -> list[dict[str, Any]]:
    """Mirror of validate_blocks._get_final_window_plays for golden corpus checks."""
    if not plays:
        return []
    sport_upper = sport.upper()

    if sport_upper in _CLOCK_SPORTS_FINAL_QUARTER:
        final_q, threshold = _CLOCK_SPORTS_FINAL_QUARTER[sport_upper]
        result = []
        for ev in plays:
            q = ev.get("quarter", 0)
            if q > final_q:
                result.append(ev)
            elif q == final_q:
                clock = ev.get("game_clock", "")
                secs = _parse_clock(clock)
                if secs is not None and secs <= threshold:
                    result.append(ev)
        return result

    if sport_upper in _MIN_PERIOD_SPORTS:
        min_p = _MIN_PERIOD_SPORTS[sport_upper]
        return [ev for ev in plays if (ev.get("quarter") or 0) >= min_p]

    if sport_upper == "MLB":
        max_inn = max((ev.get("quarter") or 1) for ev in plays)
        return [ev for ev in plays if ev.get("quarter") == max_inn]

    # Unknown sport: last 20 %
    n = max(1, len(plays) // 5)
    return plays[-n:]


def _parse_clock(clock: str | None) -> int | None:
    if not clock:
        return None
    clock = clock.strip()
    try:
        if ":" in clock:
            parts = clock.split(":", 1)
            return int(parts[0]) * 60 + int(parts[1])
        return int(clock)
    except (ValueError, IndexError):
        return None


class TestResolutionSpecificity:
    """ISSUE-026 baseline: all reference fixtures provide enough final-window
    PBP data for the RESOLUTION specificity check to evaluate the narrative.

    This does NOT run the full pipeline; it asserts that each standard fixture
    has at least one named play in the final game window so that when the
    pipeline runs on real data the RESOLUTION check has material to work with.
    """

    @pytest.mark.parametrize("fixture_path", _ALL_FIXTURES, ids=_fixture_id)
    def test_standard_fixtures_have_named_final_window_plays(
        self, fixture_path: Path
    ) -> None:
        data = load_fixture(fixture_path)
        shape = data.get("game_shape", "")
        if shape not in _SHAPES_REQUIRING_FINAL_WINDOW:
            pytest.skip(f"Shape {shape!r} does not require final-window coverage")

        sport = data.get("sport", "UNKNOWN")
        plays: list[dict[str, Any]] = data.get("pbp", {}).get("plays", [])
        if not plays:
            pytest.skip("No plays in fixture")

        final_plays = _final_window_plays(plays, sport)
        assert final_plays, (
            f"{fixture_path.name}: no plays found in the final game window for "
            f"sport={sport}, shape={shape}. "
            "Add at least one final-window play so the RESOLUTION specificity "
            "check has material when the pipeline runs."
        )

        named = [p for p in final_plays if p.get("player_name", "").strip()]
        assert named, (
            f"{fixture_path.name}: final-window has {len(final_plays)} play(s) but "
            "none have a player_name. Add at least one named final-window play so "
            "the RESOLUTION specificity check can succeed."
        )
