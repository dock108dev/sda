"""CI gate: all Pydantic response models must expose camelCase field names on the wire.

Mirrors the scripts/lint_camel_case_schemas.py CI check so that ``pytest`` catches
regressions locally before the dedicated lint job runs in GitHub Actions.
"""

import subprocess
import sys
from pathlib import Path


def test_no_snake_case_response_fields() -> None:
    """Lint script must exit 0 — no snake_case fields missing camelCase aliases."""
    repo_root = Path(__file__).parent.parent.parent
    lint_script = repo_root / "scripts" / "lint_camel_case_schemas.py"
    result = subprocess.run(
        [sys.executable, str(lint_script)],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    assert result.returncode == 0, (
        "snake_case fields found in Pydantic response models:\n"
        + result.stdout
        + result.stderr
    )
