# Advanced Stats — Data Sources (One Free Source Per Sport)

These are **dedicated advanced stats sources** — separate from the scoreboard/PBP APIs we already use for live game data. Each provides the kind of enriched, model-derived metrics that Statcast provides for MLB.

---

## MLB — MLB Stats API (Statcast) [ALREADY IMPLEMENTED]

**Source:** `https://statsapi.mlb.com/api/v1/game/{game_pk}/playByPlay`
**Auth:** None
**Format:** JSON (per-pitch data with exit velocity, launch angle, zone)
**What makes it "advanced":** Every pitch has `hitData.launchSpeed`, `hitData.launchAngle`, `pitchData.zone`, swing/contact codes. We aggregate these into hard-hit rate, barrel rate, plate discipline splits, whiff rate — metrics that don't exist in a boxscore.

---

## NBA — stats.nba.com (via `nba_api` library)

**Source:** `https://stats.nba.com/stats/` (undocumented but well-reverse-engineered endpoints)
**Auth:** None (free, public — but blocks some cloud IPs; works from residential/VPN)
**Format:** JSON
**Library:** [`swar/nba_api`](https://github.com/swar/nba_api) — Python client with 253+ documented endpoints

**Key endpoints for advanced stats:**

| Endpoint | What it provides |
|----------|-----------------|
| `shotchartdetail` | Every shot attempt with `LOC_X`, `LOC_Y`, `SHOT_DISTANCE`, `SHOT_ZONE_BASIC`, `SHOT_ZONE_AREA`, `SHOT_ZONE_RANGE`, `ACTION_TYPE` (driving layup, pullup jumper, etc.), `SHOT_MADE_FLAG` |
| `boxscoreadvancedv3` | Per-player per-game: TS%, eFG%, offensive/defensive rating, usage rate, pace, PIE (player impact estimate) |
| `boxscoreplayertrackingv3` | Per-player per-game: speed, distance, touches, time of possession, contested/uncontested shots, pull-up vs catch-and-shoot |
| `boxscorehustlev2` | Per-player per-game: contested shots, charges drawn, deflections, loose balls recovered, screen assists |
| `playerdashptshots` | Shooting splits by closest defender distance (0-2ft, 2-4ft, 4-6ft, 6+ft, wide open) |

**What we'd aggregate (analogous to Statcast):**
- Shot quality: shot distance distribution, shot zone efficiency, contested vs open shot rates
- Player tracking: speed/distance covered, touches, time of possession
- Hustle: deflections, contested shots, loose balls, charges drawn
- Shooting context: catch-and-shoot vs off-dribble, closest defender distance

**Why this source:** This is NBA's equivalent of Statcast — granular, per-event, per-player tracking data that goes far beyond the boxscore. The `nba_api` library makes it easy to call. Rate-limited but free.

---

## NHL — MoneyPuck (CSV downloads)

**Source:** `https://moneypuck.com/data.htm`
**Auth:** None (free, CC-style license — credit MoneyPuck)
**Format:** CSV (downloadable per season, per game)
**Library:** [`nhldata`](https://github.com/TonyAllenPrice/nhldata) — Python package for MoneyPuck + NHL API data

**Available data:**

| Dataset | What it provides |
|---------|-----------------|
| Shot data | Every shot with 124 attributes: xGoals (expected goals probability), shot distance, shot angle, shot type, rebound flag, rush shot flag, time since last event, shooter/goalie IDs |
| Skater stats | Per-player per-game/season: xGoals for/against, Corsi, Fenwick, on-ice shooting %, on-ice save %, game score, WAR |
| Goalie stats | Per-goalie: xGoals against, goals saved above expected (GSAx), high/medium/low danger save % |
| Team stats | Per-team: xGoals %, Corsi %, Fenwick %, shot quality metrics |

**CSV URL pattern:**
```
https://peter-tanner.com/moneypuck/downloads/shots_{season}.csv
https://moneypuck.com/moneypuck/playerData/seasonSummary/{season}/regular/teams/skaters/{team}.csv
```

**What we'd aggregate (analogous to Statcast):**
- Shot quality: xGoals per shot, high/medium/low danger shot rates
- Player impact: on-ice xGoals %, Corsi rel%, WAR estimates
- Goalie performance: GSAx, danger-zone save %

**Why this source:** MoneyPuck is the hockey analytics community standard. Pre-computed xG model on every shot (124 features), freely downloadable as CSV. This is NHL's Statcast equivalent — raw shot-level data with model-derived quality scores.

---

## NFL — nflverse (via `nflreadpy`)

**Source:** `https://github.com/nflverse/nflverse-data` (hosted on GitHub releases)
**Auth:** None (free, CC-BY 4.0 license)
**Format:** Parquet/CSV (play-by-play with pre-computed EPA, WPA, CPOE)
**Library:** [`nflreadpy`](https://github.com/nflverse/nflreadpy) — Python port of the R nflreadr package

**Available data:**

| Dataset | What it provides |
|---------|-----------------|
| Play-by-play | Every play with pre-computed `epa` (expected points added), `wpa` (win probability added), `cpoe` (completion % over expected), `air_epa`, `yac_epa`, `air_yards`, `yards_after_catch`, `xyac_epa`, `xyac_mean_yardage` |
| Player stats | Per-player weekly/seasonal aggregations with EPA splits |
| Next Gen Stats | Passing: time to throw, air distance, completion probability. Rushing: rush yards over expected, time behind line. Receiving: separation, catch probability |
| Roster data | Player metadata, positions, draft info |

**Python usage:**
```python
import nflreadpy as nfl
pbp = nfl.load_pbp([2025])  # Full season PBP with EPA/WPA/CPOE
```

**What we'd ingest (analogous to Statcast):**
- EPA: per-play expected points added (passing, rushing, receiving splits)
- WPA: win probability added per play
- CPOE: completion probability over expected per pass
- Air yards / YAC splits
- Success rate (EPA > 0)
- Explosive play rate

**Why this source:** nflverse is THE standard for NFL analytics. Pre-computed EPA/WPA/CPOE on every play going back to 1999, updated weekly during the season. ~49K plays per season. Free, open source, well-maintained. This is NFL's Statcast equivalent.

---

## NCAAB — Bart Torvik / T-Rank (via `toRvik`)

**Source:** `https://barttorvik.com/` (stats pages) + `https://torvik.sportsdataverse.org/` (R API)
**Auth:** None (free, public)
**Format:** Structured data via sportsdataverse API / web scraping
**Library:** [`toRvik`](https://torvik.sportsdataverse.org/) — R package (would need Python port or HTTP calls)

**Available data:**

| Dataset | What it provides |
|---------|-----------------|
| Team game stats | Per-game four factors: eFG%, TOV%, ORB%, FT rate — for both offense and defense |
| Player stats | Per-player: offensive/defensive BPM, usage, ORtg, DRtg, stops, game score |
| Shot-level | Shooting by location/type: at-rim, mid-range, three-point — made/missed splits |
| Tempo-free | Adjusted efficiency (adj. offensive/defensive efficiency), strength of schedule adjustments |
| Game predictions | Pre-game win probability, predicted score, T-Rank matchup ratings |

**Alternative — CBB Analytics API:**
If Torvik proves hard to scrape, [`cbbanalytics.com`](https://cbbanalytics.com/) also offers free advanced stats including shot charts and efficiency breakdowns.

**What we'd ingest (analogous to Statcast):**
- Four factors per game (both sides): eFG%, TOV%, ORB%, FT rate
- Adjusted efficiency: adj. OE, adj. DE (strength-of-schedule corrected)
- Shot distribution: at-rim%, mid-range%, 3PT% with made/missed
- Player impact: BPM, usage, game score

**Why this source:** Barttorvik T-Rank is the KenPom alternative that's fully free. It covers every D1 team with tempo-free, schedule-adjusted metrics. The `toRvik` R package provides structured access. For Python, we'd either port the key endpoints or scrape the structured HTML.

---

## Summary

| Sport | Advanced Stats Source | Data Type | Format | Auth | Analog to Statcast |
|-------|----------------------|-----------|--------|------|-------------------|
| **MLB** | MLB Stats API | Pitch-level: exit velo, launch angle, zone | JSON | None | IS Statcast |
| **NBA** | stats.nba.com | Shot-level: location, distance, tracking, hustle | JSON | None (IP restrictions) | Shot charts + player tracking |
| **NHL** | MoneyPuck | Shot-level: xGoals, distance, angle, 124 features | CSV | None (credit required) | xG model on every shot |
| **NFL** | nflverse | Play-level: EPA, WPA, CPOE, air yards, YAC | Parquet/CSV | None (CC-BY) | EPA/WPA on every play |
| **NCAAB** | Bart Torvik | Game-level: four factors, adj. efficiency, shot splits | Web/R API | None | Tempo-free efficiency |

Sources:
- [swar/nba_api (253+ NBA endpoints)](https://github.com/swar/nba_api)
- [MoneyPuck Data Downloads](https://moneypuck.com/data.htm)
- [nflverse/nflreadpy (Python)](https://github.com/nflverse/nflreadpy)
- [nflverse data repository](https://github.com/nflverse/nflverse-data)
- [Bart Torvik T-Rank](https://barttorvik.com/)
- [toRvik R package](https://torvik.sportsdataverse.org/)
