# Code Quality Cleanup Report

> Run: 2026-04-18. Branch: aidlc_1.

## Summary

| Category | Finding | Action |
|----------|---------|--------|
| Dead import | `HTTPException` unused in `simulator_mlb.py` | Removed |
| Import ordering | `_ALIAS_CFG` constant defined mid-import block in 6 files | Fixed |
| Import ordering | stdlib imports after third-party in `task_control.py` | Fixed |
| Duplicate type | `ScoreObject` defined in both `types.ts` and `api/games.ts` | Consolidated |
| Dead import | `type GuardrailResult` unused in `CollapsedGameFlow.tsx` | Removed |
| Dead code | `formatStatWithDelta()` defined but never called in `CollapsedGameFlow.tsx` | Removed |

---

## Dead Code Removed

### Python

**`api/app/routers/simulator_mlb.py`**
- Removed unused `HTTPException` from `from fastapi import ...` (never raised in this file; all error responses come from called services)

### TypeScript

**`web/src/components/gameflow/CollapsedGameFlow.tsx`**
- Removed `type GuardrailResult` from the `validateBlocksPreRender` import — only the function itself is used
- Removed `formatStatWithDelta()` (lines 79–89) — function was defined but never called; leftover from a prior stat-display iteration

---

## Import Ordering / Consistency Fixed

`_ALIAS_CFG = ConfigDict(...)` is a module-level constant that was being defined mid-import block in several files, interrupting the import section and violating PEP 8. Fixed by moving it after all imports in each file:

| File | Fix |
|------|-----|
| `api/app/routers/simulator_mlb.py` | Moved `_ALIAS_CFG` after all imports |
| `api/app/routers/simulator.py` | Moved `_ALIAS_CFG` after all imports; consolidated split local import groups |
| `api/app/routers/auth.py` | Moved `_ALIAS_CFG` after all imports |
| `api/app/routers/social.py` | Moved `_ALIAS_CFG` after all imports |
| `api/app/routers/sports/scraper_runs.py` | Moved `_ALIAS_CFG` after all imports |
| `api/app/routers/golf/pools_helpers.py` | Moved `_ALIAS_CFG` after all imports |
| `api/app/routers/admin/task_control.py` | Moved stdlib imports (`json`, `datetime`, `Optional`) before third-party; moved `_ALIAS_CFG` after all imports |

Not changed (already correct — `_ALIAS_CFG` was already last):
- `api/app/routers/admin/pbp_models.py`
- `api/app/routers/admin/resolution_models.py`
- `api/app/routers/admin/timeline_models.py`
- `api/app/game_metadata/models.py`

---

## Duplicate Utilities Consolidated

**`packages/js-core/src/api/games.ts`** — `ScoreObject` was defined inline (`{ home: number; away: number }`) duplicating the identical definition already in `packages/js-core/src/types.ts`. Fixed by importing and re-exporting from `types.ts`, making `types.ts` the single source of truth.

The `api/index.ts` re-export of `ScoreObject` from `./games` is preserved — `games.ts` now re-exports it from `types.ts`, so downstream consumers see no change.

---

## Files Still Over 500 LOC (Python)

Test files are excluded — large test files are expected and acceptable.

### Production code flagged for follow-up

| File | Lines | Note |
|------|-------|------|
| `api/app/tasks/_training_data.py` | 732 | ML dataset builders; coherent domain, acceptable |
| `api/app/services/pipeline/stages/validate_blocks.py` | 671 | Validation pipeline; dense by necessity, consider extracting per-check helpers |
| `api/app/services/pipeline/stages/guardrails.py` | 521 | Prompt-layer constants; mostly data, not logic |
| `api/app/services/pipeline/executor.py` | 576 | Orchestrator; could split per-stage dispatch into a helper module |
| `api/app/routers/admin/pbp.py` | 584 | Large admin router; consider grouping by sub-resource |
| `api/app/routers/simulator_mlb.py` | 552 | MLB-specific simulator; coherent |
| `api/app/routers/golf/pools.py` | 547 | Golf pools endpoints; coherent |
| `api/app/routers/fairbet/live.py` | 527 | Live FairBet page; coherent |
| `api/app/routers/auth.py` | 515 | Auth endpoints; coherent |
| `api/app/analytics/core/simulation_engine.py` | 541 | Monte Carlo engine; coherent |
| `api/app/realtime/poller.py` | 517 | DB poller (Phase 5 will replace) |
| `scraper/sports_scraper/golf/client.py` | 650 | Golf API client; coherent |
| `scraper/sports_scraper/golf/pool_scoring.py` | 686 | Scoring logic; coherent |
| `scraper/sports_scraper/normalization/ncaab_teams.py` | 784 | Team name lookup table; data, not logic |
| `scraper/sports_scraper/jobs/scrape_tasks.py` | 577 | Celery task registry; coherent |
| `scraper/sports_scraper/persistence/games.py` | 564 | Game persistence; could split by status-transition vs. CRUD |
| `scraper/sports_scraper/social/team_collector.py` | 523 | Social scraper; coherent |
| `scraper/sports_scraper/live/ncaab_boxscore.py` | 542 | Live boxscore fetcher; coherent |
| `scraper/sports_scraper/persistence/teams.py` | 529 | Team data; coherent |
| `scraper/sports_scraper/services/ncaab_game_ids.py` | 506 | Game ID mapping; coherent |

**Highest-priority refactor candidates** (logic-heavy, not just data):
1. `validate_blocks.py` (671 lines) — each validation check could be its own function module
2. `executor.py` (576 lines) — per-stage dispatch helpers are extractable
3. `persistence/games.py` (564 lines) — status-transition logic could be separated from CRUD

---

## Files Still Over 300 LOC (TypeScript)

Admin pages and type-definition files dominate. Most are acceptable given the domain density.

**Highest-priority refactor candidates:**

| File | Lines | Recommendation |
|------|-------|----------------|
| `web/src/lib/api/analyticsTypes.ts` | 697 | Split by domain (models, experiments, backtests) |
| `web/src/app/admin/analytics/models/page.tsx` | 578 | Extract model-detail panel into a component |
| `web/src/components/admin/RunsDrawer.tsx` | 556 | Extract run-detail and run-list sub-components |
| `web/src/app/admin/control-panel/page.tsx` | 554 | Extract task-row and category-section components |
| `web/src/components/admin/GameDetailModal.tsx` | 543 | Extract per-section sub-components |

All others (type definition files, fairbet pages, golf admin) are acceptable at their current size.

---

## Noqa Suppressions (Intentional — Not Removed)

43 `# noqa: F401` suppressions exist in API and 3 in scraper. All are legitimate:
- ORM model imports for SQLAlchemy relationship/event registration
- Re-exports from sub-modules for public API surface
- Alembic autogenerate model registration

These must remain as-is.

---

## Documented TODOs (Actionable — Not Removed)

Two genuine TODO comments remain and track real architectural work:

1. **`api/app/realtime/poller.py:10`** — Replace DB polling with Postgres `LISTEN/NOTIFY`. Tracked in Phase 5 ROADMAP.
2. **`scraper/sports_scraper/live/nba_advanced.py:10`** — Investigate residential proxy or alternative source for advanced NBA stats (blocked after ~100 req). Tracked in BRAINDUMP.

---

## Intentional Duplication (Not Consolidated)

`api/app/utils/datetime_utils.py` and `scraper/sports_scraper/utils/datetime_utils.py` both define the same 7 datetime helpers. Both files document this as intentional — `api/` and `scraper/` deploy as independent packages. Function names are kept in sync manually.
