"""Tests for deploy env-file linting."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "lint_env_file.py"


def test_lint_env_file_rejects_unknown_and_missing_required_keys(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("ENVIRONMENT=production\nDATABASE_URL=postgresql://example\nTYPO_API_KYE=x\n")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(env_file)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "UNKNOWN: TYPO_API_KYE" in result.stderr
    assert "MISSING: API_KEY" in result.stderr


def test_lint_env_file_marks_stripe_keys_deprecated_without_failing(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "ENVIRONMENT=production",
                "DATABASE_URL=postgresql://example",
                "API_KEY=admin-key",
                "CONSUMER_API_KEY=consumer-key",
                "JWT_SECRET=jwt-secret",
                "REDIS_URL=redis://example",
                "ALLOWED_CORS_ORIGINS=https://admin.example",
                "STRIPE_SECRET_KEY=deprecated",
            ]
        )
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(env_file)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "DEPRECATED: STRIPE_SECRET_KEY" in result.stderr
