# PBP Assumptions for Game Flow

This document defines the explicit guarantees that Game Flow assumes about Play-by-Play (PBP) data. It is derived from a comprehensive audit of existing schemas, ingestion paths, and data samples.

**Authoritative Reference:** [Game Flow Contract](contract.md)

---

## 1. Overview

Game Flow requires PBP data that supports:
- Unique, stable play identification
- Total ordering within a game
- Score state at any point in the game
- Period/quarter context for clock interpretation

This audit examines whether current PBP infrastructure meets these requirements and documents the conditions under which Game Flow can operate correctly.

---

## 2. PBP Schema Inventory

### 2.1 Primary Storage: `sports_game_plays`

**Location:** `api/app/db/sports.py` (ORM model), `api/alembic/versions/20260218_000001_baseline_squash.py` (DDL)

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| `id` | SERIAL | No | Database primary key |
| `game_id` | INTEGER FK | No | References `sports_games.id` |
| `play_index` | INTEGER | No | Ordering key within game |
| `quarter` | INTEGER | Yes | Period number (1-4 regulation, 5+ OT) |
| `game_clock` | VARCHAR(10) | Yes | Remaining time in period |
| `play_type` | VARCHAR(50) | Yes | Event type (league-specific) |
| `team_id` | INTEGER FK | Yes | Resolved team reference |
| `player_id` | VARCHAR(100) | Yes | External player identifier |
| `player_name` | VARCHAR(200) | Yes | Player name from source |
| `description` | TEXT | Yes | Human-readable event text |
| `home_score` | INTEGER | Yes | Score at this play |
| `away_score` | INTEGER | Yes | Score at this play |
| `raw_data` | JSONB | No | Complete source payload |
| `created_at` | TIMESTAMPTZ | No | Record creation time |
| `updated_at` | TIMESTAMPTZ | No | Last update time |

**Constraints:**
- UNIQUE on `(game_id, play_index)` - enforces ordering uniqueness

**Sports Coverage:** NBA, NHL, NCAAB, MLB

### 2.2 Normalized Input Model: `NormalizedPlay`

**Location:** `scraper/sports_scraper/models/schemas.py`

Pydantic model used during ingestion. Fields mirror storage schema.

### 2.3 Snapshot Storage: `sports_pbp_snapshots`

**Location:** Defined in the baseline Alembic migration (`api/alembic/versions/20260218_000001_baseline_squash.py`)

Stores PBP at different processing stages (raw, normalized, resolved) for auditability. Includes `resolution_stats` tracking:
- `teams_unresolved`
- `players_unresolved`
- `plays_without_score`
- `clock_parse_failures`

---

## 3. Field Coverage vs Game Flow Requirements

| Game Flow Field | PBP Source Field | Exists | Always Present | Derivation Required |
|----------------|------------------|--------|----------------|---------------------|
| `play_ids` | `play_index` | Yes | Yes | No |
| `start_clock` | `game_clock` | Yes | No | No |
| `end_clock` | `game_clock` | Yes | No | No |
| `period` | `quarter` | Yes | No | No |
| `score_before` | `home_score`, `away_score` | Partial | No | Yes |
| `score_after` | `home_score`, `away_score` | Partial | No | Yes |

### 3.1 Play IDs

**Storage:** `play_index` (INTEGER, NOT NULL, UNIQUE per game)

**Generation:**
- NBA Live: `period * 10000 + actionNumber`
- NHL API: `period * 10000 + sortOrder`
- Sports Reference: Sequential counter in HTML row order (0, 1, 2, ...)

**Stability:** Play indices are stable within a single ingestion. Re-ingestion may produce different indices if source data changes.

### 3.2 Score Fields

**Critical Finding:** Scores represent the state AFTER the play, not before.

**NBA Live API:**
- `scoreHome` and `scoreAway` present on every action
- Cumulative (score after play completes)

