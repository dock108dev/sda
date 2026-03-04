# Game Flow Guide

> Integration guide for consuming apps (Scroll Down to Update, etc.)

This guide explains how to fetch and display the **Game Flow** — compact narrative blocks with mini box scores.

---

## Quick Start

```bash
# Get games with game flow for a date
curl -H "X-API-Key: YOUR_KEY" \
  "https://sports-data-admin.dock108.ai/api/admin/sports/games?startDate=2026-01-22&league=NBA"

# Get the game flow for a specific game
curl -H "X-API-Key: YOUR_KEY" \
  "https://sports-data-admin.dock108.ai/api/admin/sports/games/123/flow"
```

---

## What You Get

Each game flow contains **3-7 narrative blocks** designed for a **60-90 second read**.

| Property | Value |
|----------|-------|
| Blocks per game | 3-7 |
| Words per block | 30-100 (~65 avg) |
| Sentences per block | 2-4 |
| Total words | ≤ 600 |
| Read time | 60-90 seconds |

---

## Team Colors (Clash-Resolved)

All game responses include **clash-resolved team colors** — ready-to-use hex values for light and dark mode. No client-side color lookup or clash detection needed.

| Field | Description |
|-------|-------------|
| `homeTeamAbbr` / `awayTeamAbbr` | Team abbreviation (e.g. `"LAL"`, `"GSW"`) |
| `homeTeamColorLight` / `awayTeamColorLight` | Hex color for light backgrounds |
| `homeTeamColorDark` / `awayTeamColorDark` | Hex color for dark backgrounds |

**Clash detection:** When two teams' light-mode colors are too visually similar (Euclidean RGB distance < 0.12), the **home** team's colors are replaced with neutral black (`#000000`) / white (`#FFFFFF`). This matches the iOS app's existing behavior — the server does it once instead of every client independently.

---

## API Endpoints

### 1. List Games

```http
GET /api/admin/sports/games
X-API-Key: YOUR_KEY
```

**Key Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `league` | `string` | `NBA`, `NHL`, `NCAAB`, or `MLB` |
| `startDate` | `date` | Games on/after (Eastern Time) |
| `endDate` | `date` | Games on/before (Eastern Time) |
| `limit` | `int` | Max results (default 50, max 200) |

**Example:**
```bash
GET /api/admin/sports/games?league=NBA&startDate=2026-01-22&endDate=2026-01-22
```

**Response:**
```json
{
  "games": [
    {
      "id": 123,
      "leagueCode": "NBA",
      "gameDate": "2026-01-23T03:00:00Z",
      "homeTeam": "Lakers",
      "awayTeam": "Warriors",
      "homeScore": 112,
      "awayScore": 108,
      "hasFlow": true,
      "homeTeamAbbr": "LAL",
      "awayTeamAbbr": "GSW",
      "homeTeamColorLight": "#FDB927",
      "homeTeamColorDark": "#552583",
      "awayTeamColorLight": "#006BB6",
      "awayTeamColorDark": "#FDB927",
      "isLive": false,
      "isFinal": true,
      "isPregame": false,
      "isTrulyCompleted": true,
      "readEligible": true,
      "currentPeriodLabel": "Q4",
      "dateSection": "Yesterday",
      "liveSnapshot": null
    }
  ],
  "total": 12,
  "withFlowCount": 10
}
```

**New fields (all nullable, additive — no breakage):**
- `isLive`, `isFinal`, `isPregame`, `isTrulyCompleted`, `readEligible` — status convenience booleans
- `currentPeriodLabel` — league-aware period label ("Q4", "2nd Half", "P3", "OT")
- `dateSection` — date grouping in US Eastern ("Today", "Yesterday", "Tomorrow", "Earlier", "Upcoming")
- `liveSnapshot` — at-a-glance live state (periodLabel, timeLabel, scores, clock)

Games with `"hasFlow": true` have game flow available.

---

### 2. Get Game Flow

```http
GET /api/admin/sports/games/{gameId}/flow
X-API-Key: YOUR_KEY
```

