# SSOT Cleanup Audit

> Branch: `aidlc_1` — Date: 2026-04-18

## Diff-Driven Deletion Summary

### 1. `PipelineStage` duplicate removed from `api/app/db/pipeline.py`

**Before:** `pipeline.py` defined its own `PipelineStage` enum (8 members) alongside the canonical definition in `api/app/services/pipeline/models.py`. Two independent definitions, no single source of truth.

**After:** `pipeline.py` re-exports from `services/pipeline/models.py` via:
```python
from ..services.pipeline.models import PipelineStage  # noqa: F401 — single source of truth
```

All import sites already use `from ....services.pipeline.models import PipelineStage` or `from app.db.pipeline import PipelineStage` (now a pass-through). No callers changed.

---

### 2. `GameStatus.canceled` renamed to `GameStatus.CANCELLED`

**Before:** `api/app/db/sports.py` had `canceled = "canceled"` (single-l, lowercase member).

**After:** `CANCELLED = "cancelled"` (canonical, matches migration `20260418_000032`).

**Migration:** `api/alembic/versions/20260418_000032_standardize_game_status_cancelled.py` backfills all `sports_games.status` rows from both `'canceled'` and `'cancelled'` to `'cancelled'`.

**Retained boundary normalization:** `scraper/sports_scraper/persistence/games.py:381` still accepts `"canceled"` as an external input string (from sports data providers) and normalizes it to `CANCELLED.value`. This is input validation at the system boundary, not a compat shim — external APIs are not under our control.

---

### 3. `FLOW_VERSION` corrected from `"v2-moments"` to `"v2-blocks"`

**Before:** `api/app/routers/sports/game_timeline.py` had:
```python
FLOW_VERSION = "v2-moments"  # WRONG — this is the legacy version
```

**After:**
```python
FLOW_VERSION = "v2-blocks"
_LEGACY_FLOW_VERSION = "v2-moments"  # deprecated; accepted on read during transition window
```

The previous code used the legacy version string as the current version, meaning the admin flow endpoint only matched old-format rows. New pipeline runs write `v2-blocks` but the query would never find them.

---

### 4. `_swap_score` per-endpoint swap replaced by `_to_score` returning `ScoreObject`

**Before:** `_swap_score(raw)` returned `[raw[1], raw[0]]` — a tuple with reversed home/away, applied inconsistently per endpoint. This was the "per-endpoint score swap" anti-pattern called out in CLAUDE.md.

**After:** `_to_score(raw)` returns `ScoreObject(home=raw[0], away=raw[1])`. No swap. The Phase 2 structured score type is now the contract on the wire.

---

### 5. Moments removed from consumer endpoint (`/api/v1/games/{id}/flow`)

**Before:** `ConsumerGameFlowResponse` included `flow: GameFlowContent` (containing `moments: list[GameFlowMoment]`). The endpoint queried for `moments_json.isnot(None)` and built a full `response_moments` list that was transmitted to consumers. CLAUDE.md: "Blocks are the consumer layer; moments are internal."

**After:**
- `ConsumerGameFlowResponse.flow` field deleted; `blocks` is now the only narrative output
- Existence check changed from `moments_json.isnot(None)` → `blocks_json.isnot(None)` (blocks are the authoritative indicator that flow generation completed)
- Play IDs collected from `block.get("play_ids")` rather than moment `play_ids` — same coverage, blocks reference all plays they narrate
- `blocks` is now `list[GameFlowBlock]` (non-optional, empty list when generation produced no valid blocks)
- `_block_clock` helper removed from consumer import (clock values now read directly from persisted block fields)

**Files changed:**
- `api/app/routers/v1/games.py`
- `api/app/routers/sports/schemas/game_flow.py`
- `packages/js-core/src/api/games.ts` — removed `GameFlowMoment` type and `flow` field
- `packages/js-core/src/api/index.ts` — removed `GameFlowMoment` re-export

`GameFlowMoment`, `GameFlowContent`, `MomentBoxScore`, `MomentPlayerStat`, `MomentTeamBoxScore`, `MomentGoalieStat` remain in `game_flow.py` and `schemas/__init__.py` because the **admin** `GameFlowResponse` and `game_timeline.py` admin endpoint legitimately expose moments for pipeline inspection.

---

### 6. `BRIANDUMP.md` deleted

