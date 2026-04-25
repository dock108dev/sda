"""Process-local single-flight (request coalescing) helper.

Use case: many concurrent requests for the same expensive computation
(e.g. a FairBet EV-mode cold miss) should share one in-flight result
instead of each running the work independently. This is a thundering-herd
mitigation, complementary to the Redis response cache.

Process-local only — does not coordinate across replicas. The Redis cache
handles cross-replica deduplication; this helper handles the same-replica
burst that arrives faster than the cache fill time.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


class SingleFlight:
    """Awaitable single-flight by string key.

    Usage::

        sf = SingleFlight()
        result = await sf.run("query_hash:xyz", lambda: expensive_async_call())

    All callers passing the same key while the first call is still running
    receive the first call's result (or its exception). Once the first
    call completes, the entry is dropped — the next call repeats the work.
    """

    def __init__(self) -> None:
        self._inflight: dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()

    async def run(
        self,
        key: str,
        compute: Callable[[], Awaitable[T]],
    ) -> T:
        async with self._lock:
            existing = self._inflight.get(key)
            if existing is not None:
                fut = existing
                is_leader = False
            else:
                fut = asyncio.get_running_loop().create_future()
                self._inflight[key] = fut
                is_leader = True

        if not is_leader:
            return await fut

        try:
            result = await compute()
        except BaseException as exc:
            fut.set_exception(exc)
            raise
        else:
            fut.set_result(result)
            return result
        finally:
            async with self._lock:
                # Only drop if it's still our future (defensive against
                # races where another caller cleared it).
                if self._inflight.get(key) is fut:
                    del self._inflight[key]