**NHL API:**
- `homeScore` and `awayScore` present ONLY on goal events
- Non-goal plays have NULL scores

**Sports Reference:**
- Score column parsed when present
- Many rows lack score data
- Score column shows cumulative score at that point

**Implication for Game Flow:**
- `score_before` must be derived from the previous play's score
- `score_after` is the current play's stored score
- First play of game requires assumption (0-0 baseline)

### 3.3 Clock Fields

**Storage:** `game_clock` (VARCHAR(10), NULLABLE)

**Format Variations:**
- NBA Live: Original `PT{M}M{S}S` parsed to `M:SS` (e.g., "11:22")
- NHL API: `timeRemaining` as `MM:SS` (e.g., "16:00")
- Sports Reference: Raw text from HTML (e.g., "11:45", "5:30.0")

**Semantics:** All sources use countdown format (time remaining in period).

---

## 4. Clock & Time Semantics

### 4.1 Clock Formats in Use

| Source | Format | Example | Parsing |
|--------|--------|---------|---------|
| NBA Live | ISO-8601 duration | `PT11M22.00S` | Parsed to `M:SS` |
| NHL API | MM:SS | `16:00` | Used directly |
| Sports Reference (NBA) | MM:SS or M:SS.x | `11:45`, `5:30.0` | Preserved as-is |
| Sports Reference (NHL) | MM:SS | `20:00` | Preserved as-is |

### 4.2 Clock Direction

All sources use **countdown** (time remaining in period):
- Period starts at maximum (12:00 for NBA quarters, 20:00 for NHL periods)
- Period ends at 0:00

### 4.3 Period Boundaries

- Clock resets at each period start
- NBA: 12:00 per quarter (4 quarters regulation, 5-minute OT)
- NHL: 20:00 per period (3 periods regulation, 5-minute OT, shootout)
- NCAAB: 20:00 per half (2 halves regulation)

### 4.4 Overtime Representation

| League | Regulation Periods | OT Encoding |
|--------|-------------------|-------------|
| NBA | 1-4 | 5, 6, 7... |
| NHL | 1-3 | 4 (OT), 5 (shootout in some sources) |
| NCAAB | 1-2 | 3, 4, 5... |

### 4.5 Clock Ordering Guarantees

**Question:** Can `(period, clock)` be used as a strict ordering key?

**Answer:** No, not reliably.

**Reasons:**
1. Multiple plays can occur at the same game clock (simultaneous events)
2. Clock granularity varies (some sources include tenths, others do not)
3. Some plays lack clock data entirely

**Ordering authority:** `play_index` is the canonical ordering key, not clock.

**Simultaneous plays:** Multiple plays sharing identical clock values is expected and valid. Each play has a unique `play_index`, so ordering remains unambiguous. Game Flow must not attempt to disambiguate via clock.

**Clock optionality:** Game Flow does not require clock values to exist for every play. When present, clocks are metadata only and do not participate in ordering or structural decisions.

---

## 5. Play ID Stability Analysis

### 5.1 Generation Methods

**NBA Live Feed:**
```python
play_index = period * 10000 + actionNumber
```
- `actionNumber` is assigned by NBA API
- Deterministic for a given API response
- Stable across repeated fetches of same game state

**NHL API:**
```python
play_index = period * 10000 + sortOrder
```
- `sortOrder` is assigned by NHL API
- Deterministic for a given API response
- Stable across repeated fetches of same game state

**Sports Reference:**
```python
play_index = sequential_counter  # 0, 1, 2, ...
```
- Assigned in HTML row order during scraping
- Deterministic for a given HTML page
- May change if source HTML structure changes

### 5.2 Uniqueness

| Scope | Guaranteed |
|-------|------------|
| Within a game | Yes (database constraint) |
| Across games | No (play_index resets per game) |

**Unique identifier for Game Flow:** `(game_id, play_index)` tuple

### 5.3 Stability Across Re-ingestion

**Condition:** Play indices are stable if source data is unchanged.