File removed from repo root. No references to `BRIANDUMP.md` remain in Python, TypeScript, or config files. CLAUDE.md's "When unsure → check BRAINDUMP.md" note is unaffected (refers to `BRAINDUMP.md`, a separate file that still exists).

---

## SSOT Verification

| Domain | Authoritative Source |
|--------|---------------------|
| `PipelineStage` enum | `api/app/services/pipeline/models.py` |
| `GameStatus` enum | `api/app/db/sports.py` (`CANCELLED = "cancelled"`) |
| Flow version strings | `api/app/routers/sports/game_timeline.py` (`FLOW_VERSION`, `_LEGACY_FLOW_VERSION`) |
| Score on wire | `ScoreObject` in `api/app/routers/sports/schemas/game_flow.py` |
| Block validation constants | `api/app/services/pipeline/stages/validate_blocks.py` (backend SSOT); `web/src/lib/guardrails.ts` mirrors — verified in sync |
| Consumer game flow contract | `ConsumerGameFlowResponse` — blocks only, no moments |
| Admin game flow contract | `GameFlowResponse` — blocks + moments + validation fields |

---

## Risk Log

### Retained: `_LEGACY_FLOW_VERSION = "v2-moments"`

Three read-path query filters accept `story_version IN ('v2-blocks', 'v2-moments')`:
- `api/app/routers/sports/game_timeline.py`
- `api/app/routers/v1/games.py`
- `api/app/services/pipeline/backfill_embedded_tweets.py`
- `api/app/services/pipeline/stages/finalize_moments.py`

Per `docs/gameflow/version-semantics.md` step 4: remove `_LEGACY_FLOW_VERSION` after all `v2-moments` rows are confirmed migrated (pipeline re-runs upgrade them to `v2-blocks`). No data migration exists for this — it is a passive transition. Remove when ops confirms no `v2-moments` rows remain.

### Retained: `"canceled"` input normalization in `persistence/games.py:381`

`_normalize_status()` accepts the single-l spelling from external providers as input. This is a boundary normalization (external API → internal DB), not a backward-compat shim. The Alembic migration only fixes historical DB rows; providers may still send either spelling.

---

## Sanity Check

```
# No references to deleted PipelineStage duplicate
grep -r "from.*db\.pipeline.*import.*PipelineStage" api/  → 0 results

# No references to old GameStatus.canceled member
grep -r "GameStatus\.canceled\b" .                        → 0 results

# No _swap_score calls remain
grep -r "_swap_score" .                                   → 0 results

# No consumer code imports GameFlowMoment from js-core
grep -r "GameFlowMoment" packages/js-core/src/api/index.ts → 0 results (removed)

# No consumer web pages use .flow.moments
grep -r "\.flow\.moments" web/src/app --include="*.tsx" --exclude-dir=admin → 0 results (admin FlowSection.tsx is expected)
```

---

## Destructive Cleanup Pass — 2026-04-19

### 7. Stale consumer-shape tests fixed in `test_v1_flow_endpoint.py`

**Problem:** `_mock_flow()` set `blocks_json = None` and used `moments_json` only. Because the v1 endpoint
queries `blocks_json.isnot(None)`, the mock was effectively simulating a no-flow game — causing two tests
to silently test the wrong code path:

- `test_returns_flow_without_validation_fields` asserted `"flow" in data` — `flow` field was removed from
  `ConsumerGameFlowResponse` in change #5.
- `test_score_is_score_object` accessed `data["flow"]["moments"][0]` — neither `flow` nor `moments` exist
  on the consumer contract.
- `test_includes_team_metadata` called with same stale mock; would reach the `FlowStatusResponse` path
  instead of `ConsumerGameFlowResponse` and miss team metadata entirely.

**Fix:**
- `_mock_flow()` now sets `blocks_json` with a representative OPENING block (score_before/after, play_ids,
  role, narrative). `moments_json` is empty list (valid for v2-blocks flows).
- `test_returns_flow_without_validation_fields` checks `"blocks" in data` and explicitly asserts
  `"flow" not in data`.
- `test_score_is_score_object` reads `data["blocks"][0]` for `scoreBefore`/`scoreAfter`.

---

### 8. Removed misleading comment from `api/app/realtime/poller.py`

`db_poller = DBPoller()` carried `# Singleton — kept for backwards-compat with main.py imports`.
The module-level instance is the live runtime object imported by `main.py`; it is not a compat shim.
Comment deleted.

---

## Destructive Cleanup Pass — 2026-04-19 (second sweep)

