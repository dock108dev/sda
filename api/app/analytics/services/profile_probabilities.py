"""Sport profile to simulation probability conversion."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Probability conversion functions
# ---------------------------------------------------------------------------

def profile_to_pa_probabilities(profile: dict[str, float]) -> dict[str, float]:
    """Convert a team's rolling profile metrics into PA event probabilities.

    Maps real team statistics to plate-appearance outcome probabilities
    used by the Monte Carlo game simulator. Teams with better contact
    rates get more hits; teams with higher whiff rates get more
    strikeouts, etc.
    """
    # Extract key metrics with league-average defaults
    whiff = profile.get("whiff_rate", 0.23)
    barrel = profile.get("barrel_rate", 0.07)
    hard_hit = profile.get("hard_hit_rate", 0.35)
    contact = profile.get("contact_rate", 0.77)
    chase = profile.get("chase_rate", 0.32)

    # Map to PA probabilities (league averages as anchors)
    # Higher whiff → more strikeouts
    k_prob = _clamp(0.15 + whiff * 0.35, 0.10, 0.38)

    # Better discipline (less chase) → more walks
    walk_prob = _clamp(0.05 + (1.0 - chase) * 0.06, 0.03, 0.14)

    # Higher barrel rate → more home runs
    hr_prob = _clamp(barrel * 0.45, 0.005, 0.06)

    # Higher hard hit → more doubles
    double_prob = _clamp(0.02 + hard_hit * 0.09, 0.02, 0.09)

    # Triples are rare and mostly speed-based
    triple_prob = 0.008

    # Singles from contact minus extra-base hits
    contact_hitting = _clamp(contact * 0.25, 0.08, 0.22)
    single_prob = max(contact_hitting - hr_prob - double_prob - triple_prob, 0.06)

    # Out probability is the residual
    named_total = k_prob + walk_prob + single_prob + double_prob + triple_prob + hr_prob
    # Ensure we don't exceed 1.0
    if named_total > 0.95:
        scale = 0.95 / named_total
        k_prob *= scale
        walk_prob *= scale
        single_prob *= scale
        double_prob *= scale
        triple_prob *= scale
        hr_prob *= scale

    return {
        "strikeout_probability": round(k_prob, 4),
        "walk_or_hbp_probability": round(walk_prob, 4),
        "single_probability": round(single_prob, 4),
        "double_probability": round(double_prob, 4),
        "triple_probability": round(triple_prob, 4),
        "home_run_probability": round(hr_prob, 4),
    }


def profile_to_nba_probabilities(profile: dict[str, float]) -> dict[str, float]:
    """Convert NBA team metrics to possession event probabilities.

    Maps team advanced stats to per-possession outcome probabilities
    for use by the NBA game simulator.
    """
    efg = profile.get("efg_pct", 0.50)
    tov = profile.get("tov_pct", 0.13)
    fg3 = profile.get("fg3_pct", 0.36)
    ft_rate = profile.get("ft_rate", 0.25)
    orb = profile.get("orb_pct", 0.25)

    # Turnover probability per possession
    turnover_prob = _clamp(tov, 0.05, 0.25)

    # Free-throw trip probability (FTA/FGA ratio scaled to per-possession)
    ft_trip_prob = _clamp(ft_rate * 0.20, 0.02, 0.15)

    # Shot attempt probability is what remains after turnovers and FT trips
    remaining = 1.0 - turnover_prob - ft_trip_prob

    # Of shots attempted, split into makes vs misses using eFG%
    # eFG already accounts for 3PT bonus, so overall make rate ~ eFG
    make_prob = _clamp(remaining * efg, 0.10, 0.55)
    miss_prob = remaining - make_prob

    # Of makes, split into 2PT and 3PT using fg3_pct as a proxy
    # Higher fg3_pct means more 3PT attempts convert
    three_pt_share = _clamp(fg3 * 0.60, 0.10, 0.45)
    three_pt_make_prob = round(make_prob * three_pt_share, 4)
    two_pt_make_prob = round(make_prob * (1.0 - three_pt_share), 4)

    # Offensive rebound probability on misses
    orb_prob = _clamp(orb, 0.15, 0.40)

    return {
        "turnover_probability": round(turnover_prob, 4),
        "ft_trip_probability": round(ft_trip_prob, 4),
        "two_pt_make_probability": two_pt_make_prob,
        "three_pt_make_probability": three_pt_make_prob,
        "miss_probability": round(miss_prob, 4),
        "offensive_rebound_probability": round(orb_prob, 4),
    }


def profile_to_nhl_probabilities(profile: dict[str, float]) -> dict[str, float]:
    """Convert NHL team metrics to shot event probabilities.

    Maps team advanced stats to per-shot outcome probabilities
    for use by the NHL game simulator.
    """
    shooting = profile.get("shooting_pct", 0.09)
    profile.get("save_pct", 0.91)
    xgoals_pct = profile.get("xgoals_pct", 0.50)
    corsi = profile.get("corsi_pct", 0.50)

    # Goal probability per shot attempt — blend shooting_pct with xG signal
    base_goal = _clamp(shooting, 0.03, 0.18)
    # Adjust slightly by xGoals dominance
    xg_adj = (xgoals_pct - 0.50) * 0.04
    goal_prob = _clamp(base_goal + xg_adj, 0.03, 0.18)

    # Save probability (goalie stops it)
    save_prob = _clamp(1.0 - goal_prob - 0.15, 0.55, 0.85)

    # Remaining split between blocked and missed
    remaining = 1.0 - goal_prob - save_prob
    blocked_prob = round(remaining * 0.55, 4)
    missed_prob = round(remaining * 0.45, 4)

    # Possession share from Corsi
    possession_share = _clamp(corsi / 100.0 if corsi > 1.0 else corsi, 0.35, 0.65)

    return {
        "goal_probability": round(goal_prob, 4),
        "save_probability": round(save_prob, 4),
        "blocked_probability": blocked_prob,
        "missed_probability": missed_prob,
        "possession_share": round(possession_share, 4),
    }


def profile_to_ncaab_probabilities(profile: dict[str, float]) -> dict[str, float]:
    """Convert NCAAB team metrics to possession event probabilities.

    Similar to NBA but uses four-factor columns directly.
    """
    efg = profile.get("off_efg_pct", 0.50)
    tov = profile.get("off_tov_pct", 0.18)
    orb = profile.get("off_orb_pct", 0.30)
    ft_rate = profile.get("off_ft_rate", 0.30)

    # Turnover probability per possession (NCAAB tends higher than NBA)
    turnover_prob = _clamp(tov, 0.08, 0.30)

    # Free-throw trip probability
    ft_trip_prob = _clamp(ft_rate * 0.18, 0.02, 0.15)

    # Shot attempt probability is what remains
    remaining = 1.0 - turnover_prob - ft_trip_prob

    # Make vs miss using eFG%
    make_prob = _clamp(remaining * efg, 0.10, 0.50)
    miss_prob = remaining - make_prob

    # Split makes into 2PT and 3PT — NCAAB has lower 3PT rate than NBA
    three_pt_pct = profile.get("three_pt_pct", 0.33)
    three_pt_share = _clamp(three_pt_pct * 0.55, 0.08, 0.40)
    three_pt_make_prob = round(make_prob * three_pt_share, 4)
    two_pt_make_prob = round(make_prob * (1.0 - three_pt_share), 4)

    # Offensive rebound probability on misses
    orb_prob = _clamp(orb, 0.18, 0.45)

    return {
        "turnover_probability": round(turnover_prob, 4),
        "ft_trip_probability": round(ft_trip_prob, 4),
        "two_pt_make_probability": two_pt_make_prob,
        "three_pt_make_probability": three_pt_make_prob,
        "miss_probability": round(miss_prob, 4),
        "offensive_rebound_probability": round(orb_prob, 4),
    }


def profile_to_probabilities(sport: str, profile: dict[str, float]) -> dict[str, float]:
    """Route to sport-specific probability conversion."""
    s = sport.lower()
    if s == "mlb":
        return profile_to_pa_probabilities(profile)
    elif s == "nba":
        return profile_to_nba_probabilities(profile)
    elif s == "nhl":
        return profile_to_nhl_probabilities(profile)
    elif s == "ncaab":
        return profile_to_ncaab_probabilities(profile)
    return {}


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))
