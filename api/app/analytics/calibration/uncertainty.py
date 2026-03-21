"""Uncertainty scoring and conservative probability computation.

Produces confidence tiers, probability penalties, and model-odds
confidence bands from sim variance, profile freshness, market
disagreement, and data quality signals.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.ev import implied_to_american


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Confidence tier → probability penalty (pulls p_true toward 0.5)
TIER_PENALTIES: dict[str, float] = {
    "high": 0.010,
    "medium": 0.020,
    "low": 0.035,
    "very_low": 0.050,
}

# Confidence tier → required edge for action
TIER_REQUIRED_EDGE: dict[str, float] = {
    "high": 0.020,
    "medium": 0.035,
    "low": 0.050,
    "very_low": 1.0,  # effectively no play
}

# Tax / friction buffer added to required edge
TAX_FRICTION_BUFFER: float = 0.005

# Factor weights for uncertainty scoring — shared between
# compute_uncertainty() and model_odds.compute_model_odds()
UNCERTAINTY_WEIGHTS: dict[str, float] = {
    "sim_variance": 0.15,
    "profile_freshness": 0.30,
    "market_disagreement": 0.35,
    "pitcher_data": 0.20,
}


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UncertaintyResult:
    """Uncertainty assessment for a single game prediction."""

    penalty: float
    confidence_tier: str
    factors: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ModelOddsCore:
    """Core model-odds output: probabilities + confidence band + American lines."""

    p_true: float
    p_conservative: float
    p_low: float
    p_high: float
    fair_line_mid: float
    fair_line_conservative: float
    fair_line_low: float
    fair_line_high: float
    uncertainty: UncertaintyResult


# ---------------------------------------------------------------------------
# Uncertainty scoring
# ---------------------------------------------------------------------------


def compute_uncertainty(
    *,
    sim_wp_std_dev: float | None = None,
    profile_games_home: int | None = None,
    profile_games_away: int | None = None,
    market_disagreement: float | None = None,
    pitcher_data_quality: bool = True,
) -> UncertaintyResult:
    """Compute a composite uncertainty score from available signals.

    Each factor contributes a score from 0 (no concern) to 1 (max concern).
    The weighted average determines the confidence tier.

    Args:
        sim_wp_std_dev: Standard deviation of home WP from Monte Carlo sim.
        profile_games_home: Number of games in home team's rolling profile.
        profile_games_away: Number of games in away team's rolling profile.
        market_disagreement: |calibrated_wp - market_wp| (0-1 scale).
        pitcher_data_quality: True if Statcast pitcher data available.

    Returns:
        UncertaintyResult with penalty, tier, and factor breakdown.
    """
    factors: dict[str, float] = {}

    # Factor 1: Sim variance
    if sim_wp_std_dev is not None:
        # At 5000 iterations, std_dev of ~0.007 is normal for a 50/50 game.
        # Bernoulli: sqrt(0.5*0.5/5000) = 0.00707
        # We're looking at whether the std_dev is unusually high relative
        # to what we'd expect, which indicates the sim itself is noisy.
        # But since this is Bernoulli, it's primarily a function of p and n.
        # We use it as a sanity signal — very high means something odd.
        if sim_wp_std_dev > 0.02:
            factors["sim_variance"] = 0.8
        elif sim_wp_std_dev > 0.015:
            factors["sim_variance"] = 0.4
        else:
            factors["sim_variance"] = 0.0
    else:
        factors["sim_variance"] = 0.5  # Unknown → moderate concern

    # Factor 2: Profile freshness (min of both teams)
    min_games = min(
        profile_games_home or 0,
        profile_games_away or 0,
    )
    if min_games == 0:
        factors["profile_freshness"] = 1.0  # No profile data
    elif min_games < 5:
        factors["profile_freshness"] = 0.8
    elif min_games < 10:
        factors["profile_freshness"] = 0.4
    elif min_games < 20:
        factors["profile_freshness"] = 0.2
    else:
        factors["profile_freshness"] = 0.0

    # Factor 3: Market disagreement
    if market_disagreement is not None:
        if market_disagreement > 0.08:
            factors["market_disagreement"] = 1.0
        elif market_disagreement > 0.05:
            factors["market_disagreement"] = 0.7
        elif market_disagreement > 0.03:
            factors["market_disagreement"] = 0.3
        else:
            factors["market_disagreement"] = 0.0
    else:
        factors["market_disagreement"] = 0.3  # No market data → mild concern

    # Factor 4: Pitcher data quality
    factors["pitcher_data"] = 0.0 if pitcher_data_quality else 0.5

    # Weighted average → tier (uses shared UNCERTAINTY_WEIGHTS)
    score = sum(factors.get(k, 0) * w for k, w in UNCERTAINTY_WEIGHTS.items())

    if score < 0.15:
        tier = "high"
    elif score < 0.35:
        tier = "medium"
    elif score < 0.55:
        tier = "low"
    else:
        tier = "very_low"

    penalty = TIER_PENALTIES[tier]

    return UncertaintyResult(
        penalty=penalty,
        confidence_tier=tier,
        factors=factors,
    )


# ---------------------------------------------------------------------------
# Conservative probability & confidence band
# ---------------------------------------------------------------------------


def apply_uncertainty(
    p_true: float,
    uncertainty: UncertaintyResult,
) -> ModelOddsCore:
    """Apply uncertainty to produce conservative probability and confidence band.

    The conservative probability pulls p_true toward 0.5 by the penalty amount.
    The confidence band is p_true ± (penalty * 1.5) for a wider visual range.

    Args:
        p_true: Calibrated (or raw) true probability (0-1).
        uncertainty: Uncertainty assessment from compute_uncertainty().

    Returns:
        ModelOddsCore with probabilities and American odds conversions.
    """
    penalty = uncertainty.penalty

    # Pull toward 0.5
    if p_true > 0.5:
        p_conservative = max(0.5, p_true - penalty)
    else:
        p_conservative = min(0.5, p_true + penalty)

    # Confidence band: wider than the penalty for display purposes
    band_width = penalty * 1.5
    p_low = max(0.01, p_true - band_width)
    p_high = min(0.99, p_true + band_width)

    # Convert to American odds
    fair_line_mid = implied_to_american(p_true) if 0.01 < p_true < 0.99 else 0.0
    fair_line_conservative = implied_to_american(p_conservative) if 0.01 < p_conservative < 0.99 else 0.0
    fair_line_low = implied_to_american(p_low)
    fair_line_high = implied_to_american(p_high)

    return ModelOddsCore(
        p_true=round(p_true, 4),
        p_conservative=round(p_conservative, 4),
        p_low=round(p_low, 4),
        p_high=round(p_high, 4),
        fair_line_mid=round(fair_line_mid, 1),
        fair_line_conservative=round(fair_line_conservative, 1),
        fair_line_low=round(fair_line_low, 1),
        fair_line_high=round(fair_line_high, 1),
        uncertainty=uncertainty,
    )