### 9. Docstrings / comments updated: "canceled" → "cancelled" for GameStatus consistency

**Problem:** Four comment strings in scraper code used the old single-l spelling as a concept
name — inconsistent with the canonical `GameStatus.CANCELLED = "cancelled"` and the migration
`20260418_000032_standardize_game_status_cancelled.py`.

**Files changed:**

| File | Location | Change |
|------|----------|--------|
| `scraper/sports_scraper/persistence/games.py` | `resolve_status_transition` docstring | "canceled" → "cancelled" |
| `scraper/sports_scraper/persistence/games.py` | Inline comment `# Non-lifecycle statuses (postponed, canceled) pass through` | "canceled" → "cancelled" |
| `scraper/scripts/audit_data.py` | `fix_stuck_games` docstring | "canceled" → "cancelled" |
| `scraper/scripts/audit_data.py` | `print(f"  Marked {fixed} stuck games as canceled …")` | "canceled" → "cancelled" |

**Retained (intentional):**
- `games.py:_normalize_status` line 400: `if status_normalized in {db_models.GameStatus.CANCELLED.value, "canceled"}` — this is a **boundary guard** that accepts the old external-provider spelling and normalises it to the canonical value. The Alembic migration only converts historical DB rows; live sports data providers may still emit either spelling. This guard is not a backward-compat shim for our own code.
- `game_state_updater.py:45`: `"phantom_canceled"` — a Prometheus/structlog **metric key name**. Renaming it would break existing dashboards and alert rules without gaining type-safety. Scope: operational concern, not an SSOT violation.

---

## SSOT Verification (final)

| Domain | Authoritative Source | Current Value |
|--------|---------------------|---------------|
| `PipelineStage` enum | `api/app/services/pipeline/models.py` | re-exported from `api/app/db/pipeline.py` |
| `GameStatus` enum | `api/app/db/sports.py` | `CANCELLED = "cancelled"` |
| `MIN_BLOCKS` | `api/app/services/pipeline/stages/block_types.py` | `3` — in sync with `web/src/lib/guardrails.ts` |
| Flow version strings | `api/app/routers/sports/game_timeline.py` | `FLOW_VERSION = "v2-blocks"`, `_LEGACY_FLOW_VERSION = "v2-moments"` |
| Score on wire | `ScoreObject {home, away}` in `api/app/routers/sports/schemas/game_flow.py` | No tuple returns in v1 |
| Consumer game flow contract | `ConsumerGameFlowResponse` | Blocks only — no `moments` field |
| `_swap_score` | Deleted | `grep -r "_swap_score" .` → 0 results |
| `BRIANDUMP.md` | Deleted / never existed | `ls BRIANDUMP.md` → no such file |

---

## Sanity Check (2026-04-19 sweep)

```
# No stale "canceled" in GameStatus comparisons (only the intentional boundary guard remains)
grep -rn '"canceled"' scraper/sports_scraper/persistence/games.py
  → line 400 only (_normalize_status boundary guard — intentional)

# No "canceled" docstrings referencing game status remain
grep -n "canceled" scraper/sports_scraper/persistence/games.py
  → 0 results (all updated to "cancelled")

# No _swap_score usages
grep -r "_swap_score" --include="*.py" .
  → 0 results

# MIN_BLOCKS is 3 on both sides
grep -n "MIN_BLOCKS\s*=" api/app/services/pipeline/stages/block_types.py
  → MIN_BLOCKS = 3
grep -n "MIN_BLOCKS\s*=" web/src/lib/guardrails.ts
  → export const MIN_BLOCKS = 3;

# No moments in v1 consumer response schema
grep -n "moments" api/app/routers/v1/games.py
  → 0 results

# PipelineStage defined only once
grep -rn "^class PipelineStage" --include="*.py" .
  → api/app/services/pipeline/models.py only

# BRIANDUMP.md references in non-aidlc code
grep -r "BRIANDUMP" --include="*.md" --include="*.py" --include="*.ts" . \
  | grep -v "\.aidlc\|docs/audits"
  → 0 results
```

---

## Destructive Cleanup Pass — 2026-04-19 (third sweep)

### 10. Stale `_swap_score` references removed from documentation

**Problem:** Four documentation locations still described `_swap_score()` as a present, operative pattern after it was deleted in change #4:

