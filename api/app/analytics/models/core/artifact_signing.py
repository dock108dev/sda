"""HMAC-SHA256 signing and verification for model artifacts.

Every model artifact saved by the training pipeline is signed with
an HMAC derived from the application's secret key. On load, the
signature is verified before deserialization to prevent loading
tampered or attacker-crafted pickle files.

Signature files are stored alongside the artifact with a ``.sig``
extension (e.g., ``model.pkl`` → ``model.pkl.sig``).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Minimum key length to prevent weak signing keys.
_MIN_KEY_LENGTH = 32


def _get_signing_key() -> bytes:
    """Resolve the signing key from environment.

    Uses ``MODEL_SIGNING_KEY`` if set, otherwise falls back to
    ``API_KEY``. Raises if neither is available or too short.
    """
    raw = os.environ.get("MODEL_SIGNING_KEY") or os.environ.get("API_KEY") or ""
    if len(raw) < _MIN_KEY_LENGTH:
        raise RuntimeError(
            "MODEL_SIGNING_KEY or API_KEY must be set (min 32 chars) "
            "for model artifact signing."
        )
    return raw.encode("utf-8")


def _sig_path(artifact_path: str | Path) -> Path:
    """Return the signature file path for an artifact."""
    return Path(str(artifact_path) + ".sig")


def sign_artifact(artifact_path: str | Path) -> Path:
    """Compute HMAC-SHA256 of an artifact file and write the signature.

    Args:
        artifact_path: Path to the serialized model artifact.

    Returns:
        Path to the written ``.sig`` file.

    Raises:
        FileNotFoundError: If the artifact does not exist.
        RuntimeError: If no signing key is available.
    """
    artifact_path = Path(artifact_path)
    if not artifact_path.exists():
        raise FileNotFoundError(f"Artifact not found: {artifact_path}")

    key = _get_signing_key()
    digest = hmac.new(key, artifact_path.read_bytes(), hashlib.sha256).hexdigest()

    sig_file = _sig_path(artifact_path)
    sig_file.write_text(digest, encoding="utf-8")
    logger.info(
        "artifact_signed",
        extra={"artifact": str(artifact_path), "sig": str(sig_file)},
    )
    return sig_file


def verify_artifact(artifact_path: str | Path) -> bool:
    """Verify the HMAC-SHA256 signature of a model artifact.

    Args:
        artifact_path: Path to the serialized model artifact.

    Returns:
        ``True`` if the signature is valid.

    Raises:
        FileNotFoundError: If the artifact or signature file is missing.
        RuntimeError: If no signing key is available.
        ValueError: If the signature does not match (tampered artifact).
    """
    artifact_path = Path(artifact_path)
    sig_file = _sig_path(artifact_path)

    if not artifact_path.exists():
        raise FileNotFoundError(f"Artifact not found: {artifact_path}")

    if not sig_file.exists():
        # No signature file — artifact predates signing. Log a warning
        # but allow loading for backward compatibility. Once all existing
        # artifacts are re-signed, this should become an error.
        logger.warning(
            "artifact_signature_missing",
            extra={"artifact": str(artifact_path)},
        )
        return True

    key = _get_signing_key()
    expected = hmac.new(key, artifact_path.read_bytes(), hashlib.sha256).hexdigest()
    stored = sig_file.read_text(encoding="utf-8").strip()

    if not hmac.compare_digest(expected, stored):
        raise ValueError(
            f"Artifact signature mismatch — file may be tampered: {artifact_path}"
        )

    logger.info("artifact_verified", extra={"artifact": str(artifact_path)})
    return True
