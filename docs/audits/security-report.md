# Security Hardening Pass — `flow` branch

**Date:** 2026-05-03
**Branch:** `flow`
**Scope:** Code added or modified on this branch since `main`. The branch's
substantive change is a near-total overhaul of the Game Flow generation
pipeline (boundary detection, archetype classification, per-block evidence
selection, prompt construction, post-LLM validation, v2 schema persistence,
bulk-job orchestration) plus narrow scraper status-transition fixes
(synthetic MLB advisory event filtering, future-tipoff promotion guard,
live → pregame self-heal margin).
**Method:** Walked every changed file's trust boundary; followed user-input
and DB-sourced strings into LLM prompts and HTTP responses; checked the
new alembic migration; confirmed router-level auth dependencies for the
new/modified endpoints; reviewed the bulk Celery job for resource exhaustion
vectors. Hardening was applied in source where safe; remaining items are
listed in §Findings with explicit rationale.

---

## Changes made this pass

- `api/app/routers/v1/games.py` — Added `_consumer_validation_view()` and
  routed the v1 `/api/v1/games/{game_id}/flow` response through it. The
  persisted `validation` JSONB carries a `warnings` list that quotes
  pipeline-internal detail (e.g. `"Block 2: banned phrases detected —
  ['set the tone']"`). Exposing those phrases on the *consumer* endpoint
  both leaks internal validator design and gives an attacker a prompt-
  crafting signal for adversarial input. The admin endpoint at
  `api/app/routers/sports/game_timeline.py` continues to surface the full
  block (intended; admin debugging needs it).
- `api/app/tasks/bulk_flow_generation.py` — Added a hard ceiling
  (`_BULK_JOB_HARD_GAME_CAP = 2000`) on the number of games a single bulk
  Celery job will process. The job record's `max_games` field is admin-
  supplied; a typo or compromised admin key could otherwise queue a
  multi-year window with no upper bound, tying a worker for hours. The
  cap is applied even when `max_games` is None (previously: unbounded).
  Also truncates the per-game `failure_reason` persisted to
  `BulkFlowGenerationJob.errors_json` to 500 chars (`_truncate_failure_reason`)
  so unexpected exception messages — which can carry SQL state strings,
  raw upstream provider responses, or oversized payloads — don't bloat
  the admin UI or smuggle large blobs into the DB.
