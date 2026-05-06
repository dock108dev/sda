# Game Flow Contract

## Foundational Axiom

**A game flow consists of 3-7 narrative blocks. Each block is grounded in
one or more moments. Each moment is backed by specific plays.**

This creates a two-level structure:

- **Blocks** — Consumer-facing narratives (3-7 per game, 1-5 sentences each, ~65 words)
- **Moments** — Internal traceability (15-25 per game, linking blocks to plays)

A block carries two parallel role dimensions:

- `role` — the **structural** semantic role (SETUP / MOMENTUM_SHIFT / RESPONSE
  / DECISION_POINT / RESOLUTION). Used by structural validators.
- `story_role` — the **narrative beat** chosen by the segmenter (opening,
  first_separation, response, lead_change, turning_point, closeout,
  blowout_compression). The voice rules enforce that this beat is consistent
  with the block's evidence.

`story_role` is the single source of truth for "what kind of moment is
this?" — the older "label" / "reason" prose fields it replaced are gone.

---

## 1. Purpose and Scope

Game Flow produces a readable, condensed replay of a game designed for 60-90
second consumption.

- The output is a sequence of narrative blocks
- Each block has a structural role and a narrative `story_role`
- The sequence preserves game chronology
- Total read time: 60-90 seconds (~600 words max)

**This system narrates consequences, not transactions.** It condenses game
action into reporter-style prose, collapsing sequences into runs and describing
effects rather than enumerating individual plays.

---

## 2. Core Units

### Narrative Block (Consumer-Facing)

A **narrative block** is:

- A short narrative (1-5 sentences, ~65 words)
- Tagged with both a structural role and a narrative `story_role`
- Grounded in one or more moments
- Annotated with `leverage`, `score_context`, `period_range`, and a
  `featured_players` evidence list
- Part of a 3-7 block sequence

**Structural roles (`role`):**

| Role | Description |
|------|-------------|
| SETUP | Early context, how game began (always first) |
| MOMENTUM_SHIFT | First meaningful swing |
| RESPONSE | Counter-run, stabilization |
| DECISION_POINT | Sequence that decided outcome |
| RESOLUTION | How game ended (always last) |

**Narrative beats (`story_role`):**

| Story role | When the segmenter assigns it |
|------------|------------------------------|
| `opening` | First block; sets the stage. |
| `first_separation` | First block where one team builds a meaningful lead. |
| `response` | A counter-run that materially shrinks or flips the gap. |
| `lead_change` | The block contains a tie-flip and the lead actually changed hands. |
| `turning_point` | The block in which the eventual winner separates for good. |
| `closeout` | Final block; describes how the game ended. |
| `blowout_compression` | Adjacent low-leverage middle blocks of a blowout, merged into one. |

`story_role` is required (Rule 19, FAIL).

**Leverage (`leverage`):** `low` / `medium` / `high`. Drives prompt voice
(quiet vs. urgent) and is used by validators to flag drama mismatches.

**Block Limits:**

- Minimum: 3 blocks per game (blowouts and low-event games compress to 3)
- Maximum: 7 blocks per game
- No structural role appears more than twice
- SETUP is always first; RESOLUTION is always last

### Moment (Internal Traceability)

A **moment** is:

- A contiguous set of PBP plays (typically 15-50 plays)
- At least one play (up to 5) is explicitly narrated
- A discrete, meaningful segment of game action
- Used for tracing blocks back to specific plays

Moments do not have consumer-facing narratives. They exist for auditability.

---

## 3. Required Fields

### Block Fields

| Field | Type | Purpose |
|-------|------|---------|
| `block_index` | int | Position (0–6) |
| `role` | string | Structural role (SETUP, MOMENTUM_SHIFT, …) |
| `story_role` | string | Narrative beat (see table above) |
| `leverage` | string | `"low"` / `"medium"` / `"high"` |
| `moment_indices` | list[int] | Which moments are grouped |
| `period_start` / `period_end` | int | First / last period covered |
| `period_range` | string | Sport-aware human label (`"Q4 6:39–0:00"`, `"Inning 8–9"`, `"P1"`) |
| `score_before` | [home, away] | Score at block start |
| `score_after` | [home, away] | Score at block end |
| `score_context` | object | `{lead_change: bool, largest_lead_delta: int}` |
| `featured_players` | list[object] | Up to 2 player anchors with structured `reason` |
| `play_ids` | list[int] | All plays inside the block |
| `key_play_ids` | list[int] | 1–3 plays the renderer is allowed to highlight |
| `narrative` | string | 1–5 sentences (~65 words) |
| `embedded_social_post_id` | int \| null | Optional social post ID (max 1 per block) |
| `mini_box` | object \| null | Cumulative + per-block deltas for top players |

`featured_players` entries are skipped (not generated) for `opening` and
`blowout_compression` story roles — those beats lean on the mini box rather
than a featured-player anchor.

### Moment Fields (Traceability)

| Field | Type | Purpose |
|-------|------|---------|
| `play_ids` | list[int] | Backing plays |
| `explicitly_narrated_play_ids` | list[int] | Key plays (1-5) |
| `period` | int | Game period |
| `start_clock` | string | Clock at first play |
| `end_clock` | string | Clock at last play |
| `score_before` | [home, away] | Score at moment start |
| `score_after` | [home, away] | Score at moment end |

---

## 4. Narrative Rules

### Block Narratives