**Response:**
```json
{
  "gameId": 123,
  "homeTeam": "Lakers",
  "awayTeam": "Warriors",
  "homeTeamAbbr": "LAL",
  "awayTeamAbbr": "GSW",
  "homeTeamColorLight": "#FDB927",
  "homeTeamColorDark": "#552583",
  "awayTeamColorLight": "#006BB6",
  "awayTeamColorDark": "#FDB927",
  "leagueCode": "NBA",
  "flow": {
    "blocks": [...],
    "moments": [...]
  },
  "plays": [...],
  "validationPassed": true,
  "validationErrors": []
}
```

---

## Block Structure

Blocks are the consumer-facing output. Each block is a narrative segment:

```json
{
  "blockIndex": 0,
  "role": "SETUP",
  "momentIndices": [0, 1, 2],
  "periodStart": 1,
  "periodEnd": 1,
  "scoreBefore": [0, 0],
  "scoreAfter": [15, 12],
  "playIds": [1, 2, 3, 4, 5],
  "keyPlayIds": [2, 4],
  "narrative": "The Lakers jumped out early, with James orchestrating a 15-12 lead through balanced scoring in the opening minutes.",
  "miniBox": {
    "home": {
      "team": "Lakers",
      "players": [
        {"name": "James", "pts": 8, "reb": 2, "ast": 3, "deltaPts": 8, "deltaReb": 2, "deltaAst": 3},
        {"name": "Davis", "pts": 7, "reb": 3, "ast": 0, "deltaPts": 7, "deltaReb": 3, "deltaAst": 0}
      ]
    },
    "away": {
      "team": "Warriors",
      "players": [
        {"name": "Curry", "pts": 6, "reb": 0, "ast": 2, "deltaPts": 6, "deltaReb": 0, "deltaAst": 2}
      ]
    },
    "blockStars": ["James", "Davis"]
  },
  "embeddedSocialPostId": null
}
```

### Block Fields

| Field | Type | Description |
|-------|------|-------------|
| `blockIndex` | `int` | Position (0 to N-1) |
| `role` | `string` | Semantic role (see below) |
| `scoreBefore` | `[away, home]` | Score at block start |
| `scoreAfter` | `[away, home]` | Score at block end |
| `narrative` | `string` | 2-4 sentences (~65 words) |
| `miniBox` | `object` | Player stats for this segment |
| `embeddedSocialPostId` | `number?` | Optional social post ID (max 1 per block) |

### Semantic Roles

| Role | Position | Description |
|------|----------|-------------|
| `SETUP` | Always first | How the game started, early context |
| `MOMENTUM_SHIFT` | Middle | First meaningful swing in the game |
| `RESPONSE` | Middle | Counter-run or stabilization |
| `DECISION_POINT` | Late | The sequence that decided the outcome |
| `RESOLUTION` | Always last | How the game ended |

---

## Mini Box Score

The `miniBox` shows player stats **for that specific segment** of the game.

### Basketball (NBA/NCAAB)

```json
{
  "home": {
    "team": "Lakers",
    "players": [
      {
        "name": "James",
        "pts": 15,          // Cumulative through this block
        "reb": 4,
        "ast": 6,
        "deltaPts": 7,      // Scored during THIS block
        "deltaReb": 2,
        "deltaAst": 3
      }
    ]
  },
  "away": {...},
  "blockStars": ["James", "Curry"]  // Top performers in this segment
}
```

### Hockey (NHL)

```json
{
  "home": {
    "team": "Kings",
    "players": [
      {
        "name": "Kopitar",
        "goals": 1,
        "assists": 1,
        "deltaGoals": 1,
        "deltaAssists": 0
      }
    ]
  },
  "away": {...},
  "blockStars": ["Kopitar"]
}
```

### Stat Fields

Mini box scores are stripped to PRA-only stats (points, rebounds, assists for basketball; goals, assists for hockey).

| Field | Basketball | Hockey |
|-------|------------|--------|
| Cumulative | `pts`, `reb`, `ast` | `goals`, `assists` |
| Delta (this block) | `deltaPts`, `deltaReb`, `deltaAst` | `deltaGoals`, `deltaAssists` |

**Display tip:** Use `delta*` fields to highlight who contributed most in each block. The `blockStars` array identifies top performers.

---

## Embedded Social Posts

Blocks may include an optional embedded social post ID for social context. Only **in-game** posts are embedded in blocks (pregame/postgame posts are excluded).

