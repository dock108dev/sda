"""Runner-advance derivation for `compute_timeline`.

Two strategies, used in order:

1. `_diff_advances` — when upstream supplies `basesAfter`, derive the
   advances by name-matching before/after slots. Preferred because it
   can't lie about which runner went where.
2. `_predict_advances` — fallback. Predict advances from the event type
   and base state alone, then reconcile against `runsScoredOnPlay`.

`parse_description_advances` augments either strategy with names and
destinations parsed from free-text play descriptions ("Smith scores",
"Jones to second", "Wilson out at third").
"""

from __future__ import annotations

import re

from .internal_types import RunnerAdvance
from .schemas import BaseMovement, BasesSituation, RunnerSummary
from .visual_mapper import batter_dest_for_event, downgrade_implausible

__all__ = [
    "apply_advances",
    "apply_run_constraint",
    "apply_runner_names",
    "build_base_movements",
    "diff_advances",
    "merge_parsed_advances",
    "names_match",
    "parse_description_advances",
    "predict_advances",
]


# ---------------------------------------------------------------------------
# Description-derived advance parsing
# ---------------------------------------------------------------------------

# Python `re` doesn't support \p{} natively; this is a close enough match
# for ASCII + most accented Latin chars.
_NAME = r"[A-ZÀ-ɏ][a-zA-ZÀ-ɏ'.\-]*(?:\s+[A-ZÀ-ɏ][a-zA-ZÀ-ɏ'.\-]*)*"
_BASE = r"1st|first|2nd|second|3rd|third|home(?:\s+plate)?"

_RE_SCORES = re.compile(rf"({_NAME})\s+scores\b", re.UNICODE)
_RE_TO_BASE = re.compile(rf"({_NAME})\s+to\s+({_BASE})\b", re.UNICODE)
_RE_OUT_AT = re.compile(
    rf"({_NAME})\s+(?:thrown\s+out\s+at|tagged\s+out\s+at|out\s+at|forced\s+out\s+at|caught\s+stealing(?:\s+at)?|picked\s+off\s+(?:at\s+)?)\s*({_BASE})\b",
    re.UNICODE,
)


def _parse_target_base(raw: str) -> str:
    t = raw.strip().lower()
    if t in ("1st", "first"):
        return "first"
    if t in ("2nd", "second"):
        return "second"
    if t in ("3rd", "third"):
        return "third"
    return "home"


def names_match(a: str | None, b: str | None) -> bool:
    """Lenient name match: exact, last-name-equal, or substring of last-name."""
    if not a or not b:
        return False
    x = a.strip().lower()
    y = b.strip().lower()
    if x == y:
        return True
    x_last = x.split()[-1] if x.split() else None
    y_last = y.split()[-1] if y.split() else None
    if x_last and y_last and x_last == y_last:
        return True
    if x_last and x_last in y:
        return True
    return bool(y_last and y_last in x)


def parse_description_advances(
    description: str,
    names_before: dict[str, str],
    batter_name: str | None,
) -> list[RunnerAdvance]:
    """Pick named runner advances out of a free-text play description."""
    if not description:
        return []

    def from_base_for(name: str) -> str | None:
        if names_match(name, names_before.get("first")):
            return "first"
        if names_match(name, names_before.get("second")):
            return "second"
        if names_match(name, names_before.get("third")):
            return "third"
        if names_match(name, batter_name):
            return "home"
        return None

    advances: list[RunnerAdvance] = []
    for m in _RE_SCORES.finditer(description):
        from_b = from_base_for(m.group(1))
        if from_b:
            advances.append(RunnerAdvance(from_base=from_b, to="home"))
    for m in _RE_TO_BASE.finditer(description):
        from_b = from_base_for(m.group(1))
        if not from_b:
            continue
        to = _parse_target_base(m.group(2))
        advances.append(RunnerAdvance(from_base=from_b, to=to))
    for m in _RE_OUT_AT.finditer(description):
        from_b = from_base_for(m.group(1))
        if not from_b:
            continue
        out_at = _parse_target_base(m.group(2))
        advances.append(RunnerAdvance(from_base=from_b, to="out", out_at=out_at))
    return advances


