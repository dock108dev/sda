"""Scroll Down MLB — backend home for catch-up deck generation.

This module owns:
  * MLB game state reconstruction (game_state)
  * Deck card selection and ordering (deck_builder)
  * Pacing card insertion (rhythm_planner)
  * Visual payload mapping for the frontend (visual_mapper)
  * Internal-consistency validation (validation)
  * Narrative sentence rewrite (narrative)
  * Result chip labeling (result_labels)
  * Persistence of generated decks (persistence)
  * HTTP surface (router)

Phase 2 lands the contract: schemas, router shell, persistence shell, and
the migration. Logic ports follow in Phase 3.
"""

from .router import router

__all__ = ["router"]
