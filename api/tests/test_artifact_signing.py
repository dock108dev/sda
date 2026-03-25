"""Tests for model artifact HMAC signing and verification."""

import os
from pathlib import Path
from unittest import mock

import pytest

from app.analytics.models.core.artifact_signing import (
    sign_artifact,
    verify_artifact,
    _sig_path,
)


@pytest.fixture(autouse=True)
def _set_signing_key(monkeypatch):
    """Ensure a signing key is available for all tests."""
    monkeypatch.setenv("API_KEY", "a" * 64)


class TestSignArtifact:
    def test_sign_creates_sig_file(self, tmp_path):
        artifact = tmp_path / "model.pkl"
        artifact.write_bytes(b"fake model data")

        sig_file = sign_artifact(artifact)

        assert sig_file.exists()
        assert sig_file.name == "model.pkl.sig"
        assert len(sig_file.read_text()) == 64  # SHA256 hex digest

    def test_sign_nonexistent_artifact_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            sign_artifact(tmp_path / "missing.pkl")

    def test_sign_without_key_raises(self, tmp_path, monkeypatch):
        monkeypatch.delenv("API_KEY", raising=False)
        monkeypatch.delenv("MODEL_SIGNING_KEY", raising=False)

        artifact = tmp_path / "model.pkl"
        artifact.write_bytes(b"data")

        with pytest.raises(RuntimeError, match="MODEL_SIGNING_KEY or API_KEY"):
            sign_artifact(artifact)

    def test_sign_uses_model_signing_key_over_api_key(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MODEL_SIGNING_KEY", "b" * 64)
        monkeypatch.setenv("API_KEY", "a" * 64)

        artifact = tmp_path / "model.pkl"
        artifact.write_bytes(b"data")

        sign_artifact(artifact)
        sig1 = _sig_path(artifact).read_text()

        # Sign with only API_KEY — should differ
        monkeypatch.delenv("MODEL_SIGNING_KEY")
        sign_artifact(artifact)
        sig2 = _sig_path(artifact).read_text()

        assert sig1 != sig2  # Different keys produce different sigs


class TestVerifyArtifact:
    def test_verify_valid_signature(self, tmp_path):
        artifact = tmp_path / "model.pkl"
        artifact.write_bytes(b"valid model data")
        sign_artifact(artifact)

        assert verify_artifact(artifact) is True

    def test_verify_tampered_artifact_raises(self, tmp_path):
        artifact = tmp_path / "model.pkl"
        artifact.write_bytes(b"original data")
        sign_artifact(artifact)

        # Tamper with the artifact after signing
        artifact.write_bytes(b"tampered data")

        with pytest.raises(ValueError, match="signature mismatch"):
            verify_artifact(artifact)

    def test_verify_tampered_sig_raises(self, tmp_path):
        artifact = tmp_path / "model.pkl"
        artifact.write_bytes(b"data")
        sign_artifact(artifact)

        # Tamper with the signature
        sig = _sig_path(artifact)
        sig.write_text("0" * 64)

        with pytest.raises(ValueError, match="signature mismatch"):
            verify_artifact(artifact)

    def test_verify_missing_sig_warns_but_passes(self, tmp_path):
        """Pre-signing artifacts (no .sig file) should be allowed with a warning."""
        artifact = tmp_path / "model.pkl"
        artifact.write_bytes(b"old model without sig")

        # No sig file exists — should return True (backward compat)
        assert verify_artifact(artifact) is True

    def test_verify_missing_artifact_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            verify_artifact(tmp_path / "missing.pkl")

    def test_roundtrip_sign_verify(self, tmp_path):
        """Sign then verify should always succeed."""
        artifact = tmp_path / "model.pkl"
        artifact.write_bytes(os.urandom(1024))

        sign_artifact(artifact)
        assert verify_artifact(artifact) is True


class TestSigPath:
    def test_sig_path_appends_extension(self):
        assert _sig_path("/models/v1.pkl") == Path("/models/v1.pkl.sig")
        assert _sig_path("relative/model.joblib") == Path("relative/model.joblib.sig")


class TestModelLoaderIntegration:
    """Verify the ModelLoader calls verification before deserialization."""

    def test_loader_verifies_before_loading(self, tmp_path):
        """When sig file exists with wrong hash, loader should raise."""
        import joblib
        from sklearn.dummy import DummyClassifier

        from app.analytics.models.core.model_loader import ModelLoader

        artifact = tmp_path / "model.pkl"
        model = DummyClassifier()
        joblib.dump(model, artifact)

        # Write a bad signature
        sig = _sig_path(artifact)
        sig.write_text("0" * 64)

        loader = ModelLoader()
        with pytest.raises(ValueError, match="signature mismatch"):
            loader.load_model(str(artifact))

    def test_loader_allows_unsigned_artifacts(self, tmp_path):
        """Pre-signing artifacts (no .sig) should load with a warning."""
        import joblib
        from sklearn.dummy import DummyClassifier

        from app.analytics.models.core.model_loader import ModelLoader

        artifact = tmp_path / "model.pkl"
        model = DummyClassifier()
        joblib.dump(model, artifact)

        loader = ModelLoader()
        loaded = loader.load_model(str(artifact))
        assert loaded is not None

    def test_loader_loads_signed_artifacts(self, tmp_path):
        """Properly signed artifacts should load successfully."""
        import joblib
        from sklearn.dummy import DummyClassifier

        from app.analytics.models.core.model_loader import ModelLoader

        artifact = tmp_path / "model.pkl"
        model = DummyClassifier()
        joblib.dump(model, artifact)
        sign_artifact(artifact)

        loader = ModelLoader()
        loaded = loader.load_model(str(artifact))
        assert loaded is not None
