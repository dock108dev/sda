# Code Quality Cleanup Report

**Date:** 2026-04-22
**Scope:** files modified/added on the current branch (observability, security
hardening, and SQL-interpolation-linter work).
**Rule:** no behavioral changes; lint/build must still pass.

## Dead code removed

- `api/tests/test_observability.py`: removed a function-local `import json`
  inside `TestPIIRedaction._format` and hoisted it to module-level stdlib
  imports (where the rest of the stdlib imports live).

## Files refactored (cosmetic only)

- `api/main.py`: consolidated two split `from sqlalchemy import …` lines
  (`text` on one line, `func, select` a few lines later) into a single
  ordered import, and re-grouped the third-party block so
  `prometheus_client`, `sqlalchemy`, and `starlette` sit together in stdlib →
  third-party → local order. No runtime change.
- `api/app/db/__init__.py`: moved `logger = logging.getLogger(__name__)`
  out from between the stdlib/third-party imports and the local `from .base
  import Base` block (was triggering PEP 8 E402 "module level import not at
  top of file"). Logger definition now sits with the other module-level state
  after the `TYPE_CHECKING` block. No runtime change.

## Files still over 500 LOC

| File | LOC | Status |
|------|-----|--------|
| `api/main.py` | 533 | **Flagged for follow-up.** Marginally over. Bulk is FastAPI router registration and exception handlers — pure wiring. A clean extraction would move (a) the admin router registrations (~lines 337–433) into `app/routers/admin/__init__.py` and (b) the domain exception handlers (~lines 197–240) into `app/error_handlers.py`. Deferred: structural and touches the import graph, out of scope for a no-behavior cleanup. |

All other audited files are well under 500 LOC:

| File | LOC |
|------|-----|
| `api/app/logging_config.py` | 102 |
| `api/app/middleware/logging.py` | 111 |
| `api/app/realtime/listener.py` | 352 |
| `api/app/routers/golf/pools_helpers.py` | 373 |
| `api/app/routers/onboarding.py` | 300 |
| `api/app/services/audit.py` | 84 |
| `api/app/context.py` | 7 |
| `api/app/metrics.py` | 32 |
| `api/app/middleware/security_headers.py` | 52 |
| `api/app/utils/sanitize.py` | 35 |
| `api/tests/test_observability.py` | 371 |
| `api/tests/test_security_hardening.py` | 218 |
| `scripts/lint_sql_interpolation.py` | 59 |

## Consistency changes

- Normalized `api/main.py` imports to stdlib → third-party → local,
  alphabetical inside the third-party group.
- Removed the misplaced in-function `import json` in `test_observability.py`.
- Relocated misplaced module-level `logger` assignment in
  `api/app/db/__init__.py` so all imports sit together at the top.

## Considered but not changed

- **`_sensitive_query_keys` (middleware/logging.py) vs `_SENSITIVE_EXTRA_FIELDS`
  (logging_config.py)** — flagged as a possible duplicate, but the two sets
  cover different concerns (URL query-string keys vs. log-record `extra`
  attributes) with only partial overlap (`signature`, `auth`, `key` exist only
  in the query-key set; `email` only in the log set). Merging would broaden
  redaction in ways that could hide useful log fields. Left as is.
- **`OrderedDict` in `api/app/realtime/listener.py`** — flagged as potentially
  redundant since `dict` preserves insertion order in Python 3.7+, but
  `_LRUDict.set()` calls `popitem(last=False)` for LRU eviction, which is
  only available on `OrderedDict`. Import is load-bearing.
- **`sanitize.py` lazy `bleach` import** — the module docstring already
  explains why (tests / environments without bleach still import cleanly).
  No additional comment needed.
- **Lazy imports inside `audit._write()` and `main.py` `/ready`,
  `/metrics`** — intentional: circular-import avoidance and lighter startup.
  Left as is.

## Duplicate utilities

None consolidated. The one candidate (the two sensitive-key lists) turned
out to be two different concerns — see "Considered but not changed".

## Verification

- `python -m py_compile api/main.py api/tests/test_observability.py
  api/app/db/__init__.py` — passes.
- All edits are import reorganization with no behavioral effect.