def merge_parsed_advances(
    predicted: list[RunnerAdvance], parsed: list[RunnerAdvance]
) -> list[RunnerAdvance]:
    """Description-parsed advances win over predicted ones, keyed by from_base."""
    if not parsed:
        return predicted
    by_from: dict[str, RunnerAdvance] = {}
    for a in predicted:
        by_from[a.from_base] = a
    for a in parsed:
        by_from[a.from_base] = a
    return list(by_from.values())


# ---------------------------------------------------------------------------
# Predict / diff / apply
# ---------------------------------------------------------------------------


def predict_advances(
    before: dict[str, bool], raw_event: str, profile: str | None
) -> list[RunnerAdvance]:
    """Predict runner movements from event type + base state alone."""
    event = downgrade_implausible(before, raw_event)
    advances: list[RunnerAdvance] = []
    advance_bases = (
        1 if event == "single"
        else 2 if event == "double"
        else 3 if event == "triple"
        else 4 if event == "home_run"
        else 0
    )
    dp_fly = profile == "double_play_fly"
    dp_grounder = profile == "double_play_grounder"
    is_force_walk = event in ("walk", "hit_by_pitch", "catcher_interference")
    is_free_base = event in ("balk", "wild_pitch", "passed_ball", "error")

    if before.get("third"):
        if advance_bases >= 1 or event == "sacrifice":
            advances.append(RunnerAdvance(from_base="third", to="home"))
        elif event in ("double_play", "triple_play"):
            if dp_fly:
                advances.append(RunnerAdvance(from_base="third", to="out", out_at="home"))
        elif is_free_base or is_force_walk and before.get("first") and before.get("second"):
            advances.append(RunnerAdvance(from_base="third", to="home"))
    if before.get("second"):
        if advance_bases >= 2:
            advances.append(RunnerAdvance(from_base="second", to="home"))
        elif advance_bases >= 1:
            advances.append(RunnerAdvance(from_base="second", to="third"))
        elif event in ("double_play", "triple_play"):
            if dp_grounder:
                advances.append(
                    RunnerAdvance(from_base="second", to="out", out_at="third")
                )
        elif event == "fielders_choice":
            advances.append(
                RunnerAdvance(from_base="second", to="out", out_at="third")
            )
        elif is_free_base or is_force_walk and before.get("first"):
            advances.append(RunnerAdvance(from_base="second", to="third"))
    if before.get("first"):
        if advance_bases >= 3:
            advances.append(RunnerAdvance(from_base="first", to="home"))
        elif advance_bases == 2:
            advances.append(RunnerAdvance(from_base="first", to="third"))
        elif advance_bases == 1 or is_force_walk:
            advances.append(RunnerAdvance(from_base="first", to="second"))
        elif event in ("double_play", "triple_play"):
            advances.append(
                RunnerAdvance(
                    from_base="first",
                    to="out",
                    out_at="first" if dp_fly else "second",
                )
            )
        elif event == "fielders_choice" and not before.get("second"):
            advances.append(
                RunnerAdvance(from_base="first", to="out", out_at="second")
            )
        elif is_free_base:
            advances.append(RunnerAdvance(from_base="first", to="second"))

    if event in ("caught_stealing", "pickoff"):
        if before.get("first"):
            advances.append(
                RunnerAdvance(
                    from_base="first",
                    to="out",
                    out_at="first" if event == "pickoff" else "second",
                )
            )
        elif before.get("second"):
            advances.append(
                RunnerAdvance(
                    from_base="second",
                    to="out",
                    out_at="second" if event == "pickoff" else "third",
                )
            )
        elif before.get("third"):
            advances.append(
                RunnerAdvance(from_base="third", to="out", out_at="home")
            )

    batter_dest = batter_dest_for_event(event)
    if batter_dest:
        out_at: str | None = None
        if batter_dest == "out" and event in (
            "field_out",
            "double_play",
            "triple_play",
            "sacrifice",
        ):
            if profile in ("popup", "shallow_fly", "deep_fly", "sacrifice_fly"):
                out_at = None
            else:
                out_at = "first"
        advances.append(
            RunnerAdvance(from_base="home", to=batter_dest, out_at=out_at)
        )

    return advances


