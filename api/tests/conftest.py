"""pytest configuration and fixtures."""

import os

# Set required environment variables for testing before any imports
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/testdb")
os.environ.setdefault("MODEL_SIGNING_KEY", "test-signing-key-for-unit-tests-min32chars")

# Register all SQLAlchemy models so mapper relationships resolve correctly.
# Without this, running a subset of tests may fail if a model referenced by a
# relationship (e.g., SportsScrapeRun from SportsLeague) hasn't been imported.
import app.db.audit  # noqa: F401, E402
import app.db.club_membership  # noqa: F401, E402
import app.db.stripe  # noqa: F401, E402 — registers WebhookDeliveryAttempt
import app.db.club  # noqa: F401, E402
import app.db.flow  # noqa: F401, E402
import app.db.quality_review  # noqa: F401, E402
import app.db.odds  # noqa: F401, E402
import app.db.scraper  # noqa: F401, E402
import app.db.social  # noqa: F401, E402
import app.db.golf_pools  # noqa: F401, E402
import app.services.pool_lifecycle  # noqa: F401, E402 — registers PoolLifecycleEvent ORM model
import app.db.telemetry  # noqa: F401, E402
import app.db.mlb_advanced  # noqa: F401, E402
import app.db.nba_advanced  # noqa: F401, E402
import app.db.ncaab_advanced  # noqa: F401, E402
import app.db.nfl_advanced  # noqa: F401, E402
import app.db.nhl_advanced  # noqa: F401, E402