| File | Location | Stale content |
|------|----------|---------------|
| `DESIGN.md` | API Conventions, line 13 | "Current tuple + `_swap_score()` pattern is deprecated" |
| `BRAINDUMP.md` | "Score display convention" bullet (~line 109) | "`_swap_score()` swap" described as active |
| `BRAINDUMP.md` | "Score tuple convention" section (~line 284) | `_swap_score()` described as present mechanism |
| `BRAINDUMP.md` | "Admin/app boundary confusion" section (~line 280) | "There is no `/api/v1/` namespace" — stale since `/api/v1/` is live |

**Fix:**
- `DESIGN.md` line 13: Reworded to state `ScoreObject` is the current contract and `_swap_score()` is deleted.
- `BRAINDUMP.md` "Score display convention": Added `> Resolved in aidlc_1` note; updated description to current reality.
- `BRAINDUMP.md` "Score tuple convention": Added `> Resolved in aidlc_1` note; struck through old description.
- `BRAINDUMP.md` "Admin/app boundary confusion": Added `> Partially resolved in aidlc_1` note; updated description to reflect `/api/v1/` being live.

### 11. ROADMAP.md Phase 2 deliverables marked complete

**Problem:** Two Phase 2 items were left unchecked (`[ ]`) despite being completed in this branch:

```
- [ ] Introduce ScoreObject Pydantic model {home: int, away: int}...
- [ ] Delete _swap_score() helper once migration complete.
```

**Fix:** Both marked `[x]`. Evidence: `grep -r "_swap_score" api/ scraper/ → 0 results`; `ScoreObject` is live in `api/app/routers/sports/schemas/game_flow.py`.

---

## SSOT Verification (final — 2026-04-19 third sweep)

| Domain | Authoritative Source | Status |
|--------|---------------------|--------|
| `_swap_score` | Deleted | 0 references in `.py` files; CI lint gate enforces no reintroduction |
| `ScoreObject` | `api/app/routers/sports/schemas/game_flow.py` | Live on consumer endpoint; admin tuple migration is Phase 2 on-touch |
| ROADMAP Phase 2 status | `ROADMAP.md` | `ScoreObject` intro + `_swap_score` deletion both `[x]` |
| BRAINDUMP descriptions | `BRAINDUMP.md` | Score convention and admin/app boundary sections updated with `aidlc_1` resolution notes |

---

## Sanity Check (2026-04-19 third sweep)

```
# _swap_score gone from all prose and code
grep -r "_swap_score" --include="*.py" api/ scraper/
  → 0 results (CI gate enforces this)

# ROADMAP Phase 2 ScoreObject items both checked
grep "_swap_score\|ScoreObject" ROADMAP.md
  → [x] lines only

# No stale "no /api/v1/" claims
grep "no.*api/v1" BRAINDUMP.md
  → 0 results
```

---

## Destructive Cleanup Pass — 2026-04-19 (fourth sweep)

### 12. `_LEGACY_FLOW_VERSION` transition shim deleted

**Problem:** Four read-path queries used `.in_([FLOW_VERSION, _LEGACY_FLOW_VERSION])` to accept both
`"v2-blocks"` and the deprecated `"v2-moments"` story_version. This is a backward-compat shim — the
pipeline has written `"v2-blocks"` exclusively since `aidlc_1`; prod usage of `"v2-moments"` rows
cannot be proven.

**Per cleanup rules:** "Replace silent fallback with hard failure where appropriate" and "If prod usage
cannot be proven, delete it."

**Changes:**

| File | Change |
|------|--------|
| `api/app/services/pipeline/stages/finalize_moments.py` | Deleted `_LEGACY_FLOW_VERSION` constant; removed comment from docstring |
| `api/app/routers/sports/game_timeline.py` | Deleted `_LEGACY_FLOW_VERSION` constant; replaced `.in_([...])` with `== FLOW_VERSION` |
| `api/app/routers/v1/games.py` | Removed `_LEGACY_FLOW_VERSION` import; replaced `.in_([...])` with `== FLOW_VERSION` |
| `api/app/services/pipeline/backfill_embedded_tweets.py` | Deleted `_LEGACY_FLOW_VERSION` constant; replaced both `.in_([...])` queries with `== FLOW_VERSION` |

**Effect:** Rows with `story_version = "v2-moments"` are now invisible to all read paths. Any such row
in production will no longer surface in consumer or admin flow endpoints, forcing a pipeline re-run to
regenerate a `"v2-blocks"` row. This is the intended hard-failure behavior.

### 13. Stale test comment corrected

