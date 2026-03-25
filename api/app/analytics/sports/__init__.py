"""Sport-specific analytics plugin modules.

Each subdirectory implements analytics for a single sport, following a
common interface so the core engines can delegate to them uniformly.

Supported sports:
- mlb/   — Major League Baseball (PA-level simulation)
- nba/   — National Basketball Association (possession-based)
- nhl/   — National Hockey League (shot-based with shootout)
- ncaab/ — NCAA Division I Basketball (four-factor possession)

Shared helpers live in ``_helpers.py``.
"""
