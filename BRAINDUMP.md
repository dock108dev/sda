# BRAINDUMP.md — Game Flow / Game Story Data + Flow Audit

## What I’m seeing

The current Game Flow structure is directionally right, but the generated flow does not feel like a real game flow yet.

The issue is not the downstream presentation. Do not focus on UI.

This is a data, segmentation, and narrative-generation problem.

The flow blocks are being split on what appear to be identified key boundaries, which is fine in theory, but the boundaries feel pretty arbitrary in practice. Some games split into innings/quarters that make sense. Others group huge chunks together, split quiet sections apart, or create separate blocks that do not actually represent a meaningful change in the game.

The text itself also reads too much like a generic recap template:

- Team started strong
- Other team responded
- Team maintained control
- Opponent attempted to rally
- Winner secured the victory

That is not the feature.

The feature should explain the actual shape of the game.

---

## Goal

Audit and improve the Game Flow generation pipeline so it produces data-backed, sport-aware, meaningfully segmented game stories.

This should be handled at the data/generation layer only.

The final output should answer:

> What actually changed in the game, when did it change, and why did that segment matter?

Not:

> Here is a polished recap paragraph for each quarter or inning bucket.

---

## Core problem

The current system appears to have two separate issues:

1. **Boundary selection may be arbitrary**
   - Blocks may be splitting on detected key points, but the detected key points do not always map to actual game movement.
   - Some segments are too broad.
   - Some segments are too narrow.
   - Some quiet periods get over-described.
   - Some important scoring windows are flattened into generic text.
2. **Narrative generation is too generic**
   - The text sounds like a recap template.
   - It repeats the same sports phrases across unrelated games.
   - It often describes vibes instead of game-state movement.
   - It sometimes overstates things the data does not prove.
   - It does not consistently explain why a block exists.

---

## Non-goals

Do not work on UI.

Do not redesign tabs, cards, layout, rendering, colors, spacing, reveal mode, or frontend copy placement.

The downstream app can render whatever data this pipeline produces.

This work is only about:

- source data quality
- league support
- normalized event data
- game-state analysis
- boundary detection
- block selection
- evidence selection
- generated narrative quality
- validation
- debug visibility

---

## Desired definition of Game Flow

Game Flow is not a recap.

Game Flow is a compressed, data-grounded timeline of meaningful game-state changes.

Each block should exist because something changed:

- lead created
- lead expanded
- game tied
- lead changed
- opponent response
- scoring run
- shutout/low-event pattern established
- comeback started
- comeback failed
- late pressure mattered
- game became effectively out of reach
- final resolution

If a block does not represent a meaningful change, it should probably be merged, removed, or rewritten.

---

## Current text problems

### Generic phrases to eliminate or heavily penalize

The current flow uses too many phrases like:

```txt
came out strong
set the tone
found their rhythm
renewed energy
tactical adjustments
continued to press their advantage
reasserted control
seized control
unable to capitalize
sparked a surge
brief spark
valiant attempt
remained composed
secured the victory
dominant performance
offensive prowess
defense proved impenetrable
comfortable cushion
commanding lead
eager to set the tone
feeling each other out
```

These phrases make the generated stories feel interchangeable.

They should either be banned outright or treated as validation failures unless explicitly justified by data.

### Unsupported language

Avoid statements about:

- rhythm
- confidence
- energy
- composure
- tactics
- coaching adjustments
- defensive intensity
- offensive cohesion
- intent
- effort
- “wanted it more” style implication

The source data usually does not prove any of that.

The story should stick to:

- score movement
- lead movement
- player contribution
- scoring sequence
- inning/period/clock context
- final margin
- scoring droughts
- response windows
- leverage

---

## Required audit

Trace the full data path

Audit the full Game Flow pipeline from raw data to generated object.

Find:

- where raw play-by-play is ingested
- where plays are normalized
- where scoring plays are identified
- where player stats are attached
- where game status/finalization is detected
- where flow generation is triggered
- where segment boundaries are selected
- where prompt/input payload is built
- where generated output is stored
- where validation happens, if any
- where NHL is excluded or failing
- where stale or partial flow data can persist

Document every file involved.

---

## NHL gap

We do not appear to have Game Flow for NHL.

This needs a direct audit.