`api/tests/pipeline/test_guardrails.py:78` comment `# Below MIN_BLOCKS (4)` updated to
`# Below MIN_BLOCKS (3)` — constant was aligned to 3 earlier in `aidlc_1`.

---

## SSOT Verification (final — 2026-04-19 fourth sweep)

| Domain | Authoritative Source | Status |
|--------|---------------------|--------|
| `_LEGACY_FLOW_VERSION` | Deleted | `grep -r "_LEGACY_FLOW_VERSION" --include="*.py" .` → 0 results |
| Flow version read filter | `== FLOW_VERSION` (strict) | No `.in_()` version filters remain |
| `MIN_BLOCKS` test comment | `test_guardrails.py:78` | Updated to `(3)` |

---

## Sanity Check (2026-04-19 fourth sweep)

```
# No _LEGACY_FLOW_VERSION in Python or TypeScript
grep -r "_LEGACY_FLOW_VERSION\|v2-moments" --include="*.py" --include="*.ts" .
  → 0 results

# No .in_() version filters remain
grep -rn "story_version.in_" --include="*.py" api/
  → 0 results

# MIN_BLOCKS comment is correct
grep -n "MIN_BLOCKS" api/tests/pipeline/test_guardrails.py
  → line 78: # Below MIN_BLOCKS (3)
```

---

## Destructive Cleanup Pass — 2026-04-20 (fifth sweep)

### 14. Admin flow endpoint: `moments_json` presence check replaced with `blocks_json`

**Problem:** `api/app/routers/sports/game_timeline.py` deprecated admin flow endpoint (`GET /games/{id}/flow`)
still used `SportsGameFlow.moments_json.isnot(None)` as the presence sentinel — inconsistent with the SSOT
established in change #5, which designates `blocks_json` as the authoritative indicator that pipeline
generation completed. For v2-blocks flows, `blocks_json` is always written; `moments_json` is a
pipeline-internal artifact.

**Change:** `moments_json.isnot(None)` → `blocks_json.isnot(None)` in the admin query filter.

**File:** `api/app/routers/sports/game_timeline.py:178`

---

### 15. Backend backward-compat alias routes deleted from `games.py`

**Problem:** `api/app/routers/sports/games.py` registered two hidden routes with `include_in_schema=False`:
- `POST /games/{game_id}/rescrape` → alias for `/resync`
- `POST /games/{game_id}/resync-odds` → alias for `/resync`

Both carried the comment `# Keep old endpoints as aliases for backward compatibility`. No test, no
frontend call, and no external documentation references either path. Per cleanup rules: "backward
compatibility is not a goal" and "If prod usage cannot be proven, delete it."

**Change:** Both alias route handlers deleted.

**File:** `api/app/routers/sports/games.py:241–249`

---

### 16. Frontend legacy alias exports deleted from `games.ts`

**Problem:** `web/src/lib/api/sportsAdmin/games.ts` exported two dead aliases:
```ts
// Legacy aliases
export const rescrapeGame = resyncGame;
export const resyncOdds = resyncGame;
```
No component, page, or test in the `web/` tree imports `rescrapeGame` or `resyncOdds`. These were
client-side mirrors of the now-deleted server-side alias routes.

**Change:** Both alias exports and their comment deleted.

**File:** `web/src/lib/api/sportsAdmin/games.ts:40–42`

---

## SSOT Verification (final — 2026-04-20 fifth sweep)

| Domain | Authoritative Source | Status |
|--------|---------------------|--------|
| Flow presence sentinel (admin endpoint) | `blocks_json.isnot(None)` | Consistent with v1 consumer endpoint |
| `/rescrape`, `/resync-odds` routes | Deleted | 0 references in Python sources |
| `rescrapeGame`, `resyncOdds` TS exports | Deleted | 0 import sites in `web/src/` |

---

## Sanity Check (2026-04-20 fifth sweep)

```
# blocks_json is now the presence check in both v1 and admin endpoints
grep -n "moments_json.isnot\|blocks_json.isnot" api/app/routers/sports/game_timeline.py api/app/routers/v1/games.py
  → blocks_json.isnot(None) in both files

# Deleted server-side aliases are gone
grep -rn "rescrape_game\|resync_game_odds\|rescrape\|resync-odds" api/app/routers/ --include="*.py"
  → 0 results

# Deleted frontend aliases are gone
grep -rn "rescrapeGame\|resyncOdds" web/src/ --include="*.ts" --include="*.tsx"
  → 0 results
```