Each block narrative:

- Is 1–5 sentences, approximately 65 words
- Describes a stretch of play with consequence-based narration
- Is role-aware (SETUP blocks set context, RESOLUTION blocks conclude)
- Uses SportsCenter-style broadcast prose
- Collapses consecutive scoring into runs where appropriate
- May reference a `featured_players` anchor by name; the anchor's `reason`
  is structured evidence the renderer is allowed to lean on

### Forbidden Language

Narratives must not contain:

- "momentum", "turning point", "shift"
- "crucial", "pivotal", "key moment"
- "dominant", "clutch", "huge", "massive"
- Retrospective commentary ("would later prove…")
- Speculation ("appeared to", "seemed to")

The full banned-phrase list lives in `render_validation.BANNED_PHRASES` and is
locked by `tests/test_banned_phrases.py`.

### Traceability

Every narrative claim is traceable:

1. Block → Moments (via `moment_indices`)
2. Moment → Plays (via `play_ids`)
3. Play → Source data (via PBP records)

---

## 5. Embedded Social Posts

Blocks may contain an embedded social post ID that adds social context.

**Constraints:**

- Maximum 5 embedded social posts per game
- Maximum 1 embedded social post per block
- Social posts are optional — removing all social posts produces the same game flow structure
- Social posts do not influence narrative content

**Backfill:** When the pipeline runs before social scraping completes, all
blocks may have `embedded_social_post_id = NULL`. A post-generation backfill
attaches tweet references once social data becomes available. This is the
sole permitted mutation to a finalized game flow — block structure, roles,
narratives, and `story_role` are never altered.

**Selection criteria:**

- In-game posts preferred over pregame/postgame
- High engagement and media content preferred
- Assigned to blocks by temporal matching (tweet `posted_at` matched to block time windows)

---

## 6. Guardrail Invariants (Non-Negotiable)

The structural / stylistic guardrails:

| Invariant | Limit | Enforcement |
|-----------|-------|-------------|
| Block count | 3–7 | Pipeline fails on violation |
| Embedded social posts | ≤ 5 per game | Hard cap enforced |
| Social post per block | ≤ 1 | Hard cap enforced |
| Total words | ≤ 600 | Warning, not failure |
| Words per block | 30–120 | Warning, not failure |
| Sentences per block | 1–5 | Warning, not failure |
| Read time | 60–90 seconds | Implicit via word limits |

Voice contract rules (FAIL on violation, enforced in
`stages/validate_blocks_voice.py` + `stages/validate_blocks_segments.py`):

| Rule | Module | What it enforces |
|------|--------|------------------|
| Rule 4 — Score continuity | `validate_blocks_rules.py` | `score_after[N] == score_before[N+1]` |
| Rule 13 — Late blowout leverage | `validate_blocks_segments.py` | Late blocks of a blowout cannot imply uncertainty |
| Rule 14 — Low-event drama | `validate_blocks_segments.py` | Low-event archetypes cannot use exaggerated dominance |
| Rule 17 — No repeated final score | `validate_blocks_voice.py` | Final score appears at most once across narratives |
| Rule 18 — Featured players have reason | `validate_blocks_voice.py` | Every `featured_players` entry has a non-empty structured reason |
| Rule 19 — `story_role` present | `validate_blocks_voice.py` | Every block has a `story_role` from `VALID_STORY_ROLES` |

Violations fail the pipeline and are logged at ERROR level with full context.

---

## 7. Social Independence

**Zero required social dependencies.** The game flow structure must be
identical with or without social data.

Validation checks:

- Block count is identical with/without social
- Block narratives are identical with/without social
- Structural roles and `story_role` are identical with/without social

Social content (embedded social posts) is additive, never structural.

---

## 8. Success Criteria

A Game Flow output is correct if and only if:

### Structural Tests

- [ ] The game flow contains 3–7 blocks
- [ ] Each block has a structural `role` and a `story_role`
- [ ] First block is SETUP, last block is RESOLUTION
- [ ] No structural role appears more than twice
- [ ] Score continuity across block boundaries (Rule 4)

### Narrative Tests

- [ ] Each narrative is 30–120 words
- [ ] Each narrative has 1–5 sentences
- [ ] Total word count ≤ 600
- [ ] No forbidden phrases (`render_validation.BANNED_PHRASES`)
- [ ] No retrospective commentary
- [ ] No raw PBP artifacts (initials, score artifacts)
- [ ] Final score is mentioned at most once across the flow (Rule 17)
- [ ] Every `featured_players` entry carries a structured reason (Rule 18)

### Traceability Tests

- [ ] Each block maps to moments via `moment_indices`
- [ ] Each moment maps to plays via `play_ids`
- [ ] All play references exist in source PBP

### Social Independence Tests

- [ ] Removing embedded social posts changes nothing but social post fields
- [ ] Block count, roles, story_role, and narratives are social-independent

---

## 9. Verification Questions

A compliant system answers these questions for any output:

1. "How many blocks?" → 3–7
2. "What structural role is block N?" → One of the structural roles
3. "What story role is block N?" → One of the seven `VALID_STORY_ROLES`
4. "Which plays back this block?" → Via moments → plays
5. "Total read time?" → 60–90 seconds
6. "Does this work without social?" → Yes, identical structure

---

## Document Status

This contract is binding. Implementation must conform to these definitions
and constraints. Amendments require explicit revision of this document.
