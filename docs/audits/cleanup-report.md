# Code Quality Cleanup Report

**Date:** 2026-05-03
**Scope:** files modified/added on the current `flow` branch — the in-progress
gameflow v2 work (archetype classification, score-timeline helpers, evidence
selection, debug logger, finalize_moments v2 schema, render-prompt rewrite,
bulk-flow diagnostics, the supporting Alembic migration) plus the scraper-side
status-transition self-heal and MLB PBP `game_advisory` filter (and their
tests).
**Rule:** no behavioral changes; build must still pass and the touched test
files must still run green.

## Changes made this pass

### Ruff/style fixes (no behavior change)

- `api/app/services/pipeline/stages/analyze_drama.py:137` (SIM300) — rewrote
  Yoda condition `"Q1" != turning_q` as `turning_q != "Q1"`.
- `api/app/services/pipeline/stages/analyze_drama.py:151-156` (SIM114) —
  collapsed two adjacent `elif archetype == "back_and_forth"` /
  `elif archetype == "low_event"` branches that set identical `weights[q] =
  1.0` into a single `elif archetype in {"back_and_forth", "low_event"}:`
  block.
- `api/app/services/pipeline/stages/group_helpers.py:51-54` (SIM108) —
  collapsed the `if archetype in {…}: base = 5 / else: base = 4` pair into
  the equivalent ternary `base = 5 if archetype in {…} else 4`.
- `api/app/services/pipeline/stages/render_prompts.py:16-55` (E402, ×5) —
  the helper `_sanitize_prompt_string` had been wedged between the
  `from __future__ import annotations` line and the relative-import block,
  triggering five `E402 module level import not at top of file`. Moved the
  five relative imports up to immediately follow the absolute imports; the
  helper now lives below the import section. No behavior change — the
  function is still defined before its first caller (`_format_evidence_block`
  is hundreds of lines below).

### Scraper-side fixes (no behavior change)

- `scraper/tests/test_game_processors.py:7,9,21` (F401 ×3) — removed three
  unused imports added with the new test module: `datetime.timezone`,
  `types.SimpleNamespace`, and `import pytest`. Verified no `pytest.` /
  `timezone(` / `SimpleNamespace(` references remain in the file.
- `scraper/tests/test_game_processors.py:64` (SIM910) —
  `kwargs.get("end_time", None)` simplified to `kwargs.get("end_time")`.
- `scraper/tests/test_pbp_mlb.py` (I001) — re-ordered the stdlib import block
  so `pathlib.Path` sits with the other stdlib imports rather than below
  `unittest.mock`, then ran `ruff --fix` to normalise the rest of the
  branch's import groups.
- `scraper/tests/test_persistence_games.py:829-838` (I001 ×2) — local
  imports inside two test methods (`test_midnight_et_is_not_real`,
  `test_noon_et_is_not_real`) had `sports_scraper.utils...` listed before
  `from datetime import …`. Reordered so the stdlib import comes first, per
  ruff isort convention. Local-import pattern (rather than module-level)
  preserved on purpose: those are the only two tests in the file that need
  `start_of_et_day_utc`, and the surrounding tests in `TestHasRealTime`
  intentionally don't import it.

### Verification

- `ruff check` — clean across every modified file in the branch
  (the full per-file allowlist re-run, both api and scraper sides). Zero
  errors after this pass; previous pass left 8 + 9 unfixed warnings, all of
  which are now closed.
- `pytest -q` for the api branch test suites
  (`test_analyze_drama test_render_blocks test_regen_context
  test_validate_blocks test_group_blocks test_classify_game_shape
  test_score_timeline test_evidence_selection test_finalize_moments_v2_schema
  test_flow_debug_logger test_flow_thresholds test_bulk_flow_diagnostics
  test_pipeline_models test_v1_flow_endpoint test_game_flow_endpoint
  test_banned_phrases test_boundary_triggers`) — 640 passed, 0 failed.
- `pytest -q` for the scraper branch test suites
  (`test_persistence_games test_pbp_mlb test_game_processors`) — 189
  passed, 0 failed.

## Files still over 500 LOC (in-scope, modified this branch)

