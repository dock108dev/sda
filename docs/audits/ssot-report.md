# SSOT Enforcement Report — `flow` branch

Scope is the committed diff between `flow` and `main` (one commit:
`44401363 feat(status_handling): enhance game status transition logic with
self-heal margin`). The diff hardens three behaviors in the scraper status
pipeline:

1. `resolve_status_transition()` gained a `game_date` kwarg used to self-heal
   a stuck `live` game back to `pregame`/`scheduled` when tipoff is still
   >15min in the future.
2. `MLBPbpFetcher._normalize_play()` drops MLB Stats API synthetic
   `game_advisory` events that previously masqueraded as 1st-inning plays
   and triggered false live promotions.
3. `try_promote_to_live()` refuses to flip status to `live` when
   `game.game_date > now`.

SSOT consequence: any call site that touches game status, ingests MLB plays,
or promotes a game to `live` must funnel through these guards. Anything that
bypasses them is a parallel implementation of the SSOT and is the target of
this pass.

The large set of uncommitted changes under `api/app/services/pipeline/`
(Game Flow narrative pipeline rework, see `BRAINDUMP.md`) is unrelated to the
single committed change and is out of scope for this pass — modifying it
would discard work-in-progress that the diff does not prove obsolete.

## Changes made this pass

All four bypass call sites of `resolve_status_transition` now pass
`game_date=`. Without this, the self-heal escape hatch added in the branch
commit silently does nothing for those code paths — a stuck `live` row
written by NBA boxscore ingestion or by a live-feed update would never
recover.

| File | Function | Change |
|------|----------|--------|
| `scraper/sports_scraper/services/nba_boxscore_ingestion.py:195` | `_apply_boxscore_to_game` | added `game_date=game.game_date` |
| `scraper/sports_scraper/persistence/boxscore_helpers.py:264` | `enrich_game_from_boxscore` | added `game_date=game.game_date` |
| `scraper/sports_scraper/persistence/games.py:326` | `_enrich_existing` | added `game_date=game_date or game.game_date` (function already receives `game_date` as a parameter) |
| `scraper/sports_scraper/persistence/games.py:572` | `update_game_from_live_feed` | added `game_date=game.game_date` |

No deletions: this branch's diff is purely additive defensive hardening — it
does not introduce a new SSOT module that supersedes an old one, remove a
flag, or reroute through a new path. There is no legacy code that the diff
proves obsolete. The SSOT work here is *propagation*: making sure every
caller funnels through the new guard rather than silently degrading to the
old behavior.

`scraper/tests/test_persistence_games.py` already covers the self-heal
contract (`TestResolveStatusTransitionSelfHeal`, including the
"without game_date does not heal" case). The propagation fixes above are
behavior-preserving in tests because the existing tests mock `game.game_date`
through `MagicMock` (truthy `MagicMock` objects compared against `now_utc()`
are not in the heal window in either direction). Full scraper suite passes
(189/189; the coverage FAIL is the pre-existing project threshold).

## Final SSOT modules per domain

| Domain | SSOT module / function | Notes |
|--------|------------------------|-------|
| Game status transitions | `scraper/sports_scraper/persistence/games.py::resolve_status_transition` | All advancement, regression, and self-heal logic lives here. Callers must pass `game_date=` to enable self-heal. |
| MLB live PBP normalization | `scraper/sports_scraper/live/mlb_pbp.py::MLBPbpFetcher._normalize_play` | Sole place that decides whether an MLB Stats API `allPlays` entry becomes a persisted play row. The `game_advisory` filter belongs here. |
| Pregame → live promotion | `scraper/sports_scraper/services/game_processors.py::try_promote_to_live` (PBP-inferred) and `scraper/sports_scraper/services/game_state_updater.py::_promote_pregame_to_live` (time-based) | Two complementary promotion paths; both gate on `game_date <= now`. |

## Risk log — intentionally retained

### `scraper/sports_scraper/live/mlb_statcast.py` does not filter `game_advisory`

Three loops iterate `payload["allPlays"]` without a `game_advisory` guard
(`aggregate_from_payload:215`, `aggregate_players_from_payload:240`,
`aggregate_pitchers_from_payload:288`). They are structurally safe because:

- They sum stats by iterating `at_bat["playEvents"]` and gating on
  `event.get("isPitch", False)`. A synthetic Game Advisory has no pitch
  events, so the inner loop is a no-op for those at-bats.
- Player and pitcher aggregators key on `matchup.batter.id` /
  `matchup.pitcher.id` and `continue` when those are falsy. Game Advisories
  do not carry a real batter/pitcher, so the per-player path also short-
  circuits.

Adding a redundant `eventType == "game_advisory"` filter would be defense in
depth but is not load-bearing. The bug the branch fixed was
"synthetic event becomes a play row"; statcast aggregation never produces
play rows, only counters, and the counters are gated on signals
(`isPitch`, `id`) that synthetic events don't carry. **No change.**

### `scraper/sports_scraper/services/game_state_updater.py:145` writes `live` directly

`_promote_pregame_to_live` assigns `game.status =
db_models.GameStatus.live.value` without calling `try_promote_to_live` or
`resolve_status_transition`. This is safe because the surrounding SQL query
(`game_date.isnot(None)` AND `game_date < now`) already enforces the
future-tipoff guard at the row-selection level — no row in the loop body
can have `game_date > now`. The other direct status assignments in this
file (`scheduled → cancelled`, `stale → final`, `final → archived`) do not
touch the `live` lane and are not in scope for this pass. **No change.**

### `BRAINDUMP.md` retained at repo root

It is a planning artifact for the uncommitted Game Flow rework, not part of
the committed branch diff and not contradicted by it. Removing it would
delete a teammate's planning notes that are still actively referenced by
the working-tree changes. **No change.**

## Sanity check — dangling references

- `git grep "resolve_status_transition("` after this pass: every match
  outside the function definition itself passes `game_date=` (verified
  during the inventory).
- No code references a removed flag, deleted helper, or stale import path —
  the branch diff did not remove any symbol.
- No tests assert the old "no `game_date` kwarg" signature; the existing
  test (`test_live_to_pregame_without_game_date_does_not_heal`) explicitly
  preserves the kwarg-optional contract for backward compatibility, so the
  call-site updates above remain compatible with both old and new behavior.

## Escalations

None. Every finding was either acted on or has a concrete structural
justification recorded in this report and (for retained risks) at the code
location's surrounding context.