Find out whether NHL is missing because:

- NHL play-by-play is not ingested
- NHL goals are not normalized as scoring plays
- NHL final games are not queued for flow generation
- NHL is excluded by a league whitelist
- NHL source events do not map into the generic flow model
- NHL player/team stats are missing required fields
- the generator throws and silently skips
- the data exists but no flow record is written
- stale cache / previous empty output is being reused
- flow generation only supports NBA/MLB/NCAAB today

Expected result:

- NHL should have a minimum goal-based Game Flow if goals and final score exist.
- If NHL cannot generate flow, the backend should store/log a specific reason.
- It should not silently return nothing.

Minimum NHL flow inputs:

- final score
- goals by period
- scoring team
- scorer
- assist info if available
- score after goal
- power play / short-handed / empty-net flags if available
- overtime / shootout marker if available
- shots by period if available, but not required

---

## Boundary / segmentation review

The current split logic needs a serious review.

It may already be trying to split on key boundaries, but from the outputs it looks like the boundaries are not consistently meaningful.

Boundary selection should be based on game-state movement

Potential boundary triggers:

- first score
- first meaningful lead
- lead change
- tie
- scoring run starts/ends
- multi-run inning
- multi-goal period
- double-digit lead created
- lead cut below key threshold
- late game one-possession / one-score window
- game becomes effectively out of reach
- overtime / shootout
- empty-net goal
- final meaningful scoring play

Boundary selection should not be based only on:

- quarter ends
- inning ends
- fixed time intervals
- every scoring play
- arbitrary “key moment” labels without score-state impact
- top player stat accumulation alone

Quarter/period/inning labels are useful context, but they should not be the main reason a block exists.

---

## Segment quality rules

Each segment should have:

1. A reason to exist
    - What changed in the game during this segment?
2. A start and end game state
    - Score before / after if available.
    - Lead before / after if available.
3. Evidence
    - Scoring plays, runs, goals, lead changes, or key stat events.
4. A narrative job
    - Opening break
    - Response
    - Separation
    - Stall
    - Swing
    - Failed comeback
    - Closeout
    - Final bookkeeping
5. A compression decision
    - Expand if the segment matters.
    - Compress if it was low leverage.
    - Merge if it does not stand alone.

---

## Game shape should be determined before writing

Do not ask the model to discover the story from raw plays.

Create a deterministic game shape object first.

The pipeline should be:

```text
raw plays / stats
  -> normalized scoring events
  -> score timeline
  -> lead timeline
  -> sport-specific game shape classification
  -> segment boundary selection
  -> evidence selection
  -> constrained narrative generation
  -> validation
  -> persisted flow object
```

Not:

```text
raw plays
  -> generic LLM summary
  -> saved story
```

---

## Game shape classification

Before generating text, classify the game.

Possible archetypes:

### Wire-to-wire

One team created an early lead and never gave it back.

The flow should explain:

- when the lead was created
- whether the opponent ever seriously threatened
- how the leader kept distance

### Comeback

One team trailed meaningfully and came back.

The flow should explain:

- size of deficit
- when comeback started
- when game tied/flipped
- who drove the swing
- whether it was completed or fell short

### Back-and-forth

Multiple lead changes or ties.

The flow should explain:

- exchange pattern
- biggest swing
- final separation

### Blowout

Game became noncompetitive.

The flow should explain:

- when it got away
- why late action mattered less
- avoid fake drama in late segments

### Low-event / shutout / pitcher’s duel

Few scoring events.

The flow should explain:

- which scoring event mattered most
- whether the losing team had real chances
- why the final stayed low

Do not overstate with words like “impenetrable” unless the underlying data strongly supports it.

### Fake close

Final margin was close but the game was mostly controlled by one team.

The flow should explain:

- why the final score may look closer than the actual flow
- whether the trailing team ever had a true late chance

### Late separation

Game was close until one late segment.

The flow should explain:

- what changed late
- how the final margin was created

---

## League-specific flow logic

### NBA

NBA flow should be driven by:

- scoring runs
- quarter score changes
- lead changes
- ties
- halftime margin
- end-of-third margin
- final margin
- largest lead
- clutch window
- key player scoring bursts
- meaningful team response

Do not generate generic quarter summaries.

