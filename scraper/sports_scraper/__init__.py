"""Theory Bets scraper package.

Avoid importing ``config`` at module import time so tests and utility imports
can load submodules without forcing full environment validation.
"""

from __future__ import annotations

__all__ = ["settings"]


def __getattr__(name: str):
    if name == "settings":
        from .config import settings

        return settings
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
