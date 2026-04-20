/**
 * k6 SSE load test — ISSUE-029
 *
 * Two-scenario test:
 *   sse_subscribers — 500 concurrent VUs each hold one SSE connection for the
 *     full test duration.  k6's built-in http_req_waiting metric (TTFB) is used
 *     as the p99 < 200 ms threshold: it measures the time from sending the GET
 *     to receiving the first response byte (the initial "subscribed" event),
 *     which is a tight proxy for first-event delivery latency.
 *
 *   publisher — 1 VU publishes 10 game-state change events via the admin API
 *     (POST /api/admin/realtime/test-emit), one per channel, starting after
 *     connections are established.
 *
 * Pass/fail thresholds (per ISSUE-029 acceptance criteria):
 *   p99 TTFB < 200 ms        — proxy for p99 event delivery latency
 *   sse_errors count == 0    — no SSE connection failures
 *   publisher_errors count==0 — all test-emit calls succeed
 *
 * NOTE: For full end-to-end event-delivery latency measurement (publish_ts →
 *   receipt at subscriber), run the Python harness instead:
 *     python tests/load/sse_load_test.py --clients 500 --duration 120 --rate 5
 *
 * Usage:
 *   k6 run tests/load/sse_concurrent.js \
 *     -e BASE_URL=http://localhost:8000 \
 *     -e API_KEY=dev \
 *     -e TEST_DURATION=120
 */

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter } from 'k6/metrics';

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const API_KEY = __ENV.API_KEY || '';
const TEST_DURATION_S = parseInt(__ENV.TEST_DURATION || '120', 10);

// 10 synthetic game channels — must match sse_load_test.py TEST_CHANNELS
const NUM_CHANNELS = 10;
const CHANNEL_BASE_ID = 9000;

// 10 total events published (one per channel)
const TOTAL_EVENTS = 10;

// ---------------------------------------------------------------------------
// Custom metrics
// ---------------------------------------------------------------------------

const sseErrors = new Counter('sse_errors');
const publisherErrors = new Counter('publisher_errors');

// ---------------------------------------------------------------------------
// Thresholds (ISSUE-029 acceptance criteria)
// ---------------------------------------------------------------------------

export const options = {
  scenarios: {
    sse_subscribers: {
      executor: 'constant-vus',
      vus: 500,
      duration: `${TEST_DURATION_S}s`,
      exec: 'subscribeSSE',
      gracefulStop: '15s',
    },
    publisher: {
      executor: 'shared-iterations',
      vus: 1,
      iterations: TOTAL_EVENTS,
      maxDuration: `${TEST_DURATION_S}s`,
      startTime: '15s', // allow connections to establish first
      exec: 'publishEvent',
    },
  },
  thresholds: {
    // p99 TTFB < 200 ms — first SSE byte arrives quickly for all subscribers
    'http_req_waiting{scenario:sse_subscribers}': ['p(99)<200'],
    // No SSE connection failures
    sse_errors: ['count==0'],
    // All admin publish calls succeed
    publisher_errors: ['count==0'],
    // Overall HTTP error rate < 1% (excludes expected 4xx on invalid channels)
    'http_req_failed{scenario:sse_subscribers}': ['rate<0.01'],
  },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function apiHeaders(accept) {
  const h = { Accept: accept || 'application/json' };
  if (API_KEY) {
    h['X-API-Key'] = API_KEY;
  }
  return h;
}

// ---------------------------------------------------------------------------
// Setup — verify API health before starting load
// ---------------------------------------------------------------------------

export function setup() {
  const res = http.get(`${BASE_URL}/healthz`, { timeout: '10s' });
  const ok = check(res, {
    'API health check passed': (r) => r.status === 200,
  });
  if (!ok) {
    throw new Error(`API not healthy (status=${res.status}): ${res.body}`);
  }
  console.log(`[setup] API healthy — starting ${TEST_DURATION_S}s load test with 500 SSE subscribers`);
}

// ---------------------------------------------------------------------------
// SSE subscriber VU — holds one connection for the full test window
// ---------------------------------------------------------------------------

export function subscribeSSE() {
  const channelIdx = (__VU - 1) % NUM_CHANNELS;
  const channel = `game:${CHANNEL_BASE_ID + channelIdx}:summary`;
  const url = `${BASE_URL}/v1/sse?channels=${channel}`;

  // Timeout is slightly longer than the test duration so k6 cancels the VU
  // cleanly at test end rather than the HTTP client timing out first.
  const res = http.get(url, {
    headers: apiHeaders('text/event-stream'),
    timeout: `${TEST_DURATION_S + 30}s`,
    tags: { name: 'SSE_subscribe', channel: `ch${channelIdx}` },
  });

  const ok = check(res, {
    'SSE status 200': (r) => r.status === 200,
    'SSE content-type is event-stream': (r) =>
      (r.headers['Content-Type'] || '').includes('text/event-stream'),
  });

  if (!ok) {
    sseErrors.add(1);
  }
}

// ---------------------------------------------------------------------------
// Publisher VU — emits one event per iteration via the admin test-emit endpoint
// ---------------------------------------------------------------------------

export function publishEvent() {
  // pace events: ~2 s gap between each (10 events over ~20 s)
  sleep(2);

  const channelIdx = (__ITER || 0) % NUM_CHANNELS;
  const channel = `game:${CHANNEL_BASE_ID + channelIdx}:summary`;

  const body = JSON.stringify({
    channel,
    event_type: 'patch',
    payload: {
      gameId: String(CHANNEL_BASE_ID + channelIdx),
      patch: { status: 'LIVE' },
    },
  });

  const res = http.post(
    `${BASE_URL}/api/admin/realtime/test-emit`,
    body,
    {
      headers: { ...apiHeaders(), 'Content-Type': 'application/json' },
      timeout: '10s',
      tags: { name: 'admin_test_emit' },
    },
  );

  const ok = check(res, {
    'Event published (200)': (r) => r.status === 200,
  });

  if (!ok) {
    publisherErrors.add(1);
    console.warn(`[publisher] emit failed channel=${channel} status=${res.status} body=${res.body}`);
  }
}

// ---------------------------------------------------------------------------
// Teardown — log realtime status summary
// ---------------------------------------------------------------------------

export function teardown() {
  sleep(3); // let final events propagate

  const res = http.get(`${BASE_URL}/v1/realtime/status`, {
    headers: apiHeaders(),
    timeout: '10s',
  });

  if (res.status === 200) {
    try {
      const status = JSON.parse(res.body);
      console.log(
        `[teardown] realtime_status: ` +
        `connections=${status.total_connections || 0} ` +
        `published=${status.publish_count || 0} ` +
        `errors=${status.error_count || 0}`,
      );
    } catch (_) {
      console.warn('[teardown] failed to parse realtime status');
    }
  }
}
