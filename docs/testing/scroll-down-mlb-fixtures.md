# Scroll Down MLB Fixtures

`api/tests/fixtures/scroll_down_mlb/` is a historical regression corpus for the Scroll Down MLB card builder port. It is test data only; it is not part of the active catch-up API runtime.

## Contents

- `games/`: captured and synthetic game payloads used by parity and scenario tests.
- `games/999125.json`: synthetic live-game fixture derived from `190125.json` to exercise an open-container case.
- `snapshots/`: TypeScript `buildCatchupCards` snapshots exported from the Scroll Down Web test suite.

## Refresh

Refresh snapshots only when the frontend builder contract intentionally changes:

```bash
cd ~/Desktop/scroll-down-web/web
npx vitest run tests/unit/qa/_export-snapshots.test.ts
cp tests/fixtures/snapshots/*.json \
   ~/Desktop/sports/sports-data-admin/api/tests/fixtures/scroll_down_mlb/snapshots/
```

## Parity Expectations

The Python port intentionally differs from the TypeScript snapshots in one documented way: backend DTOs omit `scoreAfter` for spoiler-safety. Parity tests strip `scoreAfter` from the TypeScript snapshot before comparison.

All other selected fields should match the snapshot contract unless a test explicitly documents a deliberate divergence.
