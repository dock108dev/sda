#!/usr/bin/env python3
"""Seed the initial admin user.

Usage:
    DATABASE_URL=postgresql+asyncpg://... python scripts/seed_admin_user.py

Idempotent — skips if the email already exists.
"""

from __future__ import annotations

import asyncio
import os
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Ensure app modules are importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db.users import User  # noqa: E402
from app.security import pwd_context as _pwd_ctx  # noqa: E402

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
ADMIN_ROLE = "admin"


async def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL environment variable is required.")
        sys.exit(1)
    if not ADMIN_EMAIL or not ADMIN_PASSWORD:
        print("ERROR: ADMIN_EMAIL and ADMIN_PASSWORD environment variables are required.")
        sys.exit(1)

    engine = create_async_engine(database_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        # Check if user already exists
        result = await session.execute(
            select(User).where(User.email == ADMIN_EMAIL)
        )
        existing = result.scalar_one_or_none()

        if existing is not None:
            print(f"User {ADMIN_EMAIL} already exists (id={existing.id}, role={existing.role})")
            if existing.role != ADMIN_ROLE:
                existing.role = ADMIN_ROLE
                await session.commit()
                print(f"  -> Updated role to '{ADMIN_ROLE}'")
            else:
                print("  -> Already admin, nothing to do.")
            await engine.dispose()
            return

        user = User(
            email=ADMIN_EMAIL,
            password_hash=_pwd_ctx.hash(ADMIN_PASSWORD),
            role=ADMIN_ROLE,
            is_active=True,
        )
        session.add(user)
        await session.commit()

        print(f"Created admin user: {ADMIN_EMAIL} (id={user.id})")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
