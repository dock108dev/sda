"""Pure scoring engine for golf country club pools.

This module contains NO database or framework dependencies.  It accepts
structured data and returns structured results so it can be tested in
isolation and called from any context (API, Celery task, CLI).

Scoring rules:
- RVCC: 7 picks, best 5 of those who made the cut, min 5 to qualify
- Crestmont: 6 picks (1 per bucket), best 4 of those who made the cut, min 4 to qualify

Status semantics (from golf_leaderboard.status):
- "active": golfer is still in the tournament — eligible to count
- "cut": golfer missed the cut — NOT eligible
- "wd": golfer withdrew — NOT eligible
- "dq": golfer disqualified — NOT eligible

total_score is relative to par (negative = under par = good).
Lower aggregate score wins.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# ---------------------------------------------------------------------------
# Rule definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PoolRules:
    """Parsed pool rules."""

    variant: str  # "rvcc" or "crestmont"
    pick_count: int  # 7 for RVCC, 6 for Crestmont
    count_best: int  # 5 for RVCC, 4 for Crestmont
    min_cuts_to_qualify: int  # 5 for RVCC, 4 for Crestmont
    uses_buckets: bool  # False for RVCC, True for Crestmont


RVCC_RULES = PoolRules(
    variant="rvcc",
    pick_count=7,
    count_best=5,
    min_cuts_to_qualify=5,
    uses_buckets=False,
)

CRESTMONT_RULES = PoolRules(
    variant="crestmont",
    pick_count=6,
    count_best=4,
    min_cuts_to_qualify=4,
    uses_buckets=True,
)

_RULES_BY_VARIANT: dict[str, PoolRules] = {
    "rvcc": RVCC_RULES,
    "crestmont": CRESTMONT_RULES,
}


def get_rules(variant: str) -> PoolRules:
    """Get rules for a pool variant.  Raises ValueError if unknown."""
    rules = _RULES_BY_VARIANT.get(variant.lower())
    if rules is None:
        raise ValueError(f"Unknown pool variant: {variant!r}")
    return rules


def rules_from_json(rules_json: dict[str, Any]) -> PoolRules:
    """Reconstruct PoolRules from a JSONB rules dict."""
    variant = rules_json.get("variant", "")
    return PoolRules(
        variant=variant,
        pick_count=rules_json.get("pick_count", get_rules(variant).pick_count),
        count_best=rules_json.get("count_best", get_rules(variant).count_best),
        min_cuts_to_qualify=rules_json.get("min_cuts_to_qualify", get_rules(variant).min_cuts_to_qualify),
        uses_buckets=rules_json.get("uses_buckets", get_rules(variant).uses_buckets),
    )


# ---------------------------------------------------------------------------
# Input / output types
# ---------------------------------------------------------------------------

# Eligible statuses — only "active" golfers count toward scoring
_ELIGIBLE_STATUSES = frozenset({"active"})


@dataclass
class GolferScore:
    """Live score data for a single golfer, sourced from golf_leaderboard."""

    dg_id: int
    player_name: str
    status: str  # "active", "cut", "wd", "dq"
    position: int | None = None
    total_score: int | None = None
    thru: int | None = None
    r1: int | None = None
    r2: int | None = None
    r3: int | None = None
    r4: int | None = None


@dataclass
class Pick:
    """A single golfer pick in a pool entry."""

    dg_id: int
    player_name: str
    pick_slot: int
    bucket_number: int | None = None


@dataclass
class Entry:
    """A pool entry with its picks."""

    entry_id: int
    email: str
    entry_name: str | None
    picks: list[Pick]


@dataclass
class ScoredPick:
    """Result of scoring a single pick against live data."""

    dg_id: int
    player_name: str
    pick_slot: int
    bucket_number: int | None
    # Live data snapshots
    status: str
    position: int | None
    total_score: int | None
    thru: int | None
    r1: int | None
    r2: int | None
    r3: int | None
    r4: int | None
    # Scoring flags
    made_cut: bool
    counts_toward_total: bool
    is_dropped: bool
    # Sort key for ranking picks (lower = better)
    sort_score: int | None


@dataclass
class ScoredEntry:
    """Complete scored entry with aggregate and qualification info."""

    entry_id: int
    email: str
    entry_name: str | None
    picks: list[ScoredPick]
    aggregate_score: int | None
    qualified_golfers_count: int
    counted_golfers_count: int
    qualification_status: str  # "qualified", "not_qualified", "pending"
    is_complete: bool
    rank: int | None = None
    is_tied: bool = False


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_picks(
    picks: list[Pick],
    rules: PoolRules,
    valid_dg_ids: set[int] | None = None,
    bucket_players: dict[int, set[int]] | None = None,
) -> list[str]:
    """Validate picks against pool rules.  Returns list of error messages."""
    errors: list[str] = []

    # Check pick count
    if len(picks) != rules.pick_count:
        errors.append(f"Expected {rules.pick_count} picks, got {len(picks)}")

    # Check for duplicate golfers
    dg_ids = [p.dg_id for p in picks]
    if len(set(dg_ids)) != len(dg_ids):
        errors.append("Duplicate golfer picks not allowed")

    # Check valid player universe
    if valid_dg_ids is not None:
        for pick in picks:
            if pick.dg_id not in valid_dg_ids:
                errors.append(f"Player {pick.player_name} (dg_id={pick.dg_id}) not in tournament field")

    # Bucket validation for Crestmont
    if rules.uses_buckets:
        if bucket_players is None:
            errors.append("Bucket assignments required for this pool variant")
        else:
            buckets_used: set[int] = set()
            for pick in picks:
                if pick.bucket_number is None:
                    errors.append(f"Pick {pick.player_name} missing bucket assignment")
                    continue
                if pick.bucket_number in buckets_used:
                    errors.append(f"Bucket {pick.bucket_number} used more than once")
                buckets_used.add(pick.bucket_number)

                allowed = bucket_players.get(pick.bucket_number, set())
                if pick.dg_id not in allowed:
                    errors.append(
                        f"Player {pick.player_name} not in bucket {pick.bucket_number}"
                    )

    return errors


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_entry(
    entry: Entry,
    golfer_scores: dict[int, GolferScore],
    rules: PoolRules,
) -> ScoredEntry:
    """Score a single pool entry against live leaderboard data.

    Args:
        entry: The entry with its picks.
        golfer_scores: Live score data keyed by dg_id.
        rules: Pool rules for this variant.

    Returns:
        Fully scored entry with per-pick details and aggregate.
    """
    scored_picks: list[ScoredPick] = []
    eligible_picks: list[ScoredPick] = []

    for pick in entry.picks:
        gs = golfer_scores.get(pick.dg_id)

        if gs is None:
            # Golfer not on leaderboard — treat as if they haven't started
            scored_pick = ScoredPick(
                dg_id=pick.dg_id,
                player_name=pick.player_name,
                pick_slot=pick.pick_slot,
                bucket_number=pick.bucket_number,
                status="unknown",
                position=None,
                total_score=None,
                thru=None,
                r1=None, r2=None, r3=None, r4=None,
                made_cut=False,
                counts_toward_total=False,
                is_dropped=True,
                sort_score=None,
            )
        else:
            made_cut = gs.status in _ELIGIBLE_STATUSES
            sort_score = gs.total_score if gs.total_score is not None else 999

            scored_pick = ScoredPick(
                dg_id=pick.dg_id,
                player_name=pick.player_name,
                pick_slot=pick.pick_slot,
                bucket_number=pick.bucket_number,
                status=gs.status,
                position=gs.position,
                total_score=gs.total_score,
                thru=gs.thru,
                r1=gs.r1, r2=gs.r2, r3=gs.r3, r4=gs.r4,
                made_cut=made_cut,
                counts_toward_total=False,  # Set below
                is_dropped=True,  # Set below
                sort_score=sort_score,
            )

            if made_cut:
                eligible_picks.append(scored_pick)

        scored_picks.append(scored_pick)

    # Determine qualification
    qualified_count = len(eligible_picks)

    if qualified_count >= rules.min_cuts_to_qualify:
        qualification_status = "qualified"
    elif _any_rounds_pending(golfer_scores, entry.picks):
        qualification_status = "pending"
    else:
        qualification_status = "not_qualified"

    # Select best N picks to count
    eligible_picks.sort(key=lambda p: p.sort_score if p.sort_score is not None else 999)
    counted = eligible_picks[: rules.count_best]

    counted_ids = {p.dg_id for p in counted}
    for sp in scored_picks:
        if sp.dg_id in counted_ids:
            sp.counts_toward_total = True
            sp.is_dropped = False

    # Compute aggregate
    aggregate = None
    if counted:
        scores = [p.total_score for p in counted if p.total_score is not None]
        if scores:
            aggregate = sum(scores)

    # Check completeness — all counted golfers have finished all rounds
    is_complete = all(
        p.thru == 18 or p.thru is None  # None = not started or completed
        for p in counted
    ) and qualification_status != "pending"

    return ScoredEntry(
        entry_id=entry.entry_id,
        email=entry.email,
        entry_name=entry.entry_name,
        picks=scored_picks,
        aggregate_score=aggregate,
        qualified_golfers_count=qualified_count,
        counted_golfers_count=len(counted),
        qualification_status=qualification_status,
        is_complete=is_complete,
    )


def _any_rounds_pending(
    golfer_scores: dict[int, GolferScore],
    picks: list[Pick],
) -> bool:
    """Check if any picked golfer hasn't completed round 2 yet (cut pending)."""
    for pick in picks:
        gs = golfer_scores.get(pick.dg_id)
        if gs is None:
            return True  # Not on leaderboard yet
        if gs.status == "active" and gs.r2 is None:
            return True  # Round 2 not complete, cut not settled
    return False


