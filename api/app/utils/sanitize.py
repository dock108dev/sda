"""HTML sanitization helpers for free-text fields.

Free-text user-supplied strings (club name, pool name, pool notes/description)
are stripped of all HTML tags before they reach the ORM. We use ``bleach`` with
an empty allowed-tags list, which removes tags while preserving inner text
(e.g. ``"<script>alert(1)</script>Hi"`` becomes ``"alert(1)Hi"``).

``bleach`` is imported lazily so that tests / environments without the library
installed still import this module cleanly; call sites get a clear ImportError
when sanitization is actually invoked.
"""

from __future__ import annotations

from typing import Any

try:  # pragma: no cover - import guard
    import bleach as _bleach
except ImportError:  # pragma: no cover
    _bleach = None  # type: ignore[assignment]


def sanitize_text(value: Any) -> Any:
    """Strip all HTML tags from ``value`` and return the cleaned string.

    Non-string values are returned unchanged so Pydantic validators can layer
    this in ``mode="before"`` without disrupting ``None`` / type-coercion.
    """
    if not isinstance(value, str):
        return value
    if _bleach is None:  # pragma: no cover
        raise RuntimeError(
            "bleach is required for sanitize_text(); install 'bleach' package"
        )
    return _bleach.clean(value, tags=[], attributes={}, strip=True)