```json
{
  "embeddedSocialPostId": 456
}
```

The `embeddedSocialPostId` references a social post from the `socialPosts` array in `GET /games/{gameId}`. Use the ID to look up the full post details.

**Constraints:**
- Max 5 embedded social posts per game
- Max 1 embedded social post per block
- Only in-game posts are eligible for embedding
- Social posts are additive context, not structural

---

## Social Posts

The `GET /games/{gameId}` response includes a `socialPosts` array with all tweets mapped to the game, sorted by total interactions (likes + retweets + replies) descending.

```json
{
  "socialPosts": [
    {
      "id": 456,
      "postUrl": "https://x.com/Lakers/status/...",
      "postedAt": "2026-01-23T03:00:00Z",
      "hasVideo": true,
      "teamAbbreviation": "LAL",
      "tweetText": "Let's go Lakers!",
      "videoUrl": "https://...",
      "imageUrl": null,
      "sourceHandle": "Lakers",
      "mediaType": "video",
      "gamePhase": "pregame",
      "likesCount": 1200,
      "retweetsCount": 340,
      "repliesCount": 89
    }
  ]
}
```

**Fields:**
- `gamePhase`: `"pregame"`, `"in_game"`, or `"postgame"` — consuming apps should group by phase for section display
- `likesCount`, `retweetsCount`, `repliesCount`: Interaction metrics (may be null if not yet collected)
- Sorted by total interactions descending

**Display layout:**
```
┌─ Pregame ──────────────────────┐
│ @Lakers: Let's go Lakers! 💜💛 │
│ @warriors: Game day!           │
└────────────────────────────────┘

┌─ In-Game ──────────────────────┐
│ @Lakers: AD with the SLAM! 🔨 │  ← also embedded in blocks
│ @warriors: Steph from deep!    │
└────────────────────────────────┘

┌─ Postgame ─────────────────────┐
│ @Lakers: W! 💜💛               │
└────────────────────────────────┘
```

---

## TypeScript Types

```typescript
interface GameFlowResponse {
  gameId: number;
  homeTeam: string | null;
  awayTeam: string | null;
  homeTeamAbbr: string | null;
  awayTeamAbbr: string | null;
  homeTeamColorLight: string | null;   // Clash-resolved hex color
  homeTeamColorDark: string | null;
  awayTeamColorLight: string | null;
  awayTeamColorDark: string | null;
  leagueCode: string | null;
  flow: {
    blocks: GameFlowBlock[];
    moments: GameFlowMoment[];
  };
  plays: GameFlowPlay[];
  validationPassed: boolean;
  validationErrors: string[];
}

interface GameFlowBlock {
  blockIndex: number;
  role: "SETUP" | "MOMENTUM_SHIFT" | "RESPONSE" | "DECISION_POINT" | "RESOLUTION";
  momentIndices: number[];
  periodStart: number;
  periodEnd: number;
  scoreBefore: [number, number];  // [away, home]
  scoreAfter: [number, number];   // [away, home]
  playIds: number[];
  keyPlayIds: number[];
  narrative: string;
  miniBox: BlockMiniBox | null;
  embeddedSocialPostId?: number | null;
}

interface BlockMiniBox {
  home: BlockTeamMiniBox;
  away: BlockTeamMiniBox;
  blockStars: string[];
}

interface BlockTeamMiniBox {
  team: string;
  players: BlockPlayerStat[];
}

interface BlockPlayerStat {
  name: string;
  // Basketball (PRA only)
  pts?: number;
  reb?: number;
  ast?: number;
  deltaPts?: number;
  deltaReb?: number;
  deltaAst?: number;
  // Hockey
  goals?: number;
  assists?: number;
  deltaGoals?: number;
  deltaAssists?: number;
}

type GamePhase = "pregame" | "in_game" | "postgame";

interface SocialPostEntry {
  id: number;
  postUrl: string;
  postedAt: string;           // ISO 8601
  hasVideo: boolean;
  teamAbbreviation: string;
  tweetText: string | null;
  videoUrl: string | null;
  imageUrl: string | null;
  sourceHandle: string | null;
  mediaType: string | null;
  gamePhase: GamePhase | null;
  likesCount: number | null;
  retweetsCount: number | null;
  repliesCount: number | null;
}
```

