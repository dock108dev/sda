"""SSOT guard tests for the canonical team-abbreviation filter.

These tests fail loudly if anyone reintroduces:
- a duplicate ``/mlb/teams`` handler in the simulator router
- ``MLBTeamInfo`` / ``MLBTeamsResponse`` in ``simulator_mlb``
- an inline ``if sport == "mlb"`` canonical-abbr filter in any route handler
  (the SSOT lives in ``app.analytics.sports.team_filters``)

If any of these reappear, fix the offending PR — do not weaken these tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.analytics.sports import team_filters
from app.routers import simulator, simulator_mlb

_REPO_ROOT = Path(__file__).resolve().parents[1] / "app"


def test_canonical_abbrs_ssot_module_exposes_dispatch() -> None:
    """The shared module must expose the dispatch table for all callers."""
    assert hasattr(team_filters, "CANONICAL_TEAM_ABBRS")
    assert hasattr(team_filters, "get_canonical_abbrs")
    # MLB / NBA / NHL all have canonical lists; NCAAB intentionally absent.
    assert team_filters.get_canonical_abbrs("mlb") is not None
    assert team_filters.get_canonical_abbrs("nba") is not None
    assert team_filters.get_canonical_abbrs("nhl") is not None
    assert team_filters.get_canonical_abbrs("ncaab") is None


def test_legacy_mlb_team_classes_are_gone() -> None:
    """MLBTeamInfo / MLBTeamsResponse were deleted — assert they stay deleted."""
    assert not hasattr(simulator_mlb, "MLBTeamInfo"), (
        "MLBTeamInfo was reintroduced. Use the SSOT TeamInfo in simulator.py."
    )
    assert not hasattr(simulator_mlb, "MLBTeamsResponse"), (
        "MLBTeamsResponse was reintroduced. Use the SSOT TeamsResponse."
    )
    assert not hasattr(simulator_mlb, "list_simulator_teams"), (
        "list_simulator_teams was reintroduced. /mlb/teams is served by the "
        "generic /{sport}/teams handler in simulator.py."
    )


def test_simulator_mlb_router_does_not_register_teams_route() -> None:
    """The MLB sub-router must not own /mlb/teams anymore — SSOT is generic."""
    paths = {route.path for route in simulator_mlb.router.routes}
    assert "/mlb/teams" not in paths, (
        "/mlb/teams was reintroduced in simulator_mlb. Delete it — the SSOT "
        "handler in simulator.py covers MLB via _CANONICAL_TEAM_ABBRS."
    )


def test_simulator_module_uses_shared_canonical_filter() -> None:
    """simulator.py must import from the shared SSOT, not a private dict."""
    assert hasattr(simulator, "get_canonical_abbrs"), (
        "simulator.py lost its import of team_filters.get_canonical_abbrs."
    )
    # Belt-and-suspenders: no private dict named _CANONICAL_TEAM_ABBRS lives in
    # the router anymore (it was lifted to the shared module).
    assert not hasattr(simulator, "_CANONICAL_TEAM_ABBRS"), (
        "Private _CANONICAL_TEAM_ABBRS reintroduced in simulator.py — the "
        "SSOT is app.analytics.sports.team_filters.CANONICAL_TEAM_ABBRS."
    )


@pytest.mark.parametrize(
    "relative_path",
    [
        "routers/simulator.py",
        "analytics/api/analytics_routes.py",
    ],
)
def test_no_inline_mlb_only_canonical_filter(relative_path: str) -> None:
    """No route handler may carry ``if sport == "mlb"`` to gate the canonical
    abbreviation filter — that exact pattern was the bug downstream reported,
    and the SSOT dispatch table replaces it.

    Other ``if sport == "mlb"`` checks (probability_mode selection, lineup
    handling, etc.) are legitimate sport-specific config and are not blocked.
    """
    source = (_REPO_ROOT / relative_path).read_text()
    # Tight pattern: the abbr filter, gated on an MLB-only branch.
    forbidden_substrings = (
        'sport_lower == "mlb":\n        stmt = stmt.where(SportsTeam.abbreviation.in_',
        'sport == "mlb":\n        stmt = stmt.where(SportsTeam.abbreviation.in_',
    )
    for needle in forbidden_substrings:
        assert needle not in source, (
            f"{relative_path} contains the legacy MLB-only canonical-abbr "
            f"filter. Replace with `get_canonical_abbrs(sport_lower)` from "
            f"app.analytics.sports.team_filters."
        )
