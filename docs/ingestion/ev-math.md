# EV Math — Devig Formulas & Worked Examples

Mathematical walkthrough of how expected value (EV) is computed from sharp book prices. This document should allow a human to manually compute EV for one bet and match the system.

For the full pipeline (ingestion, game matching, eligibility gating, API consumption), see [Odds & FairBet Pipeline](odds-and-fairbet.md).

---

## 1. Implied Probability from American Odds

For American odds `price`:

```
If price >= 100:  implied = 100 / (price + 100)
If price <= -100: implied = |price| / (|price| + 100)
```

Example: `-110` → `110 / (110 + 100)` = **0.5238**

Example: `+150` → `100 / (150 + 100)` = **0.4000**

---

## 2. Shin's Method (Remove Vig)

Pinnacle's implied probabilities on both sides of a market sum to more than 1.0 — the excess is the vig (bookmaker's margin). Shin's model removes this vig while accounting for **favorite-longshot bias**: it shifts more vig correction to longshots, producing fairer true probabilities than simple additive normalization.

### Formula

Given implied probabilities `q_a` and `q_b` for sides A and B:

```python
total = q_a + q_b                 # e.g., 0.5238 + 0.5238 = 1.0476
z = 1.0 - 1.0 / total            # Shin's informed-trading parameter (~0.0454)

# For each implied probability q:
true_prob = (sqrt(z² + 4(1-z)(q²/total)) - z) / (2(1-z))
```

When overround is zero (`z <= 0`), the system falls back to additive normalization: `q / total`.

### Worked Example

Pinnacle: Side A = `-110`, Side B = `-110`

```
implied_a = 110/210 = 0.5238
implied_b = 110/210 = 0.5238
total     = 1.0476
z         = 1 - 1/1.0476 = 0.0454

true_prob_a = (sqrt(0.0454² + 4×0.9546×(0.5238²/1.0476)) - 0.0454) / (2×0.9546)
            ≈ 0.5000
```

With symmetric prices, Shin correctly returns 50/50.

---

## 3. EV Calculation

For each book's price on each side, convert to decimal odds and compute EV%:

```python
# Convert book price to decimal odds
if book_price >= 100:
    decimal_odds = (book_price / 100) + 1.0
elif book_price <= -100:
    decimal_odds = (100 / |book_price|) + 1.0

# EV as a percentage
ev_percent = (decimal_odds * true_prob - 1.0) * 100.0
```

### Worked Examples

Given `true_prob_a ≈ 0.5005` (from Shin devig):

**DraftKings: -105 on side A**
```
decimal_odds = (100 / 105) + 1.0 = 1.9524
ev_percent   = (1.9524 × 0.5005 - 1.0) × 100 ≈ -2.28%
```

**FanDuel: +105 on side A**
```
decimal_odds = (105 / 100) + 1.0 = 2.0500
ev_percent   = (2.0500 × 0.5005 - 1.0) × 100 ≈ +2.60%
```

Positive EV means the book's price offers better value than the fair probability implies.

---

## 4. Annotation

Each book entry gets annotated with:

| Field | Description |
|-------|-------------|
| `ev_percent` | EV percentage (positive = value, negative = bad) |
| `implied_prob` | The book's raw implied probability (before devig) |
| `true_prob` | The devigged true probability from Shin's method |
| `is_sharp` | Whether this book is the sharp reference (Pinnacle) |

Each bet definition gets:

| Field | Description |
|-------|-------------|
| `ev_method` | Derivation method: `"pinnacle_devig"` or `"pinnacle_extrapolated"` |
| `ev_confidence_tier` | `"high"`, `"medium"`, or `"low"` (set per-strategy, not dynamic) |

---

## 5. Fair Odds Sanity Check

After devigging, the fair American odds are compared against the median book price on each side. If the divergence exceeds a per-strategy threshold, the market is flagged `fair_odds_suspect = True`:

```python
fair_american_a = implied_to_american(true_prob_a)
fair_american_b = implied_to_american(true_prob_b)
median_a = median(all book prices on side A)
median_b = median(all book prices on side B)
divergence = max(|fair_american_a - median_a|, |fair_american_b - median_b|)
# If divergence > threshold → fair_odds_suspect = True
```

Thresholds per strategy:

| Strategy | Max Divergence |
|----------|---------------|
| NBA/NHL mainline | 150 |
| NCAAB mainline | 200 |
| Player props | 250 |
| Team props | 200 |
| Alternates | 300 |

When flagged, the API layer sets `ev_disabled_reason = "fair_odds_outlier"` and strips EV annotations. The devig math still runs (annotations are computed), but the caller suppresses display.

---

## See Also

- [Odds & FairBet Pipeline](odds-and-fairbet.md) — Full pipeline: ingestion, matching, eligibility, API consumption
