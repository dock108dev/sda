#!/usr/bin/env python3
"""SSE realtime load test.

Connects --clients concurrent SSE subscribers to a running API, publishes
events at --rate events/sec per channel directly via Redis Streams, and
measures end-to-end latency (XADD → SSE receipt), message drops, and
duplicate delivery.

Generates a JSON summary + HTML report in tests/load/results/.

Exit codes:
  0  All acceptance criteria met
  1  One or more criteria failed (see report for details)

Usage:
    python tests/load/sse_load_test.py \\
        --url http://localhost:8000 \\
        --api-key dev \\
        --redis redis://localhost:6379/0 \\
        --clients 500 \\
        --duration 600 \\
        --rate 5
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import redis.asyncio as aioredis

# ── Redis stream constants — must match api/app/realtime/streams.py ──────────
STREAM_KEY = "realtime:events"
SEQ_HASH = "realtime:seq"
STREAM_RETENTION_MS = int(os.getenv("REALTIME_STREAM_RETENTION_MS", "3600000"))

# ── Channel pool — valid game:N:summary format, IDs are synthetic ────────────
_CHANNEL_COUNT = 10
TEST_CHANNELS = [f"game:{9000 + i}:summary" for i in range(_CHANNEL_COUNT)]

# ── Acceptance-criteria thresholds ───────────────────────────────────────────
P99_LATENCY_BUDGET_MS = 200.0
MAX_DROPS = 0
MAX_DUPLICATES = 0


# ── Per-client state ─────────────────────────────────────────────────────────

@dataclass
class ClientMetrics:
    client_id: int
    channel: str
    connected: bool = False
    received: int = 0
    drops: int = 0
    duplicates: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    _last_seq: int = field(default=0, repr=False)
    _seen_seqs: set[int] = field(default_factory=set, repr=False)

    def record_event(self, seq: int, publish_ts: float | None) -> None:
        now = time.time()
        if seq in self._seen_seqs:
            self.duplicates += 1
            return
        # Detect gaps: if seq jumped by more than 1, count the skipped seqs as drops.
        if self._last_seq > 0 and seq > self._last_seq + 1:
            self.drops += seq - self._last_seq - 1
        self._seen_seqs.add(seq)
        if seq > self._last_seq:
            self._last_seq = seq
        self.received += 1
        if publish_ts is not None:
            lat_ms = (now - publish_ts) * 1000.0
            # Sanity filter: ignore negative or implausibly large values
            if 0 < lat_ms < 60_000:
                self.latencies_ms.append(lat_ms)


# ── Results summary ───────────────────────────────────────────────────────────

@dataclass
class LoadTestResults:
    started_at: str
    duration_s: float
    clients_requested: int
    clients_connected: int
    total_events_received: int
    total_drops: int
    total_duplicates: int
    latency_p50_ms: float
    latency_p90_ms: float
    latency_p99_ms: float
    passed: bool
    failure_reasons: list[str]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _percentile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    k = (len(s) - 1) * p / 100.0
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _build_headers(api_key: str) -> dict[str, str]:
    h: dict[str, str] = {"Accept": "text/event-stream"}
    if api_key:
        h["X-API-Key"] = api_key
    return h


# ── SSE client coroutine ──────────────────────────────────────────────────────

async def _sse_client(
    client_id: int,
    url: str,
    api_key: str,
    channel: str,
    metrics: ClientMetrics,
    stop_event: asyncio.Event,
    ready_event: asyncio.Event,
) -> None:
    sse_url = f"{url}/v1/sse?channels={channel}"
    headers = _build_headers(api_key)
    limits = httpx.Limits(max_connections=1, max_keepalive_connections=1)
    timeout = httpx.Timeout(None, connect=30.0)

    try:
        async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
            async with client.stream("GET", sse_url, headers=headers) as response:
                if response.status_code != 200:
                    return

                async for raw_line in response.aiter_lines():
                    if stop_event.is_set():
                        break

                    if not raw_line.startswith("data: "):
                        continue

                    try:
                        data = json.loads(raw_line[6:])
                    except json.JSONDecodeError:
                        continue

                    evt_type = data.get("type")

                    if evt_type == "subscribed":
                        metrics.connected = True
                        ready_event.set()
                        continue

                    if evt_type in ("error", "epoch_changed"):
                        continue

                    seq = data.get("seq")
                    if seq is None:
                        continue

                    publish_ts = data.get("_publish_ts")
                    metrics.record_event(int(seq), publish_ts)

    except (httpx.RequestError, asyncio.CancelledError):
        pass
    except Exception:
        pass
    finally:
        # Unblock the ready-waiter even on connection failure
        ready_event.set()


# ── Publisher coroutine ───────────────────────────────────────────────────────

async def _publisher(
    redis_url: str,
    boot_epoch: str,
    channels: list[str],
    rate_per_channel: float,
    stop_event: asyncio.Event,
) -> int:
    """Write synthetic events to Redis Streams, mirroring RedisStreamsBridge.publish().

    Returns total number of events published.
    """
    r = aioredis.from_url(redis_url, decode_responses=True)
    interval = 1.0 / rate_per_channel
    published = 0

    try:
        while not stop_event.is_set():
            cycle_start = time.time()
            for channel in channels:
                if stop_event.is_set():
                    break
                # Atomically assign the next sequence number (same as the bridge)
                seq: int = await r.hincrby(SEQ_HASH, channel, 1)
                publish_ts = time.time()
                minid = f"{int(publish_ts * 1000) - STREAM_RETENTION_MS}-0"
                payload = {
                    "_publish_ts": publish_ts,
                    "gameId": channel.split(":")[1],
                    "patch": {"status": "LIVE"},
                }
                await r.xadd(
                    STREAM_KEY,
                    {
                        "channel": channel,
                        "type": "patch",
                        "payload": json.dumps(payload),
                        "boot_epoch": boot_epoch,
                        "seq": str(seq),
                    },
                    minid=minid,
                    approximate=True,
                )
                published += 1

            elapsed = time.time() - cycle_start
            sleep_time = interval - elapsed
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)

    except asyncio.CancelledError:
        pass
    finally:
        await r.aclose()

    return published


# ── Monitor coroutine ─────────────────────────────────────────────────────────

async def _monitor(
    url: str,
    api_key: str,
    samples: list[dict[str, Any]],
    stop_event: asyncio.Event,
    interval_s: float = 30.0,
) -> None:
    """Poll /v1/realtime/status periodically and record connection counts."""
    headers: dict[str, str] = {}
    if api_key:
        headers["X-API-Key"] = api_key

    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
        while not stop_event.is_set():
            try:
                resp = await client.get(
                    f"{url}/v1/realtime/status", headers=headers
                )
                if resp.status_code == 200:
                    data = resp.json()
                    samples.append(
                        {
                            "ts": time.time(),
                            "total_connections": data.get("total_connections", 0),
                            "publish_count": data.get("publish_count", 0),
                            "error_count": data.get("error_count", 0),
                        }
                    )
            except Exception:
                pass

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_s)
            except asyncio.TimeoutError:
                pass


# ── Boot-epoch fetch ──────────────────────────────────────────────────────────

async def _get_boot_epoch(url: str, api_key: str) -> str:
    headers: dict[str, str] = {}
    if api_key:
        headers["X-API-Key"] = api_key
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
        try:
            resp = await client.get(f"{url}/v1/realtime/status", headers=headers)
            if resp.status_code == 200:
                return resp.json().get("boot_epoch", "unknown")
        except Exception:
            pass
    return "unknown"


# ── Results assembly ──────────────────────────────────────────────────────────

def _build_results(
    started_at: str,
    duration_s: float,
    n_clients: int,
    all_metrics: list[ClientMetrics],
) -> LoadTestResults:
    connected = sum(1 for m in all_metrics if m.connected)
    total_received = sum(m.received for m in all_metrics)
    total_drops = sum(m.drops for m in all_metrics)
    total_dups = sum(m.duplicates for m in all_metrics)

    all_latencies: list[float] = []
    for m in all_metrics:
        all_latencies.extend(m.latencies_ms)

    p50 = _percentile(all_latencies, 50)
    p90 = _percentile(all_latencies, 90)
    p99 = _percentile(all_latencies, 99)

    failure_reasons: list[str] = []
    if connected < n_clients:
        failure_reasons.append(
            f"Only {connected}/{n_clients} clients connected successfully"
        )
    if p99 > P99_LATENCY_BUDGET_MS:
        failure_reasons.append(
            f"p99 latency {p99:.1f} ms exceeds budget of {P99_LATENCY_BUDGET_MS:.0f} ms"
        )
    if total_drops > MAX_DROPS:
        failure_reasons.append(f"{total_drops} message drop(s) detected")
    if total_dups > MAX_DUPLICATES:
        failure_reasons.append(f"{total_dups} duplicate event(s) detected")

    return LoadTestResults(
        started_at=started_at,
        duration_s=duration_s,
        clients_requested=n_clients,
        clients_connected=connected,
        total_events_received=total_received,
        total_drops=total_drops,
        total_duplicates=total_dups,
        latency_p50_ms=p50,
        latency_p90_ms=p90,
        latency_p99_ms=p99,
        passed=len(failure_reasons) == 0,
        failure_reasons=failure_reasons,
    )


# ── Report writers ────────────────────────────────────────────────────────────

def _write_json_report(results: LoadTestResults, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "started_at": results.started_at,
        "duration_s": results.duration_s,
        "clients_requested": results.clients_requested,
        "clients_connected": results.clients_connected,
        "total_events_received": results.total_events_received,
        "total_drops": results.total_drops,
        "total_duplicates": results.total_duplicates,
        "latency_p50_ms": round(results.latency_p50_ms, 2),
        "latency_p90_ms": round(results.latency_p90_ms, 2),
        "latency_p99_ms": round(results.latency_p99_ms, 2),
        "passed": results.passed,
        "failure_reasons": results.failure_reasons,
        "thresholds": {
            "p99_latency_ms": P99_LATENCY_BUDGET_MS,
            "max_drops": MAX_DROPS,
            "max_duplicates": MAX_DUPLICATES,
        },
    }
    path.write_text(json.dumps(data, indent=2))


def _write_html_report(results: LoadTestResults, path: Path) -> None:
    status_color = "#22c55e" if results.passed else "#ef4444"
    status_label = "PASSED" if results.passed else "FAILED"

    failures_html = ""
    if results.failure_reasons:
        items = "".join(f"<li>{r}</li>" for r in results.failure_reasons)
        failures_html = f"<ul class='failures'>{items}</ul>"

    def _row(label: str, value: str, threshold: str, ok: bool) -> str:
        cls = "pass" if ok else "fail"
        mark = "✓" if ok else "✗"
        return (
            f"<tr><td>{label}</td><td>{value}</td>"
            f"<td>{threshold}</td>"
            f'<td class="{cls}">{mark}</td></tr>'
        )

    rows = (
        _row(
            "Clients connected",
            f"{results.clients_connected} / {results.clients_requested}",
            str(results.clients_requested),
            results.clients_connected >= results.clients_requested,
        )
        + _row(
            "p99 latency",
            f"{results.latency_p99_ms:.1f} ms",
            f"&lt; {P99_LATENCY_BUDGET_MS:.0f} ms",
            results.latency_p99_ms <= P99_LATENCY_BUDGET_MS,
        )
        + f"<tr><td>p90 latency</td><td>{results.latency_p90_ms:.1f} ms</td><td>—</td><td>—</td></tr>"
        + f"<tr><td>p50 latency</td><td>{results.latency_p50_ms:.1f} ms</td><td>—</td><td>—</td></tr>"
        + _row(
            "Message drops",
            str(results.total_drops),
            "0",
            results.total_drops == 0,
        )
        + _row(
            "Duplicate events",
            str(results.total_duplicates),
            "0",
            results.total_duplicates == 0,
        )
        + f"<tr><td>Total events received</td><td>{results.total_events_received:,}</td><td>—</td><td>—</td></tr>"
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>SSE Load Test — {results.started_at}</title>
  <style>
    body{{font-family:system-ui,sans-serif;max-width:800px;margin:2rem auto;color:#1e293b}}
    h1{{display:flex;align-items:center;gap:.75rem}}
    .badge{{background:{status_color};color:#fff;padding:.2em .8em;border-radius:999px;font-size:.8em}}
    table{{border-collapse:collapse;width:100%;margin:1.5rem 0}}
    th,td{{padding:.55rem 1rem;text-align:left;border-bottom:1px solid #e2e8f0}}
    th{{background:#f8fafc;font-weight:600}}
    .pass{{color:#16a34a}}.fail{{color:#dc2626}}
    .failures{{background:#fef2f2;padding:.5rem 1.5rem;border-radius:.5rem;margin:1rem 0}}
    .failures li{{color:#dc2626;margin:.3rem 0}}
    footer{{margin-top:3rem;font-size:.75rem;color:#94a3b8}}
  </style>
</head>
<body>
  <h1>SSE Load Test <span class="badge">{status_label}</span></h1>
  <p>Started: {results.started_at} &nbsp;|&nbsp; Duration: {results.duration_s:.0f} s</p>
  {failures_html}
  <table>
    <tr><th>Metric</th><th>Result</th><th>Threshold</th><th>Status</th></tr>
    {rows}
  </table>
  <footer>Generated by tests/load/sse_load_test.py</footer>
</body>
</html>"""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html)


