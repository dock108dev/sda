# Scroll Down MLB

Spoiler-safe MLB catch-up deck. Read-only consumer surface served from
`/api/v1/scroll-down-mlb/...`, backed by the `app.scroll_down_mlb`
package and the `scroll_down_mlb_decks` table.

**Code:** `api/app/scroll_down_mlb/`
**Router:** `api/app/scroll_down_mlb/router.py` (mounted in `api/main.py`)
**Persistence:** `api/app/db/scroll_down_mlb.py` (SQLAlchemy) + Alembic
migration `20260510_000074_create_scroll_down_mlb_decks.py`

---

## Spoiler-safety contract

The product purpose is to let a user catch up on a game *without* learning
the result before they want to. Three endpoints, three different
disclosure rules:

| Endpoint | What it returns | What it must NOT contain |
|---|---|---|
| `GET /api/v1/scroll-down-mlb/games/recent` | List of games with `hasDeck` / `isFinal` flags | scores, winners, run totals, leads — anything implying a result |
| `GET /api/v1/scroll-down-mlb/games/{gameId}/deck` | The deck (scenes + plays + rhythm cards) | post-play scores (`scoreAfter`); only `scoreBefore` + `runsScoredOnPlay` are exposed so the running scoreboard works without leaking the final |
| `GET /api/v1/scroll-down-mlb/games/{gameId}/reveal` | Final score + winner + recap | (this is the *only* endpoint allowed to expose those) |

The contract is enforced by tests, not just convention:

- `api/tests/test_scroll_down_mlb_spoiler_safety.py` — recursive key-walk
  over each response asserting no forbidden field names appear on the
  pre-reveal endpoints.
- `api/app/scroll_down_mlb/validation.py::validate_no_final_score_leak`
  — runs at the end of `build_deck_from_upstream`. Any forbidden key in
  the serialized wire shape becomes a validation finding; the policy
  splitter then re-runs and **blocks** the deck on `official` policy
  (so a leaky deck is never persisted).

---

## Endpoints

### `GET /api/v1/scroll-down-mlb/games/recent`

Spoiler-safe feed for the home grid. Returns up to 50 MLB games whose
first pitch falls in the last 48 hours (`_RECENT_WINDOW_HOURS` in
`service.py`), capped at the current time so future-scheduled games
never appear, joined with the deck table for `hasDeck` / `deckVersion`.

Response: `ScrollDownMlbRecentResponse` (`api/app/scroll_down_mlb/schemas.py`).

### `GET /api/v1/scroll-down-mlb/games/{gameId}/deck`

Returns the live or official deck. Behavior:

- Game not found / not MLB → `404`
- Pregame / scheduled → `404`
- Live: build a fresh provisional deck from current play data, return.
- Final: serve the persisted official deck if present; otherwise build,
  validate, persist (freeze), return.

Live decks use `GenerationPolicy.live` — validation errors degrade to
warnings so an in-progress game never shows a blank screen for a
transient feed contradiction. Official decks use `GenerationPolicy.official`
— any error blocks generation; the deck is not persisted.

Response: `ScrollDownMlbDeckResponse` with `spoilerPolicy: "pre_reveal"`.

### `GET /api/v1/scroll-down-mlb/games/{gameId}/reveal`

Final-score reveal — the *only* endpoint allowed to expose
`finalScore` and `winnerTeamId`. Returns `409` if the game has not yet
produced a reveal payload (live, postponed, or upstream not ready).

Response: `ScrollDownMlbRevealResponse`.

---

## Build pipeline

`build_deck_from_upstream` (in `api/app/scroll_down_mlb/_pipeline.py`)
is the parity surface for fixture tests and the canonical entry point
for both live and official generation. Stages, in order:

1. **Game state reconstruction** — `compute_timeline` +
   `compute_pitcher_timeline` (`game_state.py`) walk every upstream play
   and forward-propagate inning, half, score, base state, runner names,
   outs.
