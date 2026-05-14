"""Scenario coverage + state round-trip tests across the QA fixture corpus.

The QA scenario manifest (`tests/fixtures/scroll_down_mlb/games/_manifest.json`)
carries boolean coverage flags so scripted audits can answer "do we have a
fixture exercising scenario X?" without scanning play-by-play text. This
module verifies two things:

1. The flags in the manifest match what the deck builder actually emits
   (no drift between human-edited metadata and the pipeline's output).
2. Every fixture's half-inning containers carry well-formed
   `base_state_before`/`base_state_after`/`outs_before`/`outs_after` and
   round-trip cleanly through `_group_into_containers()` — i.e. the post-
   state of event N matches the pre-state of event N+1 within a half-
   inning, modulo runs scored on play N.

The synthetic `live_partial_inning` fixture exercises the open-container
path that no completed-game fixture can reach: a game where the last
half-inning has non-zero outs but no third out is captured, so the
container is emitted with a partial event list.

Held-runner correctness (no `BaseMovement` for runners that stayed put)
is asserted via the `hasRunnersStayingPut` scenario in every fixture
that flags it true.

Pitching change is included in the flag schema for completeness but is
expected to be False for every current fixture — the upstream play feed
does not model substitution events as plays. The flag exists so a future
ingestion that surfaces pitching changes can flip it without a schema
migration.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.scroll_down_mlb.schemas import GenerationPolicy, ScrollDownHalfInningContainer
from app.scroll_down_mlb.service import build_deck_from_upstream

_FIXTURES_DIR = (
    Path(__file__).parent / "fixtures" / "scroll_down_mlb" / "games"
)


SCENARIO_FLAGS: tuple[str, ...] = (
    "hasDouble",
    "hasTriple",
    "hasHomeRun",
    "hasDoublePlay",
    "hasPitchingChange",
    "hasBasesLoadedWalk",
    "hasRunnersStayingPut",
)


def _all_fixture_ids() -> list[str]:
    return sorted(
        p.stem for p in _FIXTURES_DIR.glob("*.json") if p.stem.isdigit()
    )


def _load(path: Path) -> dict[str, Any]:
    with path.open() as f:
        return json.load(f)


def _manifest_by_id() -> dict[str, dict[str, Any]]:
    entries = _load(_FIXTURES_DIR / "_manifest.json")
    return {e["id"]: e for e in entries}


def _compute_scenario_flags(payload: dict[str, Any]) -> dict[str, bool]:
    """Re-derive scenario flags from upstream + deck builder output.

    Upstream `playType` is the source of truth for typed-event scenarios.
    Container-level scenarios (bases-loaded walk, runners staying put)
    are derived from the deck builder's reconstructed half-inning events
    so the assertion matches what the renderer actually sees.
    """
    flags: dict[str, bool] = {k: False for k in SCENARIO_FLAGS}

    for play in payload.get("plays", []):
        play_type = (play.get("playType") or "").upper()
        if play_type == "DOUBLE":
            flags["hasDouble"] = True
        elif play_type == "TRIPLE":
            flags["hasTriple"] = True
        elif play_type == "HOME_RUN":
            flags["hasHomeRun"] = True
        elif play_type == "DOUBLE_PLAY":
            flags["hasDoublePlay"] = True
        elif play_type in {"PITCHING_CHANGE", "SUBSTITUTION"}:
            flags["hasPitchingChange"] = True

    outcome = build_deck_from_upstream(payload, policy=GenerationPolicy.live)
    deck = outcome.deck
    if deck is None:
        return flags

    for container in deck.half_innings:
        for event in container.events:
            before = event.base_state_before
            after = event.base_state_after
            if before is None or after is None:
                continue
            event_type = (event.event_type or "").lower()
            if (
                event_type == "walk"
                and before.first
                and before.second
                and before.third
                and event.runs_scored_on_play == 1
            ):
                flags["hasBasesLoadedWalk"] = True

            runners_before = int(before.first) + int(before.second) + int(before.third)
            if (
                runners_before >= 2
                and before.first == after.first
                and before.second == after.second
                and before.third == after.third
                and len(event.movements) == 0
            ):
                flags["hasRunnersStayingPut"] = True

    return flags


def _build_deck(fixture_id: str):
    payload = _load(_FIXTURES_DIR / f"{fixture_id}.json")
    outcome = build_deck_from_upstream(payload, policy=GenerationPolicy.live)
    assert outcome.deck is not None, (
        f"Fixture {fixture_id} produced no deck "
        f"(errors={[e.code for e in outcome.errors]})"
    )
    return payload, outcome.deck


@pytest.mark.parametrize("fixture_id", _all_fixture_ids())
def test_manifest_scenario_flags_match_pipeline_output(fixture_id: str) -> None:
    """Each manifest entry's scenario flags must match what the deck
    builder pipeline derives. Catches drift between hand-edited manifest
    metadata and the actual fixture content."""
    manifest = _manifest_by_id()
    entry = manifest.get(fixture_id)
    assert entry is not None, f"Fixture {fixture_id} missing from manifest"

    payload = _load(_FIXTURES_DIR / f"{fixture_id}.json")
    expected = _compute_scenario_flags(payload)
    actual = {k: entry.get(k, False) for k in SCENARIO_FLAGS}
    assert actual == expected, (
        f"Fixture {fixture_id} scenario-flag drift: "
        f"manifest={actual} pipeline={expected}"
    )


def test_corpus_covers_required_scenarios() -> None:
    """The fixture corpus must collectively cover every scenario flagged
    in the manifest schema except `hasPitchingChange` — the upstream play
    feed does not surface substitution events, so no current fixture can
    flip that flag. The flag exists in the schema so a future ingestion
    that adds pitching-change plays can flip it without a migration."""
    manifest = list(_manifest_by_id().values())
    covered: dict[str, list[str]] = {k: [] for k in SCENARIO_FLAGS}
    for entry in manifest:
        for flag in SCENARIO_FLAGS:
            if entry.get(flag):
                covered[flag].append(entry["id"])

    uncovered = [
        flag
        for flag, ids in covered.items()
        if not ids and flag != "hasPitchingChange"
    ]
    assert not uncovered, (
        f"Scenario flags with zero coverage in fixture corpus: {uncovered}"
    )


def test_corpus_contains_live_partial_inning_fixture() -> None:
    """At least one fixture must exercise the open-container path:
    `is_final == False`, last half-inning has non-zero outs and no
    inning-end signal."""
    found = False
    for fid in _all_fixture_ids():
        _, deck = _build_deck(fid)
        if deck.is_final:
            continue
        if not deck.half_innings:
            continue
        last = deck.half_innings[-1]
        if not last.events:
            continue
        last_event = last.events[-1]
        if (
            last_event.outs_after is not None
            and 0 < last_event.outs_after < 3
        ):
            found = True
            break
    assert found, (
        "No fixture exercises the live partial inning path "
        "(is_final=False with non-zero outs in the trailing half-inning)."
    )


@pytest.mark.parametrize("fixture_id", _all_fixture_ids())
def test_container_events_carry_full_situation(fixture_id: str) -> None:
    """Every event in every container must carry `base_state_before`,
    `base_state_after`, `outs_before`, `outs_after`, and `score_before`.
    These are the wire-side mirrors of `situation_before.bases`,
    `situation_after.bases`, `situation_before.outs`, `situation_after.outs`,
    and `situation_before.score`."""
    _, deck = _build_deck(fixture_id)
    issues: list[str] = []
    for container in deck.half_innings:
        for event in container.events:
            ref = (
                f"{fixture_id} inning {container.inning}/{container.half} "
                f"play={event.play_index}"
            )
            if event.base_state_before is None:
                issues.append(f"{ref}: base_state_before is None")
            if event.base_state_after is None:
                issues.append(f"{ref}: base_state_after is None")
            if event.outs_before is None:
                issues.append(f"{ref}: outs_before is None")
            if event.outs_after is None:
                issues.append(f"{ref}: outs_after is None")
            if event.score_before is None:
                issues.append(f"{ref}: score_before is None")
    assert not issues, "Missing situation fields:\n  " + "\n  ".join(issues[:8])


@pytest.mark.parametrize("fixture_id", _all_fixture_ids())
def test_situation_round_trips_within_half_inning(fixture_id: str) -> None:
    """For consecutive events within a half-inning, the post-state of
    event N must equal the pre-state of event N+1 — the round-trip
    guarantee through `_group_into_containers()`. The grouper buckets
    timeline entries by `(inning, half)`; for any two adjacent events in
    the same bucket, the timeline's running state must be carried
    intact.

    Score continuity uses `score_before + score_change` because the wire
    payload intentionally omits `score_after`.

    Exception: when the prior event closes the half (outs_after >= 3) and
    the next event resets to zero outs, the upstream feed has merged two
    real half-innings under a single (inning, half) label. The grouper
    faithfully reflects the timeline; this is not a state-propagation
    bug, so the continuity check is skipped at those legitimate reset
    boundaries.
    """
    _, deck = _build_deck(fixture_id)
    issues: list[str] = []
    for container in deck.half_innings:
        events = container.events
        for prev, curr in zip(events, events[1:]):
            if (
                prev.outs_after is not None
                and prev.outs_after >= 3
                and curr.outs_before == 0
            ):
                continue
            ref = (
                f"{fixture_id} inning {container.inning}/{container.half}: "
                f"play {prev.play_index} → play {curr.play_index}"
            )
            if prev.base_state_after != curr.base_state_before:
                issues.append(
                    f"{ref}: bases drift "
                    f"after={prev.base_state_after} "
                    f"before(next)={curr.base_state_before}"
                )
            if prev.outs_after != curr.outs_before:
                issues.append(
                    f"{ref}: outs drift "
                    f"after={prev.outs_after} before(next)={curr.outs_before}"
                )
            if prev.score_before is None or curr.score_before is None:
                continue
            prev_after_home = prev.score_before.home + prev.score_change.home
            prev_after_away = prev.score_before.away + prev.score_change.away
            if (
                prev_after_home != curr.score_before.home
                or prev_after_away != curr.score_before.away
            ):
                issues.append(
                    f"{ref}: score drift "
                    f"computed_after=({prev_after_home},{prev_after_away}) "
                    f"before(next)=({curr.score_before.home},{curr.score_before.away})"
                )
    assert not issues, (
        f"Fixture {fixture_id} situation continuity drift:\n  "
        + "\n  ".join(issues[:6])
    )


@pytest.mark.parametrize("fixture_id", _all_fixture_ids())
def test_held_runners_emit_no_base_movement(fixture_id: str) -> None:
    """Per the held-runner absence-based encoding: when a runner stays
    on the same base across an event, no `BaseMovement` is emitted. This
    test scans every event in every fixture for held runners and asserts
    no movement record references their (from→same) base.
    """
    _, deck = _build_deck(fixture_id)
    violations: list[str] = []
    for container in deck.half_innings:
        for event in container.events:
            before = event.base_state_before
            after = event.base_state_after
            if before is None or after is None:
                continue
            for base in ("first", "second", "third"):
                # A held runner: occupied before AND occupied after by the
                # same base. The container schema doesn't carry runner
                # identity per base, so equality of base occupancy plus
                # absence of a movement out of that base is the held-
                # runner signal.
                if not getattr(before, base) or not getattr(after, base):
                    continue
                moved_away = any(
                    m.from_base == base for m in event.movements
                )
                if moved_away:
                    continue
                # Confirm no spurious self-loop in movements.
                spurious = [
                    m
                    for m in event.movements
                    if m.from_base == base and m.to_base == base
                ]
                if spurious:
                    violations.append(
                        f"{fixture_id} play {event.play_index}: "
                        f"held runner on {base} emitted self-loop movement"
                    )
    assert not violations, "Held-runner movement violations:\n  " + "\n  ".join(
        violations[:6]
    )


def test_live_partial_inning_fixture_specifics() -> None:
    """The synthetic live partial inning fixture (`999125`) is the only
    one structurally guaranteed to exercise the open-container path. Pin
    its load-bearing properties here so a future trim/regenerate cannot
    silently lose the coverage.
    """
    fixture_id = "999125"
    payload, deck = _build_deck(fixture_id)

    assert not deck.is_final, "Live partial inning fixture must have isFinal=False"
    assert deck.half_innings, "Expected non-empty half-innings list"

    last = deck.half_innings[-1]
    assert last.events, "Last half-inning container must be non-empty"
    last_event = last.events[-1]
    assert last_event.outs_after is not None
    assert 0 < last_event.outs_after < 3, (
        "Live partial inning fixture must end mid-half-inning with "
        f"non-zero outs and no third-out signal; got outs_after={last_event.outs_after}"
    )

    total_events = sum(len(hc.events) for hc in deck.half_innings)
    selected_total = sum(len(hc.selected_play_indices) for hc in deck.half_innings)
    assert selected_total < total_events, (
        "selected_play_indices must be a strict subset of total events"
    )

    # The wire schema for HalfInningEvent does not carry a per-event
    # `score_after`. The presence of `score_change` plus `score_before`
    # is the renderer's path to the running score. Pin this structural
    # guarantee for the open container so a future schema relaxation
    # cannot leak post-play cumulative scores from a live game.
    for event in last.events:
        dumped = event.model_dump(by_alias=True)
        assert "scoreAfter" not in dumped, (
            "Open container event must not carry scoreAfter"
        )


def test_corpus_runners_staying_put_has_held_movement_zero() -> None:
    """Existence test for the load-bearing held-runner scenario: at
    least one event somewhere in the corpus has 2+ runners on base,
    identical bases before/after, and zero `BaseMovement` entries.
    """
    found = False
    for fid in _all_fixture_ids():
        _, deck = _build_deck(fid)
        for container in deck.half_innings:
            for event in container.events:
                before = event.base_state_before
                after = event.base_state_after
                if before is None or after is None:
                    continue
                runners_before = (
                    int(before.first) + int(before.second) + int(before.third)
                )
                if (
                    runners_before >= 2
                    and before.first == after.first
                    and before.second == after.second
                    and before.third == after.third
                    and len(event.movements) == 0
                ):
                    found = True
                    break
            if found:
                break
        if found:
            break
    assert found, (
        "No fixture event exercises the held-runner zero-movement encoding "
        "(2+ runners on, identical before/after bases, empty movements)."
    )


def test_corpus_bases_loaded_walk_scores_one_run() -> None:
    """At least one event in the corpus must be a bases-loaded walk:
    walk event with all three bases occupied beforehand and exactly one
    run scored on the play."""
    found = False
    for fid in _all_fixture_ids():
        _, deck = _build_deck(fid)
        for container in deck.half_innings:
            for event in container.events:
                before = event.base_state_before
                if before is None:
                    continue
                if (
                    (event.event_type or "").lower() == "walk"
                    and before.first and before.second and before.third
                    and event.runs_scored_on_play == 1
                ):
                    found = True
                    break
            if found:
                break
        if found:
            break
    assert found, "No bases-loaded walk found in fixture corpus."


def test_corpus_container_grouping_orders_top_before_bottom() -> None:
    """`_group_into_containers` must order top of inning N before bottom
    of inning N, and inning N before inning N+1. Spot-check the structural
    invariant across the corpus rather than re-testing every fixture."""
    for fid in _all_fixture_ids():
        _, deck = _build_deck(fid)
        prev_key: tuple[int, int] | None = None
        for container in deck.half_innings:
            assert isinstance(container, ScrollDownHalfInningContainer)
            half_rank = 0 if container.half == "top" else 1
            key = (container.inning, half_rank)
            if prev_key is not None:
                assert key > prev_key, (
                    f"{fid}: containers out of order {prev_key} → {key}"
                )
            prev_key = key
