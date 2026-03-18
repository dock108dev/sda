"""Shared password hashing — uses bcrypt directly.

passlib is not compatible with bcrypt >= 4.1 on Python 3.14
(ValueError in wrap-bug detection). Since we only need hash/verify,
we use bcrypt directly.
"""

from __future__ import annotations

import bcrypt


class _BcryptContext:
    """Minimal drop-in replacement for passlib.CryptContext.

    Supports only ``hash()`` and ``verify()`` with bcrypt.
    """

    def hash(self, password: str) -> str:
        return bcrypt.hashpw(
            password.encode("utf-8"),
            bcrypt.gensalt(),
        ).decode("utf-8")

    def verify(self, password: str, password_hash: str) -> bool:
        try:
            return bcrypt.checkpw(
                password.encode("utf-8"),
                password_hash.encode("utf-8"),
            )
        except (ValueError, TypeError):
            return False


pwd_context = _BcryptContext()