A quarter only deserves its own block if it changed the state of the game.

**NBA useful thresholds**

Review and tune:

- lead created: 6+ points
- meaningful lead: 10+ points
- large lead: 15+ points
- comeback pressure: deficit cut by 7+ points
- clutch window: within 5 points inside final 5 minutes
- game out of reach: lead above threshold with limited time left
- scoring run: 8-0 or larger, or sport-adjusted equivalent

**NBA bad output**

> The Celtics found their rhythm in the second quarter, cutting into the 76ers' lead with precise shots and renewed energy.

**NBA better output**

> Boston cut a 13-point first-quarter deficit to five by halftime. That kept Philadelphia from turning the game into an early runaway, but the Celtics still went into the break chasing.

---

### MLB

MLB flow should be scoring-inning driven.

Do not summarize every inning.

Do not split quiet innings unless they create a meaningful drought or missed opportunity pattern.

MLB flow should use:

- first scoring inning
- multi-run innings
- lead changes
- ties
- home runs
- response innings
- bullpen collapse if supported
- inherited runners if available
- shutout context
- final meaningful scoring event
- whether the tying run came to plate late if available

**MLB useful thresholds**

Review and tune:

- multi-run inning: 2+ runs
- major inning: 4+ runs
- blowout threshold: 7+ run margin after 5th or later
- late leverage: tying run on base/plate from 7th onward if available
- low scoring: combined runs <= 4
- shutout: losing team 0 runs
- early avalanche: 4+ runs in first two innings

**MLB bad output**

> The game began with both teams eager to set the tone.

**MLB better output**

> Pittsburgh created the first real break with five runs in the opening inning. Cincinnati answered with two, but the Reds were already chasing before the game settled.

**MLB bad output**

> In the final innings, the Pirates solidified their victory with a couple more runs to seal the game.

**MLB better output**

> By the eighth, the game was already out of reach. Pittsburgh added two more runs, but the late scoring only stretched a result that had already been decided.

---

### NHL

NHL should be goal-sequence driven.

Use:

- goals by period
- first goal
- tying goal
- go-ahead goal
- multi-goal period
- power-play goal
- short-handed goal
- empty-net goal
- goalie pull / late pressure if available
- overtime / shootout outcome
- shots by period if available

**NHL useful thresholds**

Review and tune:

- one-goal game entering third
- two-goal lead entering third
- empty net changes displayed final margin
- OT/SO explicit final segment
- power-play goal as swing only if it changes lead/tie or creates separation
- late tying goal inside final 5 minutes

**NHL example**

> The game stayed tied into the third before Carolina created the first real separation. The empty-netter changed the final margin, but the deciding goal had already forced Toronto to chase late.

---

## Narrative generation rules

The generator should receive:

- league
- final score
- winner
- archetype
- selected segments
- score before/after per segment
- evidence events per segment
- featured players per segment
- banned phrases
- tone rules

The generator should not receive a massive undifferentiated play dump and be asked to “summarize.”

**Required style**

- 1–2 sentences per block
- 25–55 words normally
- plain language
- data-grounded
- no fake drama
- no speculation
- no generic sports recap phrases
- explain why this segment exists
- mention score movement when useful
- mention final score only in the final block unless necessary

**Prompt rules**

Use something like:

```text
Write Scroll Down Sports Game Flow blocks.
You are not writing a generic recap. You are explaining the shape of the game.
Use only the supplied game shape, segment evidence, score movement, and player stats.
Every block must explain why that segment mattered.
Avoid unsupported claims about rhythm, energy, composure, tactics, confidence, effort, or intent.
Avoid generic sports phrases.
If the game was already decided, say so plainly.
If a segment was low leverage, compress it.
Return strict JSON only.
```

---

## Output schema

The persisted flow object should contain enough structured data to debug the story.

Example:

```json
{
  "game_id": "190098",
  "league": "MLB",
  "version": "game-flow-v2",
  "generated_at": "timestamp",
  "archetype": "early_avalanche_blowout",
  "final_score": {
    "away": 7,
    "home": 17
  },
  "winner_team_id": "PIT",
  "source_counts": {
    "plays": 312,
    "scoring_events": 14,
    "lead_changes": 0,
    "ties": 0
  },
  "blocks": [
    {
      "id": "block_1",
      "label": "Opening break",
      "range": "Inning 1",
      "reason": "Pittsburgh built the first meaningful lead.",
      "score_before": "0-0",
      "score_after": "PIT 5, CIN 2",
      "lead_before": 0,
      "lead_after": 3,
      "evidence": [],
      "text": "Pittsburgh created the first real break with five runs in the opening inning. Cincinnati answered with two, but the Reds were already chasing before the game settled."
    }
  ],
  "validation": {
    "status": "passed",
    "warnings": []
  }
}
```

---

## Validation requirements

Post-generation validation should run every time.

Validation should check:

**Data correctness**

- final score matches source
- winner matches source
- player mentions exist in evidence/stats
- scoring plays referenced exist
- segment score_before/after is consistent
- lead movement is consistent
- league-specific required fields exist

**Text quality**

- no banned phrases
- no unsupported speculation
- no repeated opening pattern
- block is not too long
- block has evidence
- text references why the segment matters
- no final-score contradiction

**Segment quality**

- block has a reason
- block has start/end state
- quiet blocks are not over-expanded
- blowout late blocks do not imply fake leverage
- close games include late leverage if present
- lead changes are not skipped
- low-scoring games do not overstate drama

If validation fails, either:

- regenerate with explicit failure feedback, or
- store the flow as failed with reason and do not publish it as a clean flow.

---

## Debug / observability needed

Add enough logging to understand flow failures.

For each generated game, log:

- game id
- league
- final status
- source play count
- scoring event count
- lead change count
- selected archetype
- selected boundaries
- why each boundary was chosen
- why candidate boundaries were rejected
- prompt payload hash or saved debug payload
- generation result
- validation status
- validation warnings/errors
- whether flow was persisted
- if skipped, exact skip reason

For NHL specifically, log:

- whether game was considered
- whether PBP existed
- whether goals were found
- whether flow was attempted
- whether generation failed
- exact failure reason

---

## Boundary audit deliverable

After auditing the existing segmentation, produce a short report with:

**Current boundary algorithm:**

- ...

**Problems found:**

- ...

**Examples:**

- Game 190094: ...
- Game 190098: ...
- Game 190096: ...
- NHL example: ...

**Recommended boundary algorithm:**

- ...

**Files changed:**

- ...

**Validation added:**

- ...

---

## Test cases

Use recent completed games and fixed fixture tests.

### MLB

Test:

- early blowout
- low-scoring shutout
- back-and-forth game
- late separation
- extra innings if available

Required assertions:

- scoring innings drive block boundaries
- quiet innings are merged
- blowouts compress late innings
- shutouts do not use exaggerated language
- final score is correct

### NBA

Test:

- wire-to-wire
- comeback
- close clutch game
- blowout
- fake close

Required assertions:

- scoring runs and lead movement influence boundaries
- halftime/end-third margins are used when meaningful
- late leverage is represented only when real
- no generic quarter recap text

### NHL

Test:

- regulation win
- one-goal game
- empty-net final margin
- overtime
- shootout if supported
- low-scoring game

Required assertions:

- final NHL games generate flow when goals exist
- missing NHL data produces explicit skip reason
- goals drive boundaries
- empty-net goals are treated correctly
- OT/SO is handled explicitly

---

## Acceptance criteria

This work is complete when:

1. Game Flow generation is based on deterministic game-state analysis before narrative generation.
2. Segment boundaries are explainable and not arbitrary.
3. Every block has evidence and a reason to exist.
4. Text no longer sounds like a generic sports recap template.
5. Banned phrases and unsupported claims are caught.
6. NBA and MLB outputs are materially different based on game shape.
7. MLB low-scoring games and blowouts are compressed appropriately.
8. NHL either generates valid goal-based flow or records a clear backend reason why it cannot.
9. Debug logs make it obvious whether a bad flow came from data, boundary selection, prompt generation, validation, or persistence.
10. The downstream app can consume the same or improved flow object without needing to invent meaning itself.

---

## Final principle

The fix is not “make the writing better.”

The fix is:

- better source normalization
- better game-state analysis
- better boundary selection
- better evidence selection
- stricter generation
- validation

The writing should be the last step.

The story should be a readable expression of the game shape, not the thing responsible for discovering the game shape.
