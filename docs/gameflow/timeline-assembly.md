# Timeline Assembly

> **Status:** Canonical
> **Last Updated:** 2026-02-11

---

## Purpose

This document defines the **exact recipe** for assembling a unified game timeline from heterogeneous event sources. The process is deterministic and explainable.

**Implementation:** `api/app/services/timeline_events.py` (merge), `timeline_generator.py` (orchestration)

---

## Inputs

| Source | Fields Used | Count (typical) | Required? |
|--------|-------------|-----------------|-----------|
| PBP events | `quarter`, `game_clock`, `play_index`, `description` | 400-500 | Yes |
| Social posts | `posted_at`, `text`, `source_handle`, `media_type` | 0-50 | No |
| Odds rows | `book`, `market_type`, `line`, `price`, `is_closing_line` | 0-8 | No |
| Game metadata | `game_date`, `home_team`, `away_team`, `final_score` | 1 | Yes |

Social and odds data are **optional**. The pipeline produces a valid timeline with PBP events alone.

---

## Phase Order Reference

Validation and merge ordering use the canonical `PHASE_ORDER` from `timeline_types.py` (single source of truth for all leagues):

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

Unknown phases sort at order 100.

---

## The Assembly Recipe

### Step 0: Compute Phase Boundaries

Before processing events, compute the time boundaries for each narrative phase. Used to assign social posts to phases.

```python
# api/app/services/timeline_phases.py
def compute_phase_boundaries(game_start, has_overtime=False):
    """
    Returns dict of phase -> (start_time, end_time)
    NBA timing: 4 × ~18.75min quarters + 15min halftime
    """
    boundaries = {
        "pregame": (game_start - 2h, game_start),
        "q1": (game_start, game_start + Q_REAL),
        "q2": (q1_end, q1_end + Q_REAL),
        "halftime": (q2_end, q2_end + HALFTIME_REAL),
        "q3": (halftime_end, halftime_end + Q_REAL),
        "q4": (q3_end, q3_end + Q_REAL),
        # OT periods if has_overtime...
        "postgame": (game_end, game_end + 2h),
    }
    return boundaries
```

League-aware boundaries are also available via `compute_league_phase_boundaries()` for NCAAB (halves) and NHL (periods).

---

### Step 1: Build PBP Events

Each PBP event is assigned a phase from its `quarter` field and a sort key from the game clock.

```python
# api/app/services/timeline_events.py
def build_pbp_events(plays, game_start):
    for play in plays:
        phase = nba_phase_for_quarter(play.quarter)  # q1, q2, ...
        clock_seconds = parse_clock_to_seconds(play.game_clock)
        intra_phase_order = 720 - clock_seconds  # inverted clock
        synthetic_ts = quarter_start + scaled_elapsed
        yield (synthetic_ts, {
            "event_type": "pbp",
            "phase": phase,
            "intra_phase_order": intra_phase_order,
            "play_index": play.play_index,
            ...
        })
```

**Output:** List of `(timestamp, event_payload)` tuples.

---

### Step 2: Build Social Events

Social posts are assigned phases based on `posted_at` relative to phase boundaries. Roles are assigned by heuristic pattern matching.

```python
# api/app/services/social_events.py
def build_social_events(posts, phase_boundaries, ...):
    for post in posts:
        phase = assign_phase_from_time(post.posted_at, phase_boundaries)
        role = classify_role(post.text)  # hype, reaction, momentum, etc.
        intra_order = (post.posted_at - phase_start).total_seconds()
        yield (post.posted_at, {
            "event_type": "tweet",
            "phase": phase,
            "intra_phase_order": intra_order,
            "role": role,
            ...
        })
```

Social data is **optional**. An empty list is valid and expected for leagues without social scraping.

---

### Step 3: Build Odds Events

Odds events are built from `SportsGameOdds` rows. All odds events are assigned `phase="pregame"`.

```python
# api/app/services/odds_events.py
def build_odds_events(odds, game_start, phase_boundaries):
    book = select_preferred_book(odds)  # fanduel > draftkings > betmgm > caesars
    # Up to 3 events:
    # 1. opening_line  — earliest observed_at
    # 2. closing_line   — latest closing observed_at
    # 3. line_movement  — only if significant deltas detected
    return events  # list of (timestamp, event_payload) tuples
```

