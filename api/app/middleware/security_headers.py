"""HTTP security-header middleware.

Injects a conservative baseline of browser hardening headers on every
non-``OPTIONS`` HTTP response:

- ``Content-Security-Policy: default-src 'self'``
- ``Strict-Transport-Security: max-age=31536000; includeSubDomains``
- ``X-Frame-Options: DENY``
- ``X-Content-Type-Options: nosniff``
- ``Referrer-Policy: same-origin``

CORS preflight (``OPTIONS``) responses are passed through untouched so the
CORS middleware's negotiation headers are the only ones on the wire.
"""

from __future__ import annotations

from collections.abc import Callable


_DEFAULT_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"content-security-policy", b"default-src 'self'"),
    (
        b"strict-transport-security",
        b"max-age=31536000; includeSubDomains",
    ),
    (b"x-frame-options", b"DENY"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"same-origin"),
)


class SecurityHeadersMiddleware:
    def __init__(self, app: Callable) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http" or scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                existing = {name.lower() for name, _ in headers}
                for name, value in _DEFAULT_HEADERS:
                    if name not in existing:
                        headers.append((name, value))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)