2. **Play selection** — `select_plays` + `sample_tier_2`
   (`deck_builder.py`) pick the moments worth showing.
3. **Card assembly** — `to_play_card` + `decorate_play_card` produce
   `BuiltPlayCard`s with chip labels, narrative, and leverage tier.
4. **Rhythm planning** — `plan_deck_with_report` (`rhythm_planner.py`)
   inserts pacing cards (inning transitions, quiet stretches, late-game
   markers, final setup).
5. **Validation** — per-card validation + duplicate-id check
   (`validation.py`); findings are split by `apply_validation_policy`.
6. **DTO conversion** — `built_deck_to_dto` (`_dto.py`) builds the
   spoiler-safe Pydantic response, dropping post-play scores.
7. **Final-score-leak scan** — `scan_response_for_final_score_leaks`
   inspects the serialized wire shape; if it finds anything, policy
   re-runs and `official` decks block.
8. **Persistence** — `upsert_deck` (`persistence.py`) writes final decks
   to `scroll_down_mlb_decks` keyed by
   `(game_id, deck_version, spoiler_policy)`.

The pipeline order is also documented in `_pipeline.py`'s docstring;
this file is the prose-form mirror.

---

## Persistence

Table: **`scroll_down_mlb_decks`** (`api/app/db/scroll_down_mlb.py`).

| Column | Notes |
|---|---|
| `(game_id, deck_version, spoiler_policy)` | Composite uniqueness — upsert key |
| `payload_json` | Full DTO (JSONB) — `/deck` serves this directly |
| `planner_report_json` | Pacing-decision trace; admin/QA only |
| `validation_warnings_json` / `validation_errors_json` | Findings from this generation |
| `source_hash` | Stable digest of the inputs the deck was built from. Lets live polling decide whether anything changed without re-running the full pipeline. |
| `is_final` | Marks the canonical "official" row when `spoiler_policy=pre_reveal` |
| `generated_at` / `updated_at` | `updated_at` is refreshed explicitly on conflict (ORM `onupdate` does not fire for `INSERT ON CONFLICT DO UPDATE`) |
| `card_count`, `generator_label` | Soft summary fields for list queries / debugging |

There can be many rows per game: live polling produces a sequence of
`pre_reveal` versions; the first `is_final=True` row is canonical.

---

## Live vs official: the policy split

| Policy | Trigger | Validation severity rule | Persisted? |
|---|---|---|---|
| `live` | Game is in progress | Errors degrade to warnings — the live deck always ships | No |
| `official` | Game has reached a final status | Errors block generation; deck is returned as `None` | Yes (frozen on first successful build) |

Defined in `apply_validation_policy` (`_pipeline.py`) and
`get_game_deck` (`service.py`).

---

## Parity corpus

The `api/tests/fixtures/scroll_down_mlb/` directory holds 23 captured
upstream payloads + 23 TS-builder snapshot outputs. The Python port is
expected to match the TS snapshots field-for-field with two intentional
differences (documented in the fixture-corpus README):

1. `scoreAfter` is absent from the Python `PlayPayload` — the
   spoiler-safety contract forbids it. Parity tests strip `scoreAfter`
   from the TS snapshot before comparing.
2. camelCase keys (no transformation needed; backend uses Pydantic
   alias generators).

Refresh procedure: see `api/tests/fixtures/scroll_down_mlb/README.md`.

---

## What is intentionally NOT here

- **An LLM-driven recap.** The reveal endpoint returns a deterministic
  templated summary (`"<winner> beat <loser>, X–Y."`) — a
  gameflow-summary source can be wired in a follow-up, but the current
  build deliberately avoids an LLM dependency on the reveal path.
- **A push or websocket channel.** Clients poll. The `deckVersion`
  string lets a client detect updates without diffing the cards array.
- **Multi-league support.** This module is MLB-only by design; the
  spoiler-safety phrasing ("extra innings" vs "overtime", base-state
  payloads, leverage formula) does not generalize trivially.
