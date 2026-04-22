# Code Quality Cleanup Report

**Date:** 2026-04-22  
**Scope:** Full repository — Python (api/, scraper/), TypeScript (web/, packages/)

---

## Dead Code Removed

### `api/app/db/onboarding.py`
- Removed module-level constant `_SESSION_TTL_HOURS = 24`. It was defined but never referenced anywhere in the file or codebase. The TTL is enforced at the application layer, not by this constant.

### `api/app/dependencies/roles.py`
- Removed `_MAGIC_LINK_EXPIRE_MINUTES = 15`, `create_magic_link_token()`, and `decode_magic_link_token()`. These three items were dead code: the magic link flow uses DB-stored SHA-256 hashes (`MagicLinkToken` table) rather than JWTs, so the JWT-based approach was an unused parallel implementation. No import site existed for either function outside of `roles.py` itself.

### `api/app/routers/golf/tournaments.py`
- Removed unused `delete` import from `sqlalchemy`. The `remove_field_player` endpoint uses `await db.delete(row)` (the async ORM session method), not the SQLAlchemy `delete()` statement constructor — making the import unreachable.

---

## Consistency Changes Made

### `api/app/routers/onboarding.py`
- Replaced a local `from datetime import timezone` import inside `_is_session_expired()` with the module-level `UTC` constant already imported at the top of the file. The local import was a stale artifact; `UTC` and `timezone.utc` are equivalent since Python 3.11 and `UTC` was already present.

### `api/app/routers/golf/pools.py`
- Moved `import random` from between third-party imports into the stdlib import block at the top of the file. The misplacement violated PEP 8 import ordering (stdlib → third-party → first-party) and would be flagged by Ruff's `I` (isort) rules.

---

## Files Still Over 500 LOC

The following files exceed 500 lines. Each is noted with a brief justification or a flag for follow-up.

| File | Lines | Status |
|------|-------|--------|
| `api/app/services/pipeline/stages/validate_blocks.py` | 1113 | **Flag.** Largest file in the codebase. Contains 21 validation functions across several distinct concerns (structural, coverage, block-level, moment-level). Prime candidate for splitting into `_structural.py`, `_coverage.py`, and `_block_validators.py`. |
| `api/app/tasks/_training_data.py` | 732 | **Flag.** Dataset assembly logic; a dedicated module for each sport (MLB/NBA/NHL/etc.) would improve navigation. |
| `api/app/routers/golf/pools_admin.py` | 717 | **Flag.** Admin router covering pool CRUD, bucket management, CSV upload, entry management, and state-machine transitions. Consider splitting into `_pools_crud.py`, `_buckets.py`, and `_entries.py`. |
| `api/app/services/pipeline/executor.py` | 605 | **Justified.** Pure orchestration class. All 605 lines coordinate stage execution; extracting sub-stages would not reduce conceptual complexity. |
| `api/app/routers/golf/pools.py` | 604 | **Flag.** Public pool router handling submission, leaderboard, scoring, and field management. Leaderboard/scoring endpoints are good extraction candidates. |
| `api/app/routers/admin/pbp.py` | 584 | **Justified.** PBP inspection router with rich diagnostic output per endpoint. High comment density is intentional (documents wire format). |
| `api/app/routers/auth.py` | 579 | **Justified.** Single-domain router covering all auth flows (signup, login, refresh, magic-link, password reset, account management). The breadth is the feature, not bloat. |
| `api/app/tasks/experiment_tasks.py` | 571 | **Flag.** Complex Celery task with multiple phases. The experiment lifecycle phases could be helper functions in a companion module. |
| `api/app/routers/simulator_mlb.py` | 552 | **Flag.** Four functions, each individually large. The simulation orchestration logic in `run_simulation` (≈200 lines) is a candidate for extraction to `services/simulator_orchestration.py`. |
| `api/app/analytics/core/simulation_engine.py` | 541 | **Flag.** Multi-sport dispatch with per-sport specialization. Already well-commented; splitting by sport would improve discoverability. |
| `api/app/analytics/api/_experiment_routes.py` | 538 | **Flag.** Experiment lifecycle routes mixed with Celery polling. Consider splitting mutation endpoints from read endpoints. |
| `api/app/routers/fairbet/live.py` | 527 | **Flag.** Live-odds orchestration + scraper-control mixed in one file. |
| `api/app/db/sports.py` | 526 | **Justified.** Pure ORM model definitions. Monolithic by design; Alembic autogenerate requires all models visible. |
| `api/app/services/pipeline/stages/guardrails.py` | 521 | **Justified.** Invariant-enforcement stage. Heavy inline documentation is intentional (each invariant references a design principle). |
| `api/app/analytics/datasets/mlb_pa_dataset.py` | 518 | **Justified.** PA-level feature engineering. Complex domain logic without obvious seams. |
| `api/app/services/pipeline/stages/box_score_helpers.py` | 517 | **Flag.** Helper module for two different stages (`box_score_phase` and `validate_blocks`). Should be split by consumer. |
| `api/app/services/pipeline/stages/validate_moments.py` | 514 | **Flag.** Moment-level validation with structural overlap with `validate_blocks.py`. A shared `_validators_common.py` could eliminate ~100 lines of duplication. |
| `api/app/services/pipeline/stages/render_prompts.py` | 510 | **Flag.** Two large functions. `render_game_narrative_prompt` and `render_pbp_prompt` each exceed 200 lines and share no logic — separate files would improve testability. |
| `api/app/routers/fairbet/odds.py` | 509 | **Justified.** Three modes (EV/snapshot, keyset, light) require coordinated branching in a single request handler. The complexity is essential. |

---

## Duplicate Patterns Identified (Not Fixed — No Behavioral Change Risk)

1. **SQLAlchemy eager-load boilerplate.** `_safe_game_load_options()` in `fairbet/odds.py` uses try/except to handle partially-initialized mappers during testing. A similar pattern exists in `fairbet/live.py`. Candidates for a shared `db/query_helpers.py` utility.

2. **`validate_blocks.py` and `validate_moments.py`.** Both implement role-checking, word-count validation, and coverage guards using structurally identical patterns. A `_validators_common.py` with the shared primitives would eliminate ~100 lines of duplication.

3. **Mixed `Mapped`/`Column` style in `golf_pools.py`.** Most columns use the modern `Mapped[T] = mapped_column(...)` style, but several `DateTime` columns still use the legacy `Column(DateTime(...))` form. Both work correctly; a full migration to the modern style would improve consistency.

---

## No Behavioral Changes

All edits are pure dead-code removal and import ordering corrections. No logic, no defaults, and no public APIs were modified. The test suite should pass without any changes.
