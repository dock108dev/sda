# Timeline Validation

> **Status:** Canonical
> **Parent Contract:** [Timeline Assembly](timeline-assembly.md)
> **Last Updated:** 2026-02-11

---

## Purpose

Validation checks run against every generated timeline before persistence. Critical failures block persistence; warnings are logged but do not block.

**Implementation:** `api/app/services/timeline_validation.py`

---

## Validation Levels

| Level | When to Run | Blocks Persistence? |
|-------|-------------|---------------------|
| **Critical** | Every timeline | Yes |
| **Warning** | Every timeline | No, but logged |

---

## Phase Order Reference

Validation uses the canonical `PHASE_ORDER` from `timeline_types.py` (single source of truth for all leagues):

```python
PHASE_ORDER = {
    "pregame": 0,
    "q1": 1, "first_half": 1, "p1": 1,   # NBA / NCAAB / NHL
    "q2": 2,
    "halftime": 3, "p2": 3,
    "q3": 4, "second_half": 4,
    "q4": 5, "p3": 5,
    "ot": 6, "ot1": 6,
    "ot2": 7, "ot3": 8, "ot4": 9,
    "shootout": 10,
    "postgame": 99,
}
```

Unknown phases sort after postgame (order 100).

---

## Critical Checks

These must pass. Failures block persistence.

### C1: Timeline Not Empty

Timeline must contain at least one event, and at least one PBP event.

```python
def check_not_empty(timeline):
    if len(timeline) == 0:
        return Fail("Timeline is empty")
    pbp_count = sum(1 for e in timeline if e.get("event_type") == "pbp")
    if pbp_count == 0:
        return Fail("Timeline has no PBP events")
    return Pass(f"Timeline has {len(timeline)} events ({pbp_count} PBP)")
```

---

### C2: Phase Order Integrity

Phase order must be monotonically non-decreasing across all events.

```python
def check_phase_order(timeline):
    # Walk events, verify PHASE_ORDER[current] >= PHASE_ORDER[previous]
    # Unknown phases get order 50 (sorts between game phases and postgame)
```

**Failure:** `"Phase regression: q2 appeared after q3"`

---

### C3: No Duplicate Events

No event should appear twice. Identity keys are type-specific:

| Event Type | Dedup Key |
|------------|-----------|
| `pbp` | `("pbp", play_index)` |
| `tweet` | `("tweet", synthetic_timestamp, author)` |
| `odds` | `("odds", odds_type, book)` |
| other | `("other", event_index)` — always unique |

```python
def check_no_duplicates(timeline):
    seen = set()
    for i, event in enumerate(timeline):
        event_type = event.get("event_type", "unknown")
        if event_type == "pbp":
            key = ("pbp", str(event.get("play_index")))
        elif event_type == "tweet":
            key = ("tweet", event.get("synthetic_timestamp", ""), event.get("author", ""))
        elif event_type == "odds":
            key = ("odds", event.get("odds_type", ""), event.get("book", ""))
        else:
            key = ("other", str(i))
        if key in seen:
            duplicates.append(...)
        seen.add(key)
```

**Failure:** `"Duplicate event: ('pbp', '145')"`

---

### C4: Social Events Have Phase

All social (tweet) events must have a non-empty `phase` field.

```python
def check_social_has_phase(timeline):
    # For each event where event_type == "tweet":
    #   phase must not be None or ""
```

**Failure:** `"3 social events missing phase"`

---

### C5: Social Events Have Content

No social events with null or empty text.

```python
def check_social_has_content(timeline):
    # For each event where event_type == "tweet":
    #   text must not be None or empty string
```

**Failure:** `"2 social events with null/empty content"`

---

### C6: PBP Timestamps Monotonic Within Phase

PBP synthetic timestamps must be non-decreasing within each phase. Tweet and odds timestamps are not checked (wall-clock times may interleave with synthetic PBP timestamps).

```python
def check_timestamps_monotonic(timeline):
    # Group PBP events by phase
    # Within each phase, verify timestamps are non-decreasing
```

**Failure:** `"PBP timestamp regression in q2"`

---

## Warning Checks

These indicate potential issues. Logged but do not block persistence.

### W1: Social Events Have Role

Social events should have a `role` field assigned (e.g., `hype`, `reaction`, `momentum`).

**Warning:** `"3 social events missing role"`

---

### W2: Phase Coverage

Timeline should have events in the expected game phases (q1, q2, q3, q4 for NBA).

**Warning:** `"Missing expected phases: {'q3'}"`

---

### W3: Summary Phases Match Timeline

If a summary includes `phases_in_timeline`, those phases should match the phases actually present in the timeline.

**Warning:** `"Summary phases don't match timeline phases"`

---

### W4: Odds Events Have Phase

All odds events must have a non-empty `phase` field. In practice, odds events always have `phase="pregame"`.

**Warning:** `"2 odds events missing phase"`

---

## Validation Report Format

```json
{
  "game_id": 98948,
  "verdict": "PASS_WITH_WARNINGS",
  "critical": {
    "passed": 6,
    "failed": 0,
    "checks": [
      {"name": "C1_not_empty", "status": "pass", "message": "Timeline has 458 events (456 PBP)"},
      {"name": "C2_phase_order", "status": "pass", "message": "Phase order is monotonic"},
      {"name": "C3_no_duplicates", "status": "pass", "message": "No duplicate events"},
      {"name": "C4_social_has_phase", "status": "pass", "message": "All social events have phase"},
      {"name": "C5_social_has_content", "status": "pass", "message": "All social events have content"},
      {"name": "C6_timestamps_monotonic", "status": "pass", "message": "PBP timestamps are monotonic within phases"}
    ]
  },
  "warnings": {
    "count": 1,
    "checks": [
      {"name": "W2_phase_coverage", "status": "warn", "message": "Missing expected phases: {'halftime'}"}
    ]
  }
}
```

---

## Verdict Levels

| Verdict | Meaning |
|---------|---------|
| `PASS` | All critical checks passed, no warnings |
| `PASS_WITH_WARNINGS` | All critical checks passed, warnings logged |
| `FAIL` | One or more critical checks failed — timeline NOT persisted |

---

## Integration

Validation runs automatically inside `generate_timeline_artifact()`:

```python
async def generate_timeline_artifact(session, game_id, ...):
    # ... build timeline ...

    report = validate_and_log(timeline, summary, game_id)
    # validate_and_log raises TimelineValidationError on FAIL verdict

    # ... persist artifact ...
```

---

## Changelog

| Date | Change |
|------|--------|
| 2026-02-11 | Aligned with implementation: C1-C6, W1-W4. Added odds dedup key (C3). Added W4 odds_has_phase. Removed unimplemented diagnostic checks. |
| 2026-01-14 | Initial validation spec |