# ---------------------------------------------------------------------------
# Leaderboard ranking
# ---------------------------------------------------------------------------

def rank_entries(entries: list[ScoredEntry]) -> list[ScoredEntry]:
    """Assign ranks to scored entries.

    - Qualified entries ranked first by aggregate score (lower wins)
    - Tied entries share the same rank
    - Not-qualified entries ranked after all qualified entries
    - Pending entries ranked after qualified, before not-qualified
    """
    # Separate by qualification status
    qualified = [e for e in entries if e.qualification_status == "qualified"]
    pending = [e for e in entries if e.qualification_status == "pending"]
    not_qualified = [e for e in entries if e.qualification_status == "not_qualified"]

    # Sort qualified by aggregate score (lower = better)
    qualified.sort(key=lambda e: e.aggregate_score if e.aggregate_score is not None else 9999)

    # Assign ranks with tie handling
    rank = 1
    for i, entry in enumerate(qualified):
        if i > 0 and entry.aggregate_score == qualified[i - 1].aggregate_score:
            entry.rank = qualified[i - 1].rank
            entry.is_tied = True
            qualified[i - 1].is_tied = True
        else:
            entry.rank = rank
        rank = i + 2  # Next rank accounts for position

    # Pending get rank after last qualified
    for entry in pending:
        entry.rank = rank
        rank += 1

    # Not qualified get no rank
    for entry in not_qualified:
        entry.rank = None

    return qualified + pending + not_qualified


# ---------------------------------------------------------------------------
# Full pool scoring
# ---------------------------------------------------------------------------

def score_pool(
    entries: list[Entry],
    golfer_scores: dict[int, GolferScore],
    rules: PoolRules,
) -> list[ScoredEntry]:
    """Score all entries in a pool and return ranked leaderboard."""
    scored = [score_entry(e, golfer_scores, rules) for e in entries]
    return rank_entries(scored)