def apply_run_constraint(
    before: dict[str, bool],
    advances: list[RunnerAdvance],
    runs_scored: int,
    event: str,
) -> list[RunnerAdvance]:
    """Reconcile advances with reported runsScored. Two-pass:
    1. Promote existing in-play advances to home (lead runner first).
    2. Add synthetic scoring advances for occupied bases without an entry.
    """
    if runs_scored <= 0:
        return advances
    out = list(advances)
    predicted_scores = sum(1 for a in out if a.to == "home")
    if predicted_scores >= runs_scored:
        return out

    from_order = {"third": 0, "second": 1, "first": 2, "home": 3}

    # Pass 1: promote existing in-play advances.
    while predicted_scores < runs_scored:
        best_idx = -1
        best_priority = float("inf")
        for i, a in enumerate(out):
            if a.to in ("home", "out"):
                continue
            if a.from_base == "home" and event != "home_run":
                continue
            p = from_order.get(a.from_base, 4)
            if p < best_priority:
                best_priority = p
                best_idx = i
        if best_idx < 0:
            break
        a = out[best_idx]
        out[best_idx] = RunnerAdvance(from_base=a.from_base, to="home", out_at=a.out_at)
        predicted_scores += 1

    # Pass 2: synthetic advances from unaccounted-for occupied bases.
    if predicted_scores < runs_scored:
        advanced_froms = {a.from_base for a in out}
        occupied_lead_first: list[str] = []
        if before.get("third"):
            occupied_lead_first.append("third")
        if before.get("second"):
            occupied_lead_first.append("second")
        if before.get("first"):
            occupied_lead_first.append("first")
        for b in occupied_lead_first:
            if predicted_scores >= runs_scored:
                break
            if b not in advanced_froms:
                out.append(RunnerAdvance(from_base=b, to="home"))
                advanced_froms.add(b)
                predicted_scores += 1

    return out


def apply_advances(
    before: dict[str, bool], advances: list[RunnerAdvance]
) -> dict[str, bool]:
    """Project the post-play occupancy from a base state + an advance list."""
    after = dict(before)
    for adv in advances:
        if adv.from_base in ("first", "second", "third"):
            after[adv.from_base] = False
    for adv in advances:
        if adv.to in ("first", "second", "third"):
            after[adv.to] = True
    return after


def apply_runner_names(
    before: dict[str, str],
    advances: list[RunnerAdvance],
    batter_name: str | None,
) -> dict[str, str]:
    """Project the post-play `{base: runner_name}` map from advances."""
    after = dict(before)
    for adv in advances:
        if adv.from_base in ("first", "second", "third"):
            after.pop(adv.from_base, None)
    for adv in advances:
        name = (
            before.get(adv.from_base)
            if adv.from_base in ("first", "second", "third")
            else batter_name
            if adv.from_base == "home"
            else None
        )
        if not name:
            continue
        if adv.to in ("first", "second", "third"):
            after[adv.to] = name
    return after


_VALID_OUT_AT = ("first", "second", "third", "home")