**Risk:** If a game's PBP is re-scraped and the source has changed (corrections, late additions), play indices may shift.

**Mitigation:** The `raw_data` JSONB field preserves original source identifiers:
- NBA: `sequence` (original `actionNumber`)
- NHL: `sort_order`, `event_id`

### 5.4 Assessment

Play IDs (`play_index`) can be used as durable references **within a single ingestion cycle**. Game Flow should treat play indices as stable for the lifetime of a game's PBP data, but must not assume cross-ingestion stability without raw_data reconciliation.

---

## 6. Score Representation Analysis

### 6.1 Score Presence by Source

| Source | Score on Every Play | Score Semantics |
|--------|---------------------|-----------------|
| NBA Live API | Yes | Cumulative (after play) |
| NHL API | No (goals only) | Cumulative (after goal) |
| Sports Reference (NBA) | Variable | Cumulative (when present) |
| Sports Reference (NHL) | Variable | Cumulative (when present) |

### 6.2 Score Semantics

**Critical:** Stored `home_score` and `away_score` represent the score AFTER the play completes.

This means:
- A scoring play shows the NEW score (including points just scored)
- A non-scoring play shows the SAME score as the previous play (if present) or NULL

### 6.3 Deriving `score_before` and `score_after`

**For NBA Live API (scores always present):**
```
score_before(play[i]) = score_after(play[i-1])  # previous play's score
score_after(play[i]) = (play[i].home_score, play[i].away_score)
score_before(play[0]) = (0, 0)  # game start assumption
```

**For NHL API (scores on goals only):**
```
score_after(play[i]) = most recent non-null score at or before play[i]
score_before(play[i]) = score_after(play[i-1])
```
Requires forward-fill of last known score through non-scoring plays.

### 6.4 Edge Cases

1. **First play of game:** Assume `score_before = (0, 0)`
2. **First play of period:** Inherit score from last play of previous period
3. **OT/Shootout:** Score carries forward from regulation
4. **Missing scores in sequence:** Forward-fill from last known score

### 6.5 Assessment

`score_before` and `score_after` can be reconstructed reliably under these assumptions:
- Scores are cumulative (after play)
- Forward-fill is applied for missing scores
- Game starts at (0, 0)

---

## 7. Known Gaps & Failure Modes

### 7.1 Missing Clock Data

**Symptom:** `game_clock` is NULL

**Frequency:** Tracked in `resolution_stats.clock_missing`

**Sources:**
- Sports Reference parsing failures
- Period-start/period-end events without clock
- Shootout plays (some sources)

**Impact:** Game Flow cannot provide `start_clock`/`end_clock` for affected moments

**Classification:** Requires normalization (fallback to NULL with documented absence)

### 7.2 Missing Score Data

**Symptom:** `home_score` and/or `away_score` is NULL

**Frequency:** Common for NHL (non-goal plays), variable for Sports Reference

**Impact:** `score_before`/`score_after` derivation requires forward-fill

**Classification:** Requires normalization (forward-fill algorithm)

### 7.3 Team Resolution Failures

**Symptom:** `team_id` is NULL but `team_abbreviation` has value

**Example:** "PHX" vs "PHO" for Phoenix Suns

**Impact:** Team attribution unreliable for some plays

**Classification:** Acceptable with documented assumption (use abbreviation as fallback)

### 7.4 Duplicate Play Indices

**Prevented by:** Database UNIQUE constraint on `(game_id, play_index)`

**Risk:** Upsert logic uses `ON CONFLICT DO UPDATE`, so duplicates are overwritten, not rejected

**Classification:** Acceptable (constraint prevents duplicates)

### 7.5 Period Numbering Inconsistencies

**Issue:** Some sources encode shootout as period 4, others as separate shootout marker

**Impact:** Period interpretation varies by source

**Classification:** Acceptable with documented per-source handling

### 7.6 Ordering Assumptions

