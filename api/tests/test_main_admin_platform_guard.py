"""Static guards for the active admin router wiring."""

from __future__ import annotations

import re
from pathlib import Path


def test_active_admin_routes_use_api_key_dependency() -> None:
    main_py = Path(__file__).resolve().parents[1] / "main.py"
    text = main_py.read_text(encoding="utf-8")
    assert "admin_platform" not in text
    assert re.search(
        r"app\.include_router\(\s*sports\.router,[\s\S]{0,200}?dependencies=auth_dependency",
        text,
    ), "sports router must use auth_dependency"
    assert re.search(
        r"app\.include_router\(\s*task_control\.router,\s*"
        r"prefix=\"/api/admin\"[\s\S]{0,400}?dependencies=auth_dependency",
        text,
    ), "task_control router must use auth_dependency"
