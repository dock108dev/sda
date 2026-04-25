"""HEAD → GET method-rewrite middleware.

Why:
    FastAPI's ``@router.get(...)`` registers a GET-only route. A HEAD
    request to that path returns 405 before the handler runs, which means
    cache-diagnostic headers (``Cache-Control``, ``X-Cache``) and any other
    response metadata are never emitted. ``curl -I``, browser HEAD probes,
    and uptime checkers all see this as "no cache layer at all" — which is
    misleading.

What this does:
    Rewrites the ASGI scope's method from HEAD to GET before the request
    reaches Starlette's router. The handler runs normally, headers are
    emitted, and we drop the response body before forwarding to the client
    (per HTTP/1.1 semantics for HEAD: same headers as GET, empty body).

Caveats:
    - Streaming responses are collapsed: every body chunk is swallowed
      and a single empty ``http.response.body`` close message is sent.
      The handler still does all the work, so this is purely cosmetic for
      the wire — but if a route's HEAD-vs-GET cost matters, it isn't free.
    - Content-Length is preserved untouched. Per RFC 9110 §15.4.1, HEAD
      responses report the length the GET body would have been, so this is
      correct behavior even though zero bytes follow.
"""

from __future__ import annotations

from collections.abc import Callable


class HeadAsGetMiddleware:
    """Outermost middleware: HEAD requests are run as GET, body is dropped."""

    def __init__(self, app: Callable) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http" or scope.get("method") != "HEAD":
            await self.app(scope, receive, send)
            return

        # Rewrite the method so the router resolves to the GET handler.
        get_scope = {**scope, "method": "GET"}

        async def send_wrapper(message: dict) -> None:
            if message["type"] == "http.response.body":
                more_body = message.get("more_body", False)
                if more_body:
                    # Swallow streaming chunks; the close message below
                    # terminates the response with zero body bytes.
                    return
                message = {"type": "http.response.body", "body": b""}
            await send(message)

        await self.app(get_scope, receive, send_wrapper)