Movement thresholds: spread >= 1.0 pt, total >= 1.0 pt, moneyline >= 20 cents.

Odds data is **optional**. Zero odds rows produces zero odds events.

---

### Step 4: Merge Events by Phase

Combine all event sources using **phase-first ordering**.

```python
# api/app/services/timeline_events.py
def merge_timeline_events(pbp_events, social_events, odds_events=()):
    merged = list(pbp_events) + list(social_events) + list(odds_events)

    def sort_key(item):
        _, payload = item
        return (
            PHASE_ORDER[payload["phase"]],     # 1. Phase order (primary)
            payload["intra_phase_order"],       # 2. Progress within phase
            EVENT_TYPE_ORDER[payload["event_type"]],  # 3. Type tiebreaker
            payload.get("play_index", 0),       # 4. PBP stability
        )

    return [payload for _, payload in sorted(merged, key=sort_key)]
```

**Event type tiebreaker:** `pbp=0, odds=1, tweet=2`. At the same phase and intra-phase position, PBP events appear first, then odds, then tweets.

---

## Forbidden Patterns

### Global Timestamp Sort

```python
# FORBIDDEN: Do not do this
all_events.sort(key=lambda e: e.timestamp)  # NO
```

**Why:** Timestamps are approximate. Phase ordering is the source of truth.

### Interleave Without Phase Assignment

```python
# FORBIDDEN: Merging without explicit phases
merged = merge_by_time(pbp, social, odds)  # NO
```

**Why:** This hides the phase assignment logic. Phases must be explicit and inspectable.

---

## Guarantees

| Guarantee | Description |
|-----------|-------------|
| **Phase integrity** | All Q1 events appear before all Q2 events. Always. |
| **Determinism** | Same inputs → same output. No randomness. |
| **Explainability** | Every event's position can be explained by its phase + sort key. |
| **Inspectability** | The `phase` field is visible in output for debugging. |
| **Graceful degradation** | Timeline works with PBP alone. Social and odds are optional. |

---

## Visualization

```
INPUT:                          ASSEMBLY:                       OUTPUT:

┌─────────────┐                 ┌──────────────┐                ┌─────────────────┐
│ PBP Events  │──► Assign ──►  │   pregame    │                │ [pregame]       │
│ (by quarter)│    Phase        │   ┌──────┐   │                │   Odds: open    │
└─────────────┘                 │   │odds  │   │                │   Odds: close   │
                                │   │social│   │                │   Tweet: hype   │
┌─────────────┐                 │   └──────┘   │  Sort within   ├─────────────────┤
│ Social Posts│──► Assign ──►   │      q1      │ ────────────►  │ [q1]            │
│ (by time)   │    Phase        │   ┌────┐     │                │   PBP: tip-off  │
└─────────────┘                 │   │pbp │     │                │   PBP: bucket   │
                                │   │pbp │     │                │   Tweet: react  │
┌─────────────┐                 │   │soc │     │                │   PBP: foul     │
│ Odds Rows   │──► All to ──►  │   │pbp │     │                ├─────────────────┤
│ (pregame)   │    pregame      │   └────┘     │                │ [q2]            │
└─────────────┘                 ├──────────────┤                │   ...           │
                                │      q2      │                └─────────────────┘
                                │     ...      │
                                └──────────────┘
```

---

## Validation

Assembled timelines are validated before persistence. See [Timeline Validation](timeline-validation.md) for the full validation spec (6 critical checks, 4 warning checks).

---

## Related Modules

| Module | Purpose |
|--------|---------|
| `timeline_generator.py` | Orchestration: fetch data, build events, merge, validate, persist |
| `timeline_events.py` | PBP event building and `merge_timeline_events()` |
| `social_events.py` | Social post processing, role assignment |
| `odds_events.py` | Odds event processing, book selection, movement detection |
| `timeline_phases.py` | Phase boundaries and timing calculations |
| `timeline_types.py` | Constants (`PHASE_ORDER`, timing), data classes, exceptions |
| `timeline_validation.py` | Validation rules (C1-C6 critical, W1-W4 warnings) |

---

## Changelog

| Date | Change |
|------|--------|
| 2026-02-11 | Rewritten: added odds as third source, multi-league PHASE_ORDER, updated merge pseudocode and visualization. Aligned with implementation. |
| 2026-01-14 | Initial assembly recipe defined |
