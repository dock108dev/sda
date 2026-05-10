"""Negative tests pinning the SSOT cleanup on the `odds_pause` branch.

These assertions fail if deprecated symbols are reintroduced. They exist
because the symbols below were deleted as part of an SSOT consolidation
pass; reintroducing them would re-create the duplicate config / dead-code
paths that this branch removed.

If a future change *intentionally* needs one of these symbols back,
delete the corresponding assertion and update this docstring with the
new owner.
"""

from __future__ import annotations

import importlib


def test_api_side_live_odds_constant_is_not_reintroduced() -> None:
    """`LIVE_ODDS_ENABLED` lives in `scraper/sports_scraper/config_sports.py`.

    The api-side definition was a duplicate with zero callers — keeping
    it would split the SSOT for the live-odds toggle.
    """
    mod = importlib.import_module("app.config_sports")
    assert not hasattr(mod, "LIVE_ODDS_ENABLED"), (
        "api/app/config_sports.py must not re-define LIVE_ODDS_ENABLED — "
        "the SSOT is scraper/sports_scraper/config_sports.py."
    )
    assert not hasattr(mod, "is_live_odds_enabled"), (
        "api/app/config_sports.py must not re-define is_live_odds_enabled() "
        "— the SSOT is scraper/sports_scraper/config_sports.py."
    )


def test_scroll_down_mlb_phase2_stub_deck_is_not_reintroduced() -> None:
    """`service._stub_deck` was a Phase-2 placeholder.

    Phase 5 wires `get_game_deck` to the real `build_deck_from_upstream`
    pipeline; the stub had no callers and contradicted the data-source
    SSOT.
    """
    mod = importlib.import_module("app.scroll_down_mlb.service")
    assert not hasattr(mod, "_stub_deck"), (
        "app.scroll_down_mlb.service must not re-define _stub_deck — "
        "the SSOT is build_deck_from_upstream + load_game_payload."
    )