| File | LOC | Status |
|------|-----|--------|
| `api/app/services/pipeline/executor.py` | 639 | **Justification.** Unchanged from previous pass — orchestration entry point for the entire pipeline (stage dispatch, run/stage transactional bookkeeping, FlowDebugLogger lifecycle, player-name mapping). The branch's edits this pass are limited to the debug-logger setup/teardown around `run_full_pipeline`, which must be co-located with the run lifecycle. **Plan for next pass:** lift `_build_player_name_mapping` (~120 LOC, lines 254-298) and `_resolve_league_code` (lines 237-252) into `pipeline/executor_helpers.py`. Both are now called only from `_get_game_context`, so a follow-up PR can move them with no public-API change. |
| `api/app/services/pipeline/stages/render_prompts.py` | 632 | **Justification.** Grew by ~114 LOC since the previous pass (518 → 632) as the v2 prompts continue to stabilise — this branch added archetype-specific guidance, NHL context lines, the shots-by-period formatter, the banned-phrase serialiser, and resolution-extras handling. The file has a clean three-section shape (archetype guidance, evidence formatting, two builder functions) but a split now would fragment the prompt vocabulary mid-rewrite, with no caller benefit. The two test files that depend on it (`test_render_blocks`, `test_regen_context`) only import the *public* builder names (`build_block_prompt`, `build_game_flow_pass_prompt`, `GAME_FLOW_PASS_PROMPT`); none of the underscore helpers leak. **Plan for next pass:** once the BRAINDUMP TODOs close, extract the evidence-formatting helpers (`_format_evidence_block`, `_resolve_team_label`, `_scoring_unit`, `_nhl_context_lines`, `_format_shots_by_period`, `_format_banned_phrases`; ~170 LOC) into `render_prompts_evidence.py`. That alone drops the file under 500 without touching the public API. |
| `api/app/services/pipeline/stages/finalize_moments.py` | 531 | **Justification.** Unchanged from previous pass; same v2-schema enrichment (`_signed_lead`, `_ensure_v2_block_fields`, `_resolve_winner_team_id`, `_compute_source_counts`, `_build_validation_block`) plus debug-logger calls. Helpers live next to the persistence flow that consumes them; extracting now would require coupling SCHEMA_VERSION_V2 / FLOW_VERSION across `db/flow.py`. **Plan for next pass:** extract the four `_…` enrichment helpers + `_extract_flow_score` into `pipeline/helpers/v2_schema.py`. |
| `api/app/services/pipeline/helpers/evidence_selection.py` | 524 | **Justification.** Unchanged from previous pass; single public entry point (`select_evidence`) composing seven small private helpers. Reads top-to-bottom as one algorithm. **Plan for next pass:** extract the three per-league flag detectors (`_detect_power_play_goal`, `_detect_empty_net_goal`, `_detect_short_handed_goal`, `_detect_home_run`) into `evidence_league_flags.py` if a fourth league-specific flag lands. |

All other in-scope files are under 500 LOC.

## Consistency edits (one line per file)

- `api/app/services/pipeline/stages/analyze_drama.py` — fix SIM300 Yoda; collapse SIM114 duplicate elifs.
- `api/app/services/pipeline/stages/group_helpers.py` — collapse SIM108 if/else into ternary.
- `api/app/services/pipeline/stages/render_prompts.py` — hoist five relative imports to top of file (E402 ×5).
- `scraper/tests/test_game_processors.py` — drop three unused imports; SIM910 default-`None` cleanup.
- `scraper/tests/test_pbp_mlb.py` — ruff-isort import block.
- `scraper/tests/test_persistence_games.py` — ruff-isort two local-import blocks inside test methods.

## Duplicate utilities

None consolidated this pass. The previous report's audit (between `_signed_lead`
in `finalize_moments` vs the in-line `signed_lead` arithmetic in
`block_analysis`, and the single canonical home of `build_score_timeline` /
`ScoreTimeline` in `pipeline/helpers/score_timeline.py`) still holds — verified
afresh against the current diff.

The two new branch files re-checked:

- `api/app/services/pipeline/stages/classify_game_shape.py` (294 LOC) — the
  archetype classifier. Reads the score timeline via `score_timeline.py` and
  reuses `LEAGUE_CONFIG` from `league_config.py`; defines no helpers that
  exist elsewhere.
- `api/app/services/pipeline/stages/validate_blocks_segments.py` (302 LOC) —
  segment-level validators (per-block evidence checks, leverage-claim
  checks, lead-change consistency). Imports from
  `validate_blocks_constants.py` and `evidence_selection.py`; no overlap
  with `validate_blocks_text` / `validate_blocks_phrases` /
  `validate_blocks_resolution` / `validate_blocks_rules` (each handles a
  distinct validation axis).

## Considered but not changed

- **Pre-existing narration comments in
  `finalize_moments.execute_finalize_moments`** (lines 229, 234, 245, 250,
  264) — `# Get input data from previous stages`,
  `# Verify VALIDATE_MOMENTS passed`, `# Get moments`, etc. Predate this
  branch (Jan–Feb 2026); per the no-out-of-scope-refactor rule, left as is.
  Lines added by *this* branch in the same function (e.g. the
  `# v2 schema enrichment` comment, the eager-load comment around the
  `select(SportsGame)` call) explain a non-obvious *why* and stay.
- **`api/app/services/pipeline/executor.py` broad `except Exception`** at
  the orchestration boundary — explained inline with a reference to
  `docs/audits/error-handling-report.md §F-11`. Canonical
  orchestration-boundary pattern; narrowing would silently lose stages.
- **`api/app/tasks/bulk_flow_generation.py` per-game broad `except Exception`** —
  same rationale (§F-8). A single bad game must not fail the bulk run; the
  catch is paired with `exc_info=True` structured logging.
- **F401 `noqa` imports in `bulk_flow_generation.py`** (MLB/NBA/NFL/NHL/NCAAB
  advanced-stat models, odds, social posts) — load-bearing SQLAlchemy
  relationship-resolution imports. The `# noqa: F401` markers are correct.
- **Local imports inside two test methods of
  `scraper/tests/test_persistence_games.py`** (`from sports_scraper.utils.
  datetime_utils import start_of_et_day_utc` plus `from datetime import …`).
  Two of ~30 tests in `TestHasRealTime` need `start_of_et_day_utc`; lifting
  the import to module scope would make the dependency look universal.
  Re-ordered the local blocks so they pass I001 instead.
- **The previous pass's `test_game_processors.py` SIM910 fix
  (`kwargs.get("end_time", None)`)** — applied this pass; the previous report
  did not flag it because the file was untracked at the time the previous
  pass ran.

## Escalations

None this pass. Every finding above was either acted on or has a written
justification with a concrete plan-for-next-pass for the four >500-LOC files.
The growth of `render_prompts.py` (518 → 632) is on the radar; the
extraction plan for evidence formatters is documented above and can be
picked up the moment the v2 prompt rewrite stabilises.
