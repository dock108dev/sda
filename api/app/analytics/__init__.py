"""Analytics framework for sport-agnostic data analysis and simulation.

This package provides the core infrastructure for:
- Team and player analytics profiles
- Matchup analysis across sports
- Simulation engines (Monte Carlo, game-level)
- Derived metric computation

Architecture:
    core/       - Sport-agnostic engines and types
    sports/     - Per-sport plugin modules (MLB, NBA, etc.)
    services/   - Service layer connecting analytics to the API
"""