---

## Swift Integration Example

```swift
struct GameFlowResponse: Codable {
    let gameId: Int
    let homeTeam: String?
    let awayTeam: String?
    let homeTeamAbbr: String?
    let awayTeamAbbr: String?
    let homeTeamColorLight: String?   // Clash-resolved hex color
    let homeTeamColorDark: String?
    let awayTeamColorLight: String?
    let awayTeamColorDark: String?
    let leagueCode: String?
    let flow: GameFlowContent
    let plays: [GameFlowPlay]
    let blocks: [GameFlowBlock]?
    let validationPassed: Bool
    let validationErrors: [String]
}

struct GameFlowBlock: Codable {
    let blockIndex: Int
    let role: String
    let scoreBefore: [Int]
    let scoreAfter: [Int]
    let narrative: String
    let miniBox: BlockMiniBox?
    let embeddedSocialPostId: Int?
}

struct BlockMiniBox: Codable {
    let home: BlockTeamMiniBox
    let away: BlockTeamMiniBox
    let blockStars: [String]
}

struct BlockTeamMiniBox: Codable {
    let team: String
    let players: [BlockPlayerStat]
}

struct BlockPlayerStat: Codable {
    let name: String
    let pts: Int?
    let reb: Int?
    let ast: Int?
    let deltaPts: Int?
    let deltaReb: Int?
    let deltaAst: Int?
}

// Fetch game flow
func fetchGameFlow(gameId: Int) async throws -> GameFlowResponse {
    var request = URLRequest(url: URL(string: "https://sports-data-admin.dock108.ai/api/admin/sports/games/\(gameId)/flow")!)
    request.setValue(apiKey, forHTTPHeaderField: "X-API-Key")
    let (data, _) = try await URLSession.shared.data(for: request)
    return try JSONDecoder().decode(GameFlowResponse.self, from: data)
}
```

---

## Display Layout

```
┌─────────────────────────────────────────┐
│ SETUP                        0-0 → 15-12│
│ The Lakers jumped out early...          │
│ ┌─────────────────────────────────────┐ │
│ │ LAL: James 8p/2r/3a  Davis 7p/3r   │ │
│ │ GSW: Curry 6p/2a                    │ │
│ └─────────────────────────────────────┘ │
└─────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────┐
│ MOMENTUM_SHIFT              15-12 → 28-32│
│ The Warriors answered with a 20-13 run..│
│ ┌─────────────────────────────────────┐ │
│ │ GSW: Curry +12p  Thompson +8p       │ │
│ │ LAL: James +5p                      │ │
│ └─────────────────────────────────────┘ │
│ @warriors: Splash Brothers cooking!     │
└─────────────────────────────────────────┘
          │
          ▼
        [...]
```

### Design Tips

1. **Use semantic roles for visual hierarchy** — Style SETUP/RESOLUTION differently from middle blocks
2. **Highlight delta stats** — Show what happened in each segment, not just cumulative totals
3. **Score progression** — Display `scoreBefore → scoreAfter` to show the swing
4. **Block stars** — Bold or highlight players in `blockStars` array
5. **Tweets are optional** — Don't leave empty space if no tweet exists

---

## Error Handling

| Status | Meaning |
|--------|---------|
| `200` | Success |
| `401` | Invalid or missing API key |
| `404` | Game not found or no game flow exists |
| `500` | Server error |

**No game flow response:**
```json
{
  "detail": "No Game Flow found for game 123"
}
```

---

## Caching

- Game flow structure and narratives do not change after generation — cache aggressively
- The only post-generation mutation is `embeddedSocialPostId` backfill (attaching tweet references to blocks that were initially NULL)
- Recommended: Cache responses for 24 hours
- Games list can be cached for 5-15 minutes

---

## See Also

- [GAMEFLOW_CONTRACT.md](GAMEFLOW_CONTRACT.md) — Authoritative specification (block fields, semantic roles, guardrails, narrative rules)
- [GAMEFLOW_PIPELINE.md](GAMEFLOW_PIPELINE.md) — Pipeline implementation details (8 stages, execution modes)
- [API.md](API.md) — Complete API reference
