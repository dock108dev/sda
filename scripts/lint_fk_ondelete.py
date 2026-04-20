#!/usr/bin/env python3
"""CI check: every ForeignKey( call in api/app/db/ and alembic/versions/ must
declare an explicit ondelete= strategy.

Exit 0 = all clear.  Exit 1 = violations found.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]

SEARCH_DIRS = [
    ROOT / "api/app/db",
    ROOT / "api/alembic/versions",
]

# Matches ForeignKey( ... ) on a single logical line.
# We flag any ForeignKey( call that does NOT contain ondelete=.
FK_RE = re.compile(r"ForeignKey\([^)]+\)")


def check_file(path: Path) -> list[tuple[int, str]]:
    """Return list of (lineno, line) for violations."""
    violations: list[tuple[int, str]] = []
    for lineno, line in enumerate(path.read_text().splitlines(), start=1):
        for match in FK_RE.finditer(line):
            if "ondelete=" not in match.group():
                violations.append((lineno, line.rstrip()))
    return violations


def main() -> int:
    all_violations: list[tuple[Path, int, str]] = []

    for search_dir in SEARCH_DIRS:
        if not search_dir.exists():
            continue
        for path in sorted(search_dir.rglob("*.py")):
            for lineno, line in check_file(path):
                all_violations.append((path, lineno, line))

    if not all_violations:
        print("FK ondelete check PASSED — all ForeignKey() calls declare ondelete=")
        return 0

    print("FK ondelete check FAILED — the following ForeignKey() calls are missing ondelete=:\n")
    for path, lineno, line in all_violations:
        rel = path.relative_to(ROOT)
        print(f"  {rel}:{lineno}: {line.strip()}")

    print(
        "\nFix: add ondelete='CASCADE', ondelete='RESTRICT', or ondelete='SET NULL' to each"
        " ForeignKey call.\n"
        "Decision matrix:\n"
        "  child-of-game / child-of-tournament → CASCADE\n"
        "  join table row                       → CASCADE\n"
        "  nullable soft-reference              → SET NULL\n"
        "  lookup / reference table             → RESTRICT\n"
        "See docs/conventions/db.md for the full matrix."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