**Implicit assumption:** `play_index` reflects chronological order

**Verification:** All ingestion paths assign indices in chronological order:
- Live APIs: period * 10000 + sequence preserves chronology
- Sports Reference: HTML row order is chronological

**Classification:** Acceptable (invariant maintained by ingestion)

### 7.7 Late Corrections / Stat Revisions

**Risk:** Source data may be updated after initial ingestion (stat corrections, player attribution fixes)

**Impact:** Re-ingestion may alter play indices or content

**Mitigation:** Raw snapshots preserve original state; re-ingestion is append-only for PBP

**Classification:** Acceptable with snapshot audit trail

---

## 8. PBP Guarantees Required by Game Flow

Game Flow assumes the following conditions are true. Violations of these guarantees will cause incorrect or undefined behavior.

### 8.1 Structural Guarantees

| Guarantee | Condition | Status |
|-----------|-----------|--------|
| **G1** | Every play has a unique identifier within a game | MET via `(game_id, play_index)` constraint |
| **G2** | Plays can be totally ordered within a game by `play_index` | MET via ingestion logic |
| **G3** | `play_index` values are non-negative integers | MET via schema validation |
| **G4** | `play_index` values are consecutive (no gaps) | NOT GUARANTEED - gaps may exist. Game Flow does not rely on continuity, only uniqueness and ordering. |
| **G5** | Every play has `raw_data` containing source event | MET via NOT NULL constraint |

### 8.2 Temporal Guarantees

| Guarantee | Condition | Status |
|-----------|-----------|--------|
| **G6** | `quarter` (period) is present for plays within regulation and OT | MOSTLY MET - some edge cases have NULL |
| **G7** | `game_clock` follows countdown semantics (time remaining) | MET for all sources |
| **G8** | `game_clock` format is parseable to seconds via `parse_clock_to_seconds()` | MOSTLY MET - malformed values return NULL |

### 8.3 Score Guarantees

| Guarantee | Condition | Status |
|-----------|-----------|--------|
| **G9** | `home_score`/`away_score` represent cumulative score AFTER play | MET for all sources |
| **G10** | First play of game has derivable `score_before` of (0, 0) | ASSUMED - not explicitly stored |
| **G11** | Score gaps can be forward-filled without ambiguity | MET via cumulative semantics |

### 8.4 Blocking Issues

| Issue | Description | Blocking? |
|-------|-------------|-----------|
| Play index gaps | `play_index` may have gaps (e.g., 0, 1, 3 with no 2) | NO - Game Flow uses indices as identifiers, not as array positions |
| NULL clock values | Some plays lack `game_clock` | NO - Game Flow treats clock as optional metadata |
| NULL scores | Some plays lack score data | NO - Forward-fill algorithm handles this |

### 8.5 Normalization Requirements (Upstream)

Game Flow assumes the following normalizations have already been applied upstream. **Game Flow does not perform these normalizations itself.** These transformations belong in ingestion or pipeline preparation stages.

1. **Score Forward-Fill:** Propagate last known score to plays with NULL scores
2. **Score Before Derivation:** Compute `score_before` as previous play's `score_after`
3. **Period Validation:** Ensure period values are positive integers where present

---

## 9. Summary

PBP data is **sufficient** to support Game Flow under documented assumptions.

**No blocking issues** prevent implementation.

**Normalization required:**
- Score forward-fill for sources with sparse score data (NHL, Sports Reference)
- `score_before` derivation from sequential play analysis

**Assumptions documented:**
- Play indices are stable within an ingestion cycle
- Scores are cumulative (after play)
- Games start at (0, 0)
- Clock is optional metadata, not required for ordering

Game Flow engineers may rely on this document without additional investigation. Reviewers should challenge specific guarantees if evidence contradicts them.

---

## Document Status

This audit is based on code inspection as of the audit date. Changes to ingestion logic or schema may invalidate specific findings. Re-audit recommended if PBP infrastructure changes significantly.
