"""Negative checks for deleted legacy payment/webhook paths."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REMOVED_RUNTIME_FILES = (
    "api/app/routers/commerce.py",
    "api/app/routers/billing.py",
    "api/app/routers/webhooks.py",
    "api/app/routers/admin/webhooks.py",
    "api/app/tasks/webhook_retry.py",
    "api/app/db/stripe.py",
    "scraper/sports_scraper/jobs/flow_tasks.py",
)

REMOVED_IMPORTS = (
    "app.routers.commerce",
    "app.routers.billing",
    "app.routers.webhooks",
    "app.tasks.webhook_retry",
    "app.db.stripe",
    "sports_scraper.jobs.flow_tasks",
)


def test_legacy_payment_runtime_files_are_absent() -> None:
    for relative in REMOVED_RUNTIME_FILES:
        assert not (ROOT / relative).exists(), f"legacy runtime file reintroduced: {relative}"


def test_legacy_payment_imports_are_absent_from_runtime_code() -> None:
    runtime_files = [
        path
        for base in (ROOT / "api" / "app", ROOT / "scripts")
        for path in base.rglob("*.py")
        if "__pycache__" not in path.parts
    ]
    offenders: list[str] = []
    for path in runtime_files:
        text = path.read_text(encoding="utf-8")
        for removed in REMOVED_IMPORTS:
            if removed in text:
                offenders.append(f"{path.relative_to(ROOT)} contains {removed}")
    assert offenders == []
