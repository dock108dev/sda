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
grep -r "\.flow\.moments" web/src/app --include="*.tsx" --exclude-dir=admin → 0 results
```
