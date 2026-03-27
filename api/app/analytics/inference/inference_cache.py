"""Inference model cache.

Caches loaded ML model artifacts in memory to prevent repeated
disk reads during inference. Models are keyed by their file path
and loaded once per runtime.

Usage::

    cache = InferenceCache()
    model = cache.get_model("models/mlb/artifacts/mlb_pa_model_v1.pkl")
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class InferenceCache:
    """In-memory cache for loaded ML model artifacts."""

    def __init__(self) -> None:
        self._cache: dict[str, Any] = {}

    def get_model(self, path: str) -> Any:
        """Get a model from cache, loading from disk on first access.

        Args:
            path: Path to the model artifact file.

        Returns:
            The deserialized model object.

        Raises:
            FileNotFoundError: If the model file does not exist.
            RuntimeError: If the file cannot be loaded.
        """
        if path in self._cache:
            return self._cache[path]

        from pathlib import Path as _Path
        p = _Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Model artifact not found: {path}")
        if not p.is_file():
            raise FileNotFoundError(f"Model artifact path is not a file: {path}")

        # Verify artifact signature before loading to prevent tampered
        # or unsigned models from being deserialized.
        from app.analytics.models.core.artifact_signing import verify_artifact
        verify_artifact(path)

        import joblib
        try:
            model = joblib.load(path)
        except Exception as exc:
            raise RuntimeError(f"Failed to load model artifact {path}: {exc}") from exc
        self._cache[path] = model
        logger.info("model_cached", extra={"path": path})
        return model

    def is_cached(self, path: str) -> bool:
        """Check if a model is already cached."""
        return path in self._cache

    def invalidate(self, path: str) -> None:
        """Remove a model from the cache."""
        self._cache.pop(path, None)

    def clear(self) -> None:
        """Clear all cached models."""
        self._cache.clear()

    @property
    def size(self) -> int:
        """Number of models currently cached."""
        return len(self._cache)
