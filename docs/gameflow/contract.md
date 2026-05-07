# Game Summary Contract (v3-summary)

This is the binding spec for the catch-up game summary returned by
`GET /api/v1/games/{gameId}/summary`. The summary replaces the prior
block-based game flow and is generated once per completed game in a
single LLM call.

## Pipeline shape

```
NORMALIZE_PBP → CLASSIFY_GAME_SHAPE → GENERATE_SUMMARY → FINALIZE_SUMMARY
```

`NORMALIZE_PBP` and `CLASSIFY_GAME_SHAPE` are deterministic. The single
LLM hit happens inside `GENERATE_SUMMARY`. `FINALIZE_SUMMARY` persists
the result to `sports_game_stories.summary_json` with
`story_version="v3-summary"`.

## Output schema

Stored in `sports_game_stories.summary_json` and surfaced (with team and
league metadata) by the consumer endpoint:

```json
{
  "summary": [
    "Paragraph one (2–4 sentences).",
    "Paragraph two...",
    "Closing paragraph that contains the final score in prose."
  ],
  "referenced_play_ids": [12, 47, 102, 138, 201],
  "key_play_ids": [3, 12, 47, 88, 102, 138, 201],
  "home_final": 110,
  "away_final": 109,
  "by_period": [[28, 31], [25, 22], [27, 30], [30, 26]],
  "total_words": 187
}
```

| Field | Description |
|-------|-------------|
| `summary` | List of 3–5 narrative paragraphs. Plain text. No markdown. |
| `referenced_play_ids` | `play_index` values the recap actually leans on. Subset of `key_play_ids`. |
| `key_play_ids` | Full set of plays selected by `select_key_plays_full_game()` and offered to the model. |
| `home_final` / `away_final` | Final score read from the last `pbp_event` in `NORMALIZE_PBP`. |
| `by_period` | Per-period `[home, away]` deltas, ordered by period number. |
| `total_words` | Sum of words across all paragraphs. |

## Voice rules

- 3–5 paragraphs, 2–4 sentences each.
- Active voice. Standout players named naturally as the events warrant.
- The final score appears in the closing paragraph as prose, not as a
  header or a leading sentence.
- No markdown, headers, or bullet points in `summary` strings.
- No empty clichés ("set the tone", "left it all on the floor").
- The model must only reference plays that appear in the supplied
  `key_plays` list. The stage filters `referenced_play_ids` to that set
  before persistence; hallucinated ids are dropped silently.

## Sport-specific vocabulary

Sport differences are injected via `league_config.LEAGUE_CONFIG` rather
than separate prompt variants:

| League | `period_noun` | `score_noun` | `extra_period_label` |
|--------|---------------|--------------|----------------------|
| NBA    | quarter       | point        | overtime             |
| NCAAB  | half          | point        | overtime             |
| NHL    | period        | point        | overtime             |
| MLB    | inning        | run          | extra innings        |
| NFL    | quarter       | point        | overtime             |

## Archetype hints

`CLASSIFY_GAME_SHAPE` produces one of: `wire_to_wire`, `comeback`,
`back_and_forth`, `blowout`, `early_avalanche_blowout`, `low_event`,
`fake_close`, `late_separation`. Each maps to a one-line tone hint
injected into the prompt — see `summary_prompt._ARCHETYPE_HINTS`.

## Persistence and caching

- One row per game with `story_version="v3-summary"` in
  `sports_game_stories`. Cached indefinitely.
- Old `v2-blocks` rows remain in storage for history but are not served
  by any endpoint.
- Regeneration happens only via the admin pipeline endpoints. The
  pipeline does not auto-regenerate.

## Versioning

- `story_version` (DB upsert key) — `"v3-summary"`.
- `version` (top-level schema literal) — `"game-flow-v3"`.

When the prompt or schema changes in a way that affects consumers, bump
`version` and add a migration note here.