- `api/app/services/pipeline/stages/render_prompts.py` — Added
  `_sanitize_prompt_string()` (strips ASCII control bytes, CR/LF/tab, and
  the markdown/JSON characters `` ` { } [ ] " ``; bounds length to 80
  chars). Wired it into the per-block and game-flow-pass prompt builders
  for the two trust-boundary surfaces:
  - **team names** — `home_team_name`, `away_team_name`, `home_team_abbrev`,
    `away_team_abbrev` from `game_context` (DB).
  - **player names** — `player_name` from PBP events in `_collect_rosters()`
    and `featured_players` in evidence formatting.
  Defense-in-depth against malformed names from upstream feeds (NHL/NCAAB
  ingestion in particular consumes third-party JSON we don't own). Without
  this, a stray newline in a player name would visibly break the
  structured prompt sections; an attacker who landed adversarial text in
  upstream data could in principle inject directives the model treats as
  instructions. PBP is from official sports APIs, so realistic risk is
  low — this is the cheap belt-and-braces edit, not a fix for a confirmed
  exploit.

Verification: `python -m pytest tests/test_bulk_flow_diagnostics.py
tests/test_regen_context.py tests/test_render_blocks.py
tests/test_v1_flow_endpoint.py tests/test_game_flow_endpoint.py` — 138
passed. Coverage threshold fail is the pre-existing project-wide gate
unrelated to these edits.

---

## Trust boundaries the branch touches

| Surface | Auth | Notes |
|--------|------|-------|
| `GET /api/v1/games/{game_id}/flow` | API key (consumer-scoped via `verify_consumer_api_key`, applied at the v1 router level — `api/app/routers/v1/__init__.py:15`) + per-IP/keyed rate limit. | New on this branch — exposes blocks, plays, team metadata, v2 schema fields. **Hardened this pass** (validation field). |
| `GET /api/admin/sports/games/{game_id}/flow` | API key (`verify_api_key`, applied at app-include level — `api/main.py:322`) + admin-tier rate limit. | Deprecated; admin debugging surface. Exposes pipeline-internal `validationPassed`/`validationErrors` and full validation JSON. Acceptable for admin tooling. |
| `GET /api/admin/sports/games/{game_id}/timeline` | API key. | Read-only; returns persisted artifact JSONB verbatim. |
| `POST /api/admin/sports/games/{game_id}/timeline/generate` | API key. | Mutating + expensive (kicks off generation). Mounted under the admin prefix but only API-key-gated, not `require_admin`. Consistent with the rest of `sports.router`'s pattern (intentional per `api/main.py:319-322` comment) and bounded by the admin-tier rate limiter. See finding F-2. |
| Celery task `run_bulk_flow_generation` | Database-driven; the task reads a `BulkFlowGenerationJob` row created via the admin pipeline router. | **Hardened this pass** (game-count cap, failure-reason truncation). |
| Alembic migration `20260503_000070_add_v2_schema_fields_to_game_stories` | Schema only. | Adds five nullable columns to `sports_game_stories` (`version`, `archetype`, `winner_team_id`, `source_counts`, `validation`). All nullable, no constraints, additive — no data migration, no security impact. |
| LLM prompt builder (`render_prompts.py`) | DB-internal; not directly callable. | Reads team names + PBP `player_name` and embeds them in the OpenAI prompt. **Hardened this pass** (sanitizer). |
| Frontend guardrail (`web/src/lib/guardrails.ts`) | Client-only, pre-render check. | Branch only tightens `MAX_TOTAL_WORDS` 600→400 to mirror backend; client-side enforcement is advisory by definition (server is the canonical gate at `validate_blocks.py`). No new attack surface. |

---

## Findings

### F-1 — Player/team names embedded in LLM prompts unsanitized — **FIXED THIS PASS**

- **Severity:** Low.
- **File:** `api/app/services/pipeline/stages/render_prompts.py:336-345, 156-162, 396-416, before fix`.
- **Evidence:** `home_players: set[str] = set()` populated from `evt.get("player_name", "")` then concatenated into prompt as `f"{home_team} (home): {', '.join(sorted(home_players)[:10])}"`. Team names from `game_context` likewise interpolated raw.
- **Risk:** Defense-in-depth against newline / control-byte / quote characters that could break the prompt's structured sections or be (mis)read by the model as control directives. PBP is from official sports APIs so realistic exploit is low; the fix is a cheap sanitizer.
- **Action:** `_sanitize_prompt_string()` strips control bytes + a small set of structure-breaking characters (`` ` { } [ ] " ``) and caps length to 80; applied to all team and player strings in both the per-block and game-flow-pass prompt builders.

### F-2 — `POST /api/admin/sports/games/{game_id}/timeline/generate` not admin-role-gated — **NOT FIXED, JUSTIFIED**

- **Severity:** Low.
- **File:** `api/app/routers/sports/game_timeline.py:117-147`; mounted via `app.include_router(sports.router, dependencies=auth_dependency)` at `api/main.py:322`.
- **Evidence:** The router prefix is `/api/admin/sports`, suggesting admin-only, but the dependency is `auth_dependency = [Depends(verify_api_key)]` — API key only, no `require_admin`. A consumer-scoped key is rejected for admin routes (see `api/app/dependencies/auth.py:67-81`), so this is admin-or-equivalent in practice; but a non-admin JWT alongside a valid admin key would currently pass through.
- **Why not fixed inline:** The pattern is consistent across the entire `sports.router` bundle (games, teams, jobs, diagnostics, scraper_runs, etc.) and is documented as intentional in `api/main.py:319-322` ("Public / Guest-accessible endpoints (API key required, no role gate)"). Adding `require_admin` only to this one POST would be inconsistent and risks breaking internal callers (admin SPA, ops scripts) that don't carry a JWT.
- **Mitigations already in place:** The admin-tier rate limiter (`api/app/middleware/rate_limit.py:212-236`) caps invocations per IP and per key. Timeline generation is bounded per-game by a database transaction; there's no fan-out.
- **Smallest concrete next step:** If the team wants to tighten this surface, add an explicit `require_admin` (or a narrower role) to the *mutating* endpoints in `sports.router` only — leave the read-only ones unchanged. That belongs in a follow-up because it requires a sweep of all admin SPA / ops callers to confirm they carry the JWT, not just the API key.

### F-3 — Bulk job game-count cap missing; failure_reason persisted unbounded — **FIXED THIS PASS**

- **Severity:** Low (DoS-shaped, admin-triggered).
- **File:** `api/app/tasks/bulk_flow_generation.py:160-166, 257, 322 (before fix)`.
- **Evidence:** The pre-fix `if job.max_games is not None and job.max_games > 0: games = games[:job.max_games]` left `max_games is None` unbounded. Each game is followed by `await asyncio.sleep(0.2)` plus the pipeline run itself, so a multi-year window for all leagues could occupy a worker for many hours. Separately, `failure_reason = str(e)` and `errors_json = [{"error": str(e)}]` persisted whatever the exception's `__str__` produced — large traces or upstream JSON dumps would land in the admin UI.
- **Action:** `_BULK_JOB_HARD_GAME_CAP = 2000` enforced unconditionally; `_truncate_failure_reason()` caps stored exception strings at 500 chars.

### F-4 — `validation` field exposed by consumer v1 endpoint quoted internal phrases — **FIXED THIS PASS**

- **Severity:** Low (information disclosure / model-evasion signal).
- **File:** `api/app/routers/v1/games.py:191 (before fix)`; `validation` field defined at `api/app/routers/sports/schemas/game_flow.py:188-189, 218-219`.
- **Evidence:** `_build_validation_block()` (`finalize_moments.py:178-200`) populates `warnings` from `previous_output.get("warnings")`, which `validate_blocks.py` and `validate_blocks_phrases.py` build from validator strings like `"Block 2: banned phrases detected — ['set the tone']"`. Surfacing this on the consumer endpoint reveals (a) the existence and design of the post-LLM validator, (b) the specific phrases the model fell for, and (c) which blocks failed — useful information for an adversary trying to engineer prompt-injection content reaching the LLM via upstream data.
- **Action:** `_consumer_validation_view()` in `api/app/routers/v1/games.py` reduces the consumer payload to `{"status": <status>}` only; the full block remains on the admin endpoint.

### F-5 — Frontend guardrail constants are advisory; backend is authoritative — **NO ACTION NEEDED**

- **Severity:** None (informational).
- **File:** `web/src/lib/guardrails.ts:46, 54, 57, 76`.
- **Evidence:** Branch only tightened `MAX_TOTAL_WORDS` 600 → 400 to mirror `api/app/services/pipeline/stages/block_types.py`. The header comment states the canonical source is the Python file; CI enforces parity via `scripts/check_guardrails_sync.py`.
- **Why no action:** Client-side guardrails are a UX backstop; the backend `validate_blocks.py` rejects oversized payloads regardless of what the client believes. No bypass risk.

### F-6 — Scraper status-transition self-heal does not regress finals — **NO ACTION NEEDED**

- **Severity:** None (correctness review of the new behavior).
- **File:** `scraper/sports_scraper/persistence/games.py:441-508`; promotion guard at `scraper/sports_scraper/services/game_processors.py:140-196`.
- **Evidence:** `resolve_status_transition()` accepts a `live → pregame|scheduled` regression *only* when `current == live`, the incoming status is one of those two, AND `game_date > now + 15min`. Final / post-final / archived states are short-circuited earlier (`if is_final_or_post_final_status(current): ...` returns before the regression branch). The new MLB-PBP filter rejects synthetic `game_advisory` events before they can cause an incorrect promotion (`scraper/sports_scraper/live/mlb_pbp.py:146-152`); `try_promote_to_live()` additionally refuses to flip a game to live when scheduled tipoff is still in the future (`game_processors.py:167-181`).
- **Why no action:** Behavior is well-bounded, has explicit unit coverage in `scraper/tests/test_persistence_games.py`, and the failure modes (rare brief flicker around tipoff) are documented in the new docstring.

---

## Notes on what was reviewed and not changed

- **New alembic migration `20260503_000070`** — adds 5 nullable columns to
  `sports_game_stories`; no constraints, no data migration. Standard
  additive migration with safe `downgrade()`. No security implications.
- **`validate_blocks_phrases.py` TOML loader** — the fallback path on TOML
  parse failure uses a 7-phrase compatibility list and logs at ERROR with
  `exc_info=True`; not a security issue (degraded validator quality, not
  bypassed validator). Already documented in `error-handling-report.md` §F-4.
- **`bulk_flow_generation.py:91`** — `create_async_engine(settings.database_url, echo=False, ...)`
  sets `echo=False`, so SQL parameters aren't logged. The engine is
  disposed in a `finally` block to prevent connection leaks.
- **Render prompts use SegmentEvidence dataclass values** — all evidence
  numeric fields (`points`, `duration_plays`, `delta_contribution`) are
  formatted via Python f-strings on `int` values from upstream
  validators; no string interpolation surface beyond the names already
  sanitized in F-1.
- **`game_timeline.py` `generate_game_timeline` error path** —
  `raise HTTPException(status_code=exc.status_code, detail=str(exc))` passes
  the `TimelineGenerationError`'s message verbatim. These are
  pipeline-controlled strings; for the admin endpoint this is acceptable.
  If the same error path is ever wired into the v1 surface, it should be
  scrubbed first.
- **`web/src/lib/guardrails.ts`** — only constant change on the branch;
  no logic change.

---

## No escalations.

All in-scope items were either fixed inline or have a concrete justification
documented above. The one architectural item (F-2: admin role gating on
mutating endpoints under `sports.router`) is a deliberate project-wide
pattern; changing it would require a follow-up that audits all internal
callers, which is beyond a defensive hardening pass.
