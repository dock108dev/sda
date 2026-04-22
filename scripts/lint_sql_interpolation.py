#!/usr/bin/env python3
"""Fail if any ``text()`` / ``execute()`` call uses f-string or %-string SQL.

SQLAlchemy must use parameterized queries — ``text("... :param")`` with
``bindparams`` or ORM constructs. String interpolation into SQL enables
injection. Run under CI; this is a cheap static scan, not a full AST walk.
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCAN_DIR = ROOT / "api" / "app"

PATTERNS = [
    # text("... " + var) or text(f"...")
    re.compile(r"\btext\(\s*f['\"]"),
    # execute(f"SELECT ...")
    re.compile(r"\bexecute\(\s*f['\"](?:SELECT|INSERT|UPDATE|DELETE)", re.IGNORECASE),
    # "SELECT ... %s" % ...  — %-formatted SQL
    re.compile(
        r"['\"](?:SELECT|INSERT|UPDATE|DELETE)[^'\"]*%s[^'\"]*['\"]\s*%",
        re.IGNORECASE,
    ),
    # "SELECT ...".format(...)
    re.compile(
        r"['\"](?:SELECT|INSERT|UPDATE|DELETE)[^'\"]*\{[^'\"]*['\"]\s*\.format\(",
        re.IGNORECASE,
    ),
]


def main() -> int:
    offenders: list[tuple[pathlib.Path, int, str]] = []
    for path in SCAN_DIR.rglob("*.py"):
        try:
            text = path.read_text()
        except Exception:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pat in PATTERNS:
                if pat.search(line):
                    offenders.append((path, lineno, line.strip()))
                    break

    if offenders:
        print("Found potential SQL string-interpolation sites:", file=sys.stderr)
        for path, lineno, line in offenders:
            print(f"  {path.relative_to(ROOT)}:{lineno}: {line}", file=sys.stderr)
        return 1
    print("OK: no SQL string interpolation found under api/app/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