# ── Main orchestrator ─────────────────────────────────────────────────────────

async def run(args: argparse.Namespace) -> bool:
    n_clients: int = args.clients
    channels = TEST_CHANNELS

    started_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    ts_tag = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    report_dir = Path(__file__).parent / "results"

    print(f"[load-test] {started_at}")
    print(f"[load-test] target={args.url}  clients={n_clients}  "
          f"channels={len(channels)}  duration={args.duration}s  "
          f"rate={args.rate}/chan/s")

    # Resolve the API's boot_epoch so published entries pass the backfill filter
    boot_epoch = await _get_boot_epoch(args.url, args.api_key)
    print(f"[load-test] boot_epoch={boot_epoch}")

    stop_event = asyncio.Event()
    monitor_samples: list[dict[str, Any]] = []

    # Build per-client state, distributing clients round-robin across channels
    all_metrics: list[ClientMetrics] = []
    ready_events: list[asyncio.Event] = []
    for i in range(n_clients):
        ch = channels[i % len(channels)]
        all_metrics.append(ClientMetrics(client_id=i, channel=ch))
        ready_events.append(asyncio.Event())

    print("[load-test] connecting clients…")

    client_tasks = [
        asyncio.create_task(
            _sse_client(
                client_id=m.client_id,
                url=args.url,
                api_key=args.api_key,
                channel=m.channel,
                metrics=m,
                stop_event=stop_event,
                ready_event=ready_events[m.client_id],
            ),
            name=f"sse-{m.client_id}",
        )
        for m in all_metrics
    ]

    # Wait up to 60 s for all clients to receive their "subscribed" confirmation
    try:
        await asyncio.wait_for(
            asyncio.gather(*[e.wait() for e in ready_events]),
            timeout=60.0,
        )
    except asyncio.TimeoutError:
        pass

    connected_count = sum(1 for m in all_metrics if m.connected)
    print(f"[load-test] {connected_count}/{n_clients} clients connected — starting test window")

    publisher_task = asyncio.create_task(
        _publisher(
            redis_url=args.redis,
            boot_epoch=boot_epoch,
            channels=channels,
            rate_per_channel=args.rate,
            stop_event=stop_event,
        ),
        name="publisher",
    )
    monitor_task = asyncio.create_task(
        _monitor(args.url, args.api_key, monitor_samples, stop_event),
        name="monitor",
    )

    test_start = time.time()
    try:
        await asyncio.sleep(args.duration)
    except asyncio.CancelledError:
        pass
    actual_duration = time.time() - test_start

    print(f"[load-test] test window complete ({actual_duration:.1f}s) — collecting results")
    stop_event.set()

    published = await publisher_task
    await monitor_task
    for t in client_tasks:
        t.cancel()
    await asyncio.gather(*client_tasks, return_exceptions=True)

    print(f"[load-test] published={published} events")

    results = _build_results(
        started_at=started_at,
        duration_s=actual_duration,
        n_clients=n_clients,
        all_metrics=all_metrics,
    )

    json_path = report_dir / f"load-{ts_tag}.json"
    html_path = report_dir / f"load-{ts_tag}.html"
    _write_json_report(results, json_path)
    _write_html_report(results, html_path)

    verdict = "PASSED" if results.passed else "FAILED"
    print(f"\n{'='*50}")
    print(f"  {verdict}")
    print(f"  p50={results.latency_p50_ms:.1f} ms  "
          f"p90={results.latency_p90_ms:.1f} ms  "
          f"p99={results.latency_p99_ms:.1f} ms")
    print(f"  drops={results.total_drops}  "
          f"duplicates={results.total_duplicates}  "
          f"received={results.total_events_received:,}")
    print(f"  clients connected: {results.clients_connected}/{results.clients_requested}")
    for reason in results.failure_reasons:
        print(f"  ✗ {reason}")
    print(f"{'='*50}")
    print(f"\nJSON report : {json_path}")
    print(f"HTML report : {html_path}")

    return results.passed


def main() -> None:
    parser = argparse.ArgumentParser(description="SSE realtime load test — 500 clients, 10 min")
    parser.add_argument(
        "--url",
        default=os.getenv("LOAD_TEST_URL", "http://localhost:8000"),
        help="API base URL (env: LOAD_TEST_URL)",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("LOAD_TEST_API_KEY", ""),
        help="X-API-Key value; empty = dev-mode unauthenticated (env: LOAD_TEST_API_KEY)",
    )
    parser.add_argument(
        "--redis",
        default=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        help="Redis URL for event publishing (env: REDIS_URL)",
    )
    parser.add_argument(
        "--clients",
        type=int,
        default=int(os.getenv("LOAD_TEST_CLIENTS", "500")),
        help="Number of concurrent SSE clients",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=int(os.getenv("LOAD_TEST_DURATION", "600")),
        help="Test duration in seconds (default: 600 = 10 min)",
    )
    parser.add_argument(
        "--rate",
        type=float,
        default=float(os.getenv("LOAD_TEST_RATE", "5")),
        help="Events published per second per channel",
    )
    args = parser.parse_args()

    passed = asyncio.run(run(args))
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