def build_base_movements(
    advances: list[RunnerAdvance],
    bases_before: BasesSituation,
    batter: RunnerSummary | None,
) -> list[BaseMovement]:
    """Derive `BaseMovement[]` from a play's advance list.

    The advance list is itself a diff of `situation_before.bases` vs
    `situation_after.bases` (plus the batter's destination from event
    context), so this transformation preserves the deterministic-diff
    contract: held runners are absent from `advances` and therefore
    absent from the result.

    Filters batter putouts (`from_base="home"` and `to_base="out"`):
    the in-place flare is driven by the animation profile, not a
    movement record. Resolves runner identity from `bases_before` for
    on-base runners and from `batter` for batter-originating advances.
    """
    movements: list[BaseMovement] = []
    for adv in advances:
        if adv.from_base == "home" and adv.to == "out":
            continue
        if adv.from_base == "home":
            runner = batter or RunnerSummary(id=None, name="Batter")
        else:
            existing = getattr(bases_before, adv.from_base, None)
            runner = existing or RunnerSummary(id=None, name="Runner")
        if adv.to == "out":
            style = "out"
            reason = "runner_out"
        elif adv.to == "home":
            style = "score"
            reason = "scored"
        elif adv.from_base == "home":
            style = "advance"
            reason = "batter_reached"
        else:
            style = "advance"
            reason = "base_changed"
        out_at = adv.out_at if adv.out_at in _VALID_OUT_AT else None
        movements.append(
            BaseMovement(
                runner=runner,
                from_base=adv.from_base,
                to_base=adv.to,
                style=style,
                out_at=out_at,
                reason=reason,
            )
        )
    return movements


def diff_advances(
    before: dict[str, bool],
    names_before: dict[str, str],
    after: dict[str, bool],
    names_after: dict[str, str],
    batter_name: str | None,
    batter_dest: str | None,
    runs_scored: int,
) -> list[RunnerAdvance]:
    """Derive RunnerAdvance[] from a known before/after pair.

    Matches by name first, then falls back to lead-runner positional matching.
    Used when upstream supplies basesAfter — preferred over predicting because
    it can't lie about which runner went where.
    """
    base_rank = {"home": 0, "first": 1, "second": 2, "third": 3}
    before_slots: list[dict[str, object]] = []
    if before.get("first"):
        before_slots.append({"base": "first", "name": names_before.get("first")})
    if before.get("second"):
        before_slots.append({"base": "second", "name": names_before.get("second")})
    if before.get("third"):
        before_slots.append({"base": "third", "name": names_before.get("third")})
    after_slots: list[dict[str, object]] = []
    if after.get("first"):
        after_slots.append({"base": "first", "name": names_after.get("first")})
    if after.get("second"):
        after_slots.append({"base": "second", "name": names_after.get("second")})
    if after.get("third"):
        after_slots.append({"base": "third", "name": names_after.get("third")})

    advances: list[RunnerAdvance] = []
    used_after: set[int] = set()

    # Pass 1: name-match every before-slot whose name we know.
    for b in before_slots:
        if not b["name"]:
            continue
        for i, a in enumerate(after_slots):
            if i in used_after:
                continue
            if a["name"] == b["name"]:
                used_after.add(i)
                if a["base"] != b["base"]:
                    advances.append(
                        RunnerAdvance(from_base=b["base"], to=a["base"])
                    )
                break

    # Pass 2: unmatched before-slots — runner left without a destination.
    runs_to_allocate = max(
        0, runs_scored - sum(1 for a in advances if a.to == "home")
    )
    if batter_dest == "home":
        runs_to_allocate = max(0, runs_to_allocate - 1)
    used_before_bases = {a.from_base for a in advances}
    unmatched_before = [
        b for b in before_slots if b["base"] not in used_before_bases
        and not any(
            i not in used_after and after_slots[i]["base"] == b["base"]
            for i in range(len(after_slots))
        )
    ]
    unmatched_before.sort(key=lambda x: -base_rank[x["base"]])
    for b in unmatched_before:
        if runs_to_allocate > 0:
            advances.append(RunnerAdvance(from_base=b["base"], to="home"))
            runs_to_allocate -= 1
        else:
            advances.append(RunnerAdvance(from_base=b["base"], to="out"))

    # Pass 3: batter destination.
    if batter_name and batter_dest and batter_dest not in ("out", "home"):
        advances.append(RunnerAdvance(from_base="home", to=batter_dest))
    elif batter_dest == "home":
        advances.append(RunnerAdvance(from_base="home", to="home"))
    elif batter_dest == "out":
        advances.append(RunnerAdvance(from_base="home", to="out"))

    return advances
