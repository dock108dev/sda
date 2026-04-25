"""Tests for the process-local single-flight helper."""

from __future__ import annotations

import asyncio

import pytest

from app.services.single_flight import SingleFlight


@pytest.mark.asyncio
async def test_single_call_runs_compute_once():
    sf = SingleFlight()
    call_count = 0

    async def compute():
        nonlocal call_count
        call_count += 1
        return 42

    result = await sf.run("k", compute)
    assert result == 42
    assert call_count == 1


@pytest.mark.asyncio
async def test_concurrent_callers_share_one_compute():
    """Eight concurrent requests for the same key → one compute, one result."""
    sf = SingleFlight()
    call_count = 0

    async def compute():
        nonlocal call_count
        call_count += 1
        # Yield so all callers reach the lock before the leader finishes.
        await asyncio.sleep(0.01)
        return "shared-result"

    results = await asyncio.gather(*[sf.run("same-key", compute) for _ in range(8)])
    assert all(r == "shared-result" for r in results)
    assert call_count == 1


@pytest.mark.asyncio
async def test_different_keys_run_independently():
    sf = SingleFlight()
    call_count = 0

    async def compute_for(label):
        nonlocal call_count

        async def inner():
            nonlocal call_count
            call_count += 1
            return label

        return inner

    a, b = await asyncio.gather(
        sf.run("k-a", await compute_for("A")),
        sf.run("k-b", await compute_for("B")),
    )
    assert {a, b} == {"A", "B"}
    assert call_count == 2


@pytest.mark.asyncio
async def test_exception_propagates_to_all_callers():
    """A failure in the leader's compute should raise in every waiter, not
    leave them hanging."""
    sf = SingleFlight()

    async def fail():
        await asyncio.sleep(0.01)
        raise RuntimeError("boom")

    async def call():
        with pytest.raises(RuntimeError, match="boom"):
            await sf.run("k", fail)

    await asyncio.gather(call(), call(), call())


@pytest.mark.asyncio
async def test_entry_is_dropped_after_completion():
    """After a key finishes, the next call repeats the work — single-flight
    is a coalescing window, not a permanent cache."""
    sf = SingleFlight()
    call_count = 0

    async def compute():
        nonlocal call_count
        call_count += 1
        return "x"

    await sf.run("k", compute)
    await sf.run("k", compute)
    assert call_count == 2
