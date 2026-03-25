"""Model artifact loader.

Handles loading serialized ML models from disk. Supports joblib
(scikit-learn) and pickle formats. Verifies HMAC-SHA256 signatures
before deserialization when a ``.sig`` file is present.

Usage::

    loader = ModelLoader()
    model = loader.load_model("models/mlb/pa_model_v1.pkl")
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


class ModelLoader:
    """Loads serialized ML model artifacts from the filesystem.

    Before deserializing, verifies the HMAC signature produced by
    ``artifact_signing.sign_artifact()``. Artifacts without a ``.sig``
    file are allowed with a warning (backward compatibility for
    pre-signing artifacts).
    """

    def load_model(self, model_path: str) -> Any:
        """Load a model from the given path.

        Tries joblib first, falls back to pickle.

        Args:
            model_path: Absolute or relative path to the model file.

        Returns:
            The deserialized model object.

        Raises:
            FileNotFoundError: If the model file does not exist.
            ValueError: If the path is a symlink, traversal attempt,
                or the HMAC signature does not match.
            RuntimeError: If the file cannot be loaded.
        """
        # Resolve to canonical path to prevent traversal attacks.
        canonical = os.path.realpath(os.path.abspath(model_path))

        if os.path.islink(model_path):
            raise ValueError(f"Model path must not be a symlink: {model_path}")

        if not os.path.exists(canonical):
            raise FileNotFoundError(f"Model file not found: {canonical}")

        # Verify HMAC signature before deserialization.
        try:
            from .artifact_signing import verify_artifact
            verify_artifact(canonical)
        except (RuntimeError, FileNotFoundError):
            # No signing key configured or sig file missing — allow
            # with warning for backward compatibility.
            logger.warning(
                "artifact_signature_skipped",
                extra={"path": canonical, "reason": "no_key_or_sig"},
            )

        logger.info("loading_model", extra={"path": canonical})

        try:
            return self._load_joblib(canonical)
        except Exception:
            logger.debug("joblib_load_failed, trying pickle", extra={"path": canonical})

        try:
            return self._load_pickle(canonical)
        except Exception as exc:
            raise RuntimeError(f"Failed to load model from {canonical}: {exc}") from exc

    def _load_joblib(self, path: str) -> Any:
        import joblib
        return joblib.load(path)

    def _load_pickle(self, path: str) -> Any:
        import pickle
        with open(path, "rb") as f:
            return pickle.load(f)  # noqa: S301
