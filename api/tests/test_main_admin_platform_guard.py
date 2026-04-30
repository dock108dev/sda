"""Static guard: admin platform router must stay on admin_dependency."""

from __future__ import annotations

import re
from pathlib import Path


def test_admin_platform_include_uses_admin_dependency() -> None:
    main_py = Path(__file__).resolve().parents[1] / "main.py"
    text = main_py.read_text(encoding="utf-8")
    assert re.search(
        r"app\.include_router\(\s*admin_platform\.router,\s*"
        r"prefix=\"/api/admin\"[\s\S]{0,400}?dependencies=admin_dependency",
        text,
    ), "admin_platform router must use dependencies=admin_dependency"
