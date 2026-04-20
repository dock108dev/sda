"""Tests for Grafana alert rule provisioning files (ISSUE-020).

Validates:
- All 4 alert JSON files are present and structurally correct.
- Evaluation intervals satisfy the "fires within 5 min" acceptance criterion.
- Alert condition math matches the documented thresholds.
- Metric names referenced in PromQL match the names emitted by the metrics modules.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ALERTS_DIR = Path(__file__).resolve().parents[2] / "infra" / "grafana" / "alerts"

ALERT_FILES = {
    "quality-regression": ALERTS_DIR / "quality-regression.json",
    "social-collection-health": ALERTS_DIR / "social-collection-health.json",
    "odds-budget": ALERTS_DIR / "odds-budget.json",
    "score-mismatch": ALERTS_DIR / "score-mismatch.json",
}

pytestmark = pytest.mark.skipif(
    not ALERTS_DIR.is_dir(),
    reason=f"Grafana alert provisioning directory not present at {ALERTS_DIR}",
)


def _load(name: str) -> dict:
    path = ALERT_FILES[name]
    assert path.exists(), f"Alert file missing: {path}"
    return json.loads(path.read_text())


# ---------------------------------------------------------------------------
# Structural / presence checks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", list(ALERT_FILES))
def test_alert_file_parses(name: str) -> None:
    data = _load(name)
    assert data.get("apiVersion") == 1
    assert "groups" in data, f"{name}: missing 'groups' key"
    assert len(data["groups"]) > 0


@pytest.mark.parametrize("name", list(ALERT_FILES))
def test_alert_has_contact_point(name: str) -> None:
    data = _load(name)
    cps = data.get("contactPoints", [])
    assert len(cps) > 0, f"{name}: no contactPoints defined"
    recv = cps[0]["receivers"][0]
    assert recv["settings"].get("url") == "${ALERT_WEBHOOK_URL}"


@pytest.mark.parametrize("name", list(ALERT_FILES))
def test_alert_group_has_rules(name: str) -> None:
    data = _load(name)
    for group in data["groups"]:
        assert len(group.get("rules", [])) > 0, (
            f"{name}: group '{group['name']}' has no rules"
        )


# ---------------------------------------------------------------------------
# Evaluation interval requirements
# AC: quality-score alert fires within 5 min → interval must be ≤ 5m
# AC: score-mismatch fires immediately → interval must be ≤ 5m
# ---------------------------------------------------------------------------

_INTERVAL_MINUTES = {"5m": 5, "10m": 10, "15m": 15, "1h": 60, "30m": 30}


def _interval_minutes(s: str) -> int:
    return _INTERVAL_MINUTES.get(s, 999)


def test_quality_regression_interval_within_5m() -> None:
    data = _load("quality-regression")
    for group in data["groups"]:
        mins = _interval_minutes(group["interval"])
        assert mins <= 5, (
            f"quality-regression group '{group['name']}' interval '{group['interval']}' "
            "exceeds 5 min — alert cannot fire within 5 min of threshold breach"
        )


def test_score_mismatch_interval_within_5m() -> None:
    data = _load("score-mismatch")
    for group in data["groups"]:
        mins = _interval_minutes(group["interval"])
        assert mins <= 5, (
            f"score-mismatch group '{group['name']}' interval '{group['interval']}' "
            "exceeds 5 min — score mismatch page is meant to be immediate"
        )


# ---------------------------------------------------------------------------
# Condition / threshold math validation
# ---------------------------------------------------------------------------


def test_quality_regression_condition_expression() -> None:
    """Alert condition E = D - C - 10 > 0, i.e. yesterday_p50 - today_p50 > 10."""
    data = _load("quality-regression")
    rule = data["groups"][0]["rules"][0]
    assert rule["condition"] == "E"
    expr_node = next(d for d in rule["data"] if d["refId"] == "E")
    expr = expr_node["model"]["expression"]
    # Expression must compute yesterday - today - 10; positive means regression
    assert "$D" in expr and "$C" in expr and "10" in expr, (
        f"Condition expression '{expr}' does not encode 10-point regression threshold"
    )


def test_quality_regression_uses_quality_score_column() -> None:
    """SQL must query the actual quality_score column, not a derived proxy."""
    data = _load("quality-regression")
    rule = data["groups"][0]["rules"][0]
    for node in rule["data"]:
        if node.get("datasourceUid") == "sports-postgres":
            sql = node["model"]["rawSql"]
            assert "quality_score" in sql, (
                f"refId={node['refId']}: SQL does not reference quality_score column"
            )
            assert "quality_score IS NOT NULL" in sql, (
                f"refId={node['refId']}: SQL should filter NULL quality_scores "
                "(rows pre-dating the column migration)"
            )


def test_social_threshold_90pct() -> None:
    """Alert condition E = 0.9 * total - successful > 0, i.e. rate < 90%."""
    data = _load("social-collection-health")
    rule = data["groups"][0]["rules"][0]
    assert rule["condition"] == "E"
    expr_node = next(d for d in rule["data"] if d["refId"] == "E")
    expr = expr_node["model"]["expression"]
    assert "0.9" in expr, f"Social alert expression '{expr}' missing 0.9 threshold"


def test_odds_budget_80pct_threshold() -> None:
    """Alert condition E = projected - 0.80*budget > 0."""
    data = _load("odds-budget")
    rule = data["groups"][0]["rules"][0]
    assert rule["condition"] == "E"
    expr_node = next(d for d in rule["data"] if d["refId"] == "E")
    expr = expr_node["model"]["expression"]
    assert "$C" in expr and "$D" in expr, (
        f"Odds alert expression '{expr}' must reference both projected (C) and budget (D)"
    )
    # Budget query B must contain the 0.80 multiplier
    budget_node = next(d for d in rule["data"] if d["refId"] == "B")
    budget_expr = budget_node["model"]["expr"]
    assert "0.80" in budget_expr or "0.8" in budget_expr, (
        f"Odds budget query '{budget_expr}' missing 80% threshold"
    )


def test_score_mismatch_fires_on_any_increment() -> None:
    """Score mismatch alert fires when count > 0 (condition B = reduce of A)."""
    data = _load("score-mismatch")
    rule = data["groups"][0]["rules"][0]
    assert rule["condition"] == "B"
    reduce_node = next(d for d in rule["data"] if d["refId"] == "B")
    assert reduce_node["model"]["type"] == "reduce"
    assert reduce_node["model"]["expression"] == "A"


# ---------------------------------------------------------------------------
# Metric name alignment: PromQL names must match OTel instrument names
# (OTel → Prometheus: dots→underscores, counter suffix _total added by collector)
# ---------------------------------------------------------------------------


def test_social_metric_name_matches_otel_instrument() -> None:
    """social.scrape.result → social_scrape_result_total in Prometheus."""
    data = _load("social-collection-health")
    rule = data["groups"][0]["rules"][0]
    for node in rule["data"]:
        model = node.get("model", {})
        if model.get("datasource", {}).get("type") == "prometheus":
            expr = model.get("expr", "")
            assert "social_scrape_result_total" in expr, (
                f"refId={node['refId']}: expected 'social_scrape_result_total' "
                f"in PromQL expression, got: {expr!r}"
            )


def test_score_mismatch_metric_name_matches_otel_instrument() -> None:
    """pipeline.score_mismatch → pipeline_score_mismatch_total in Prometheus."""
    data = _load("score-mismatch")
    rule = data["groups"][0]["rules"][0]
    for node in rule["data"]:
        model = node.get("model", {})
        if model.get("datasource", {}).get("type") == "prometheus":
            expr = model.get("expr", "")
            assert "pipeline_score_mismatch_total" in expr, (
                f"refId={node['refId']}: expected 'pipeline_score_mismatch_total' "
                f"in PromQL expression, got: {expr!r}"
            )


def test_odds_metric_names_match_otel_instruments() -> None:
    """odds.api.credits_used_today and odds.api.credits_budget_weekly → underscored."""
    data = _load("odds-budget")
    rule = data["groups"][0]["rules"][0]
    prom_nodes = [
        d for d in rule["data"]
        if d.get("model", {}).get("datasource", {}).get("type") == "prometheus"
    ]
    exprs = " ".join(n["model"]["expr"] for n in prom_nodes)
    assert "odds_api_credits_used_today" in exprs
    assert "odds_api_credits_budget_weekly" in exprs


# ---------------------------------------------------------------------------
# Synthetic threshold simulation
# Confirms the alert math fires/clears at boundary values without a live stack.
# ---------------------------------------------------------------------------


def _eval_quality_regression(today_p50: float, yesterday_p50: float) -> bool:
    """Mirrors condition E = D - C - 10 > 0 (D=yesterday, C=today)."""
    return (yesterday_p50 - today_p50 - 10) > 0


def _eval_social_rate(successes: int, total: int) -> bool:
    """Mirrors condition E = 0.9*D - C > 0."""
    if total == 0:
        return False
    return (0.9 * total - successes) > 0


def _eval_odds_budget(projected_weekly: float, weekly_budget: float) -> bool:
    """Mirrors condition E = C - D > 0 (C=projected, D=0.8*budget)."""
    return (projected_weekly - 0.8 * weekly_budget) > 0


def _eval_score_mismatch(count: int) -> bool:
    """Mirrors condition B = reduce(A) > 0."""
    return count > 0


def test_synthetic_quality_regression_fires() -> None:
    assert _eval_quality_regression(today_p50=60.0, yesterday_p50=75.0) is True
    assert _eval_quality_regression(today_p50=60.0, yesterday_p50=70.0) is False
    assert _eval_quality_regression(today_p50=60.0, yesterday_p50=70.1) is True
    assert _eval_quality_regression(today_p50=60.0, yesterday_p50=69.9) is False


def test_synthetic_social_rate_fires() -> None:
    # 80 successes of 100 → 80% < 90% → alert fires
    assert _eval_social_rate(successes=80, total=100) is True
    # 90 successes of 100 → 90% = 90% → does NOT fire (strict inequality)
    assert _eval_social_rate(successes=90, total=100) is False
    # 89 successes of 100 → 89% < 90% → fires
    assert _eval_social_rate(successes=89, total=100) is True
    # No data → no alert
    assert _eval_social_rate(successes=0, total=0) is False


def test_synthetic_odds_budget_fires() -> None:
    # 850 credits projected vs 1000 budget → 85% > 80% → fires
    assert _eval_odds_budget(projected_weekly=850.0, weekly_budget=1000.0) is True
    # 800 credits projected → exactly 80% → does NOT fire
    assert _eval_odds_budget(projected_weekly=800.0, weekly_budget=1000.0) is False
    # 799 credits projected → below 80% → does not fire
    assert _eval_odds_budget(projected_weekly=799.0, weekly_budget=1000.0) is False


def test_synthetic_score_mismatch_fires() -> None:
    assert _eval_score_mismatch(1) is True
    assert _eval_score_mismatch(0) is False
    assert _eval_score_mismatch(5) is True
