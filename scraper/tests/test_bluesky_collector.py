"""Tests for the Bluesky AT Protocol social collector prototype.

Uses importlib to load bluesky_collector.py and models.py directly,
bypassing the social package __init__.py which pulls in structlog/db
dependencies not present in the minimal test venv.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRAPER_ROOT = REPO_ROOT / "scraper"
if str(SCRAPER_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRAPER_ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/test_db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ENVIRONMENT", "development")

# ---------------------------------------------------------------------------
# Load models.py and bluesky_collector.py directly to avoid __init__.py
# chain that requires structlog (not installed in minimal test venv).
# ---------------------------------------------------------------------------

_MISSING = object()
_ORIG_MODULES: dict[str, object] = {}


def _remember_module(name: str) -> None:
    if name not in _ORIG_MODULES:
        _ORIG_MODULES[name] = sys.modules.get(name, _MISSING)


def _set_module(name: str, module: types.ModuleType) -> None:
    _remember_module(name)
    sys.modules[name] = module


def _setdefault_module(name: str, module: types.ModuleType) -> None:
    _remember_module(name)
    sys.modules.setdefault(name, module)


def _restore_stubbed_modules() -> None:
    for name, original in _ORIG_MODULES.items():
        if original is _MISSING:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original


@pytest.fixture(autouse=True)
def _restore_runtime_module_stubs():
    """Prevent per-test module stubs from leaking to other test modules."""
    names = (
        "sports_scraper.db",
        "sqlalchemy",
        "sqlalchemy.dialects",
        "sqlalchemy.dialects.postgresql",
    )
    originals: dict[str, object] = {
        name: sys.modules.get(name, _MISSING) for name in names
    }
    yield
    for name, original in originals.items():
        if original is _MISSING:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original


def _load_module(name: str, path: Path, package: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path, submodule_search_locations=[])
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = package
    _set_module(name, mod)
    spec.loader.exec_module(mod)
    return mod


# Stub the social package so relative imports inside the loaded modules resolve.
_social_pkg = types.ModuleType("sports_scraper.social")
_social_pkg.__path__ = []
_social_pkg.__package__ = "sports_scraper.social"
_setdefault_module("sports_scraper.social", _social_pkg)

_models_mod = _load_module(
    "sports_scraper.social.models",
    SCRAPER_ROOT / "sports_scraper/social/models.py",
    "sports_scraper.social",
)
_social_pkg.models = _models_mod  # type: ignore[attr-defined]

_bc_mod = _load_module(
    "sports_scraper.social.bluesky_collector",
    SCRAPER_ROOT / "sports_scraper/social/bluesky_collector.py",
    "sports_scraper.social",
)

CollectedPost = _models_mod.CollectedPost
BlueSkyCollector = _bc_mod.BlueSkyCollector
persist_bluesky_posts = _bc_mod.persist_bluesky_posts
_build_post_url = _bc_mod._build_post_url
_extract_media = _bc_mod._extract_media
_parse_at_uri = _bc_mod._parse_at_uri
_to_utc = _bc_mod._to_utc

# Restore global module table so this test's import stubs do not affect
# collection/imports in unrelated modules.
_restore_stubbed_modules()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_feed_item(
    rkey: str = "abc123",
    handle: str = "patriots.bsky.social",
    did: str = "did:plc:testdid",
    created_at: str = "2024-01-15T14:00:00Z",
    text: str = "Game day!",
    embed: dict | None = None,
    is_repost: bool = False,
) -> dict:
    item: dict = {
        "post": {
            "uri": f"at://{did}/app.bsky.feed.post/{rkey}",
            "author": {"did": did, "handle": handle},
            "record": {
                "$type": "app.bsky.feed.post",
                "text": text,
                "createdAt": created_at,
            },
            "indexedAt": created_at,
        }
    }
    if embed is not None:
        item["post"]["record"]["embed"] = embed
    if is_repost:
        item["reason"] = {"$type": "app.bsky.feed.defs#reasonRepost"}
    return item


def _mock_client(pages: list[dict]) -> httpx.Client:
    client = MagicMock(spec=httpx.Client)
    responses = []
    for page in pages:
        resp = MagicMock(spec=httpx.Response)
        resp.json.return_value = page
        resp.raise_for_status = MagicMock()
        responses.append(resp)
    client.get.side_effect = responses
    return client


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------

class TestParseAtUri:
    def test_valid_uri(self):
        did, rkey = _parse_at_uri("at://did:plc:abc/app.bsky.feed.post/xyz789")
        assert did == "did:plc:abc"
        assert rkey == "xyz789"

    def test_not_at_uri(self):
        assert _parse_at_uri("https://bsky.app/foo") == (None, None)

    def test_too_short(self):
        assert _parse_at_uri("at://did:plc:abc") == (None, None)


class TestBuildPostUrl:
    def test_basic(self):
        url = _build_post_url("patriots.bsky.social", "rkey123")
        assert url == "https://bsky.app/profile/patriots.bsky.social/post/rkey123"


class TestExtractMedia:
    def test_no_embed(self):
        image_url, video_url, media_type = _extract_media({})
        assert image_url is None
        assert video_url is None
        assert media_type == "none"

    def test_images_embed(self):
        record = {
            "embed": {
                "$type": "app.bsky.embed.images",
                "images": [
                    {"image": {"ref": {"$link": "abc123"}, "mimeType": "image/jpeg"}, "alt": ""}
                ],
            }
        }
        image_url, video_url, media_type = _extract_media(record)
        assert media_type == "image"
        assert "abc123" in (image_url or "")
        assert video_url is None

    def test_images_embed_empty_list(self):
        record = {"embed": {"$type": "app.bsky.embed.images", "images": []}}
        _, _, media_type = _extract_media(record)
        assert media_type == "none"

    def test_video_embed(self):
        record = {
            "embed": {
                "$type": "app.bsky.embed.video",
                "video": {"ref": {"$link": "vid456"}, "mimeType": "video/mp4"},
            }
        }
        image_url, video_url, media_type = _extract_media(record)
        assert media_type == "video"
        assert "vid456" in (video_url or "")
        assert image_url is None

    def test_external_with_thumb(self):
        record = {
            "embed": {
                "$type": "app.bsky.embed.external",
                "external": {"uri": "https://example.com", "thumb": "thumbdata"},
            }
        }
        _, _, media_type = _extract_media(record)
        assert media_type == "image"

    def test_external_without_thumb(self):
        record = {
            "embed": {
                "$type": "app.bsky.embed.external",
                "external": {"uri": "https://example.com"},
            }
        }
        _, _, media_type = _extract_media(record)
        assert media_type == "none"


class TestToUtc:
    def test_naive_datetime_gets_utc(self):
        dt = datetime(2024, 1, 1, 12, 0)
        result = _to_utc(dt)
        assert result.tzinfo is not None
        assert result.utcoffset().total_seconds() == 0

    def test_aware_datetime_converted(self):
        from datetime import timedelta, timezone
        eastern = timezone(timedelta(hours=-5))
        dt = datetime(2024, 1, 1, 7, 0, tzinfo=eastern)
        result = _to_utc(dt)
        assert result.hour == 12  # 7 AM ET == 12 PM UTC


# ---------------------------------------------------------------------------
# BlueSkyCollector integration-style tests
# ---------------------------------------------------------------------------

class TestBlueSkyCollectorCollectPosts:
    def _collector(self, pages: list[dict]) -> BlueSkyCollector:
        return BlueSkyCollector(client=_mock_client(pages))

    def test_returns_collected_posts_within_window(self):
        page = {
            "feed": [_make_feed_item(rkey="r1", created_at="2024-01-15T14:00:00Z")],
            "cursor": None,
        }
        results = self._collector([page]).collect_posts(
            "patriots.bsky.social",
            window_start=datetime(2024, 1, 15, 13, 0, tzinfo=UTC),
            window_end=datetime(2024, 1, 15, 15, 0, tzinfo=UTC),
        )
        assert len(results) == 1
        post = results[0]
        assert isinstance(post, CollectedPost)
        assert post.platform == "bluesky"
        assert post.external_post_id == "r1"
        assert "bsky.app/profile" in post.post_url
        assert post.text == "Game day!"

    def test_skips_reposts(self):
        page = {
            "feed": [
                _make_feed_item(rkey="r1", created_at="2024-01-15T14:00:00Z"),
                _make_feed_item(rkey="r2", created_at="2024-01-15T14:05:00Z", is_repost=True),
            ],
            "cursor": None,
        }
        results = self._collector([page]).collect_posts(
            "patriots.bsky.social",
            window_start=datetime(2024, 1, 15, 13, 0, tzinfo=UTC),
            window_end=datetime(2024, 1, 15, 15, 0, tzinfo=UTC),
        )
        assert len(results) == 1
        assert results[0].external_post_id == "r1"

    def test_skips_posts_after_window_end(self):
        page = {
            "feed": [
                _make_feed_item(rkey="future", created_at="2024-01-15T20:00:00Z"),
                _make_feed_item(rkey="in_window", created_at="2024-01-15T14:00:00Z"),
            ],
            "cursor": None,
        }
        results = self._collector([page]).collect_posts(
            "patriots.bsky.social",
            window_start=datetime(2024, 1, 15, 13, 0, tzinfo=UTC),
            window_end=datetime(2024, 1, 15, 15, 0, tzinfo=UTC),
        )
        assert len(results) == 1
        assert results[0].external_post_id == "in_window"

    def test_stops_early_when_post_before_window_start(self):
        page = {
            "feed": [_make_feed_item(rkey="old", created_at="2024-01-15T10:00:00Z")],
            "cursor": "some_cursor",
        }
        collector = self._collector([page])
        results = collector.collect_posts(
            "patriots.bsky.social",
            window_start=datetime(2024, 1, 15, 13, 0, tzinfo=UTC),
            window_end=datetime(2024, 1, 15, 15, 0, tzinfo=UTC),
        )
        assert results == []
        # Stops early — only one page fetched even though cursor was present
        assert collector._client.get.call_count == 1

    def test_paginates_until_no_cursor(self):
        page1 = {
            "feed": [_make_feed_item(rkey="r1", created_at="2024-01-15T14:30:00Z")],
            "cursor": "next_cursor",
        }
        page2 = {
            "feed": [_make_feed_item(rkey="r2", created_at="2024-01-15T14:00:00Z")],
            "cursor": None,
        }
        collector = self._collector([page1, page2])
        results = collector.collect_posts(
            "patriots.bsky.social",
            window_start=datetime(2024, 1, 15, 13, 0, tzinfo=UTC),
            window_end=datetime(2024, 1, 15, 15, 0, tzinfo=UTC),
        )
        assert len(results) == 2
        assert collector._client.get.call_count == 2

    def test_returns_empty_on_api_error(self):
        client = MagicMock(spec=httpx.Client)
        client.get.side_effect = httpx.ConnectError("connection refused")
        collector = BlueSkyCollector(client=client)
        results = collector.collect_posts(
            "patriots.bsky.social",
            window_start=datetime(2024, 1, 15, 13, 0, tzinfo=UTC),
            window_end=datetime(2024, 1, 15, 15, 0, tzinfo=UTC),
        )
        assert results == []

    def test_empty_feed_returns_empty_list(self):
        page = {"feed": [], "cursor": None}
        results = self._collector([page]).collect_posts(
            "patriots.bsky.social",
            window_start=datetime(2024, 1, 15, 13, 0, tzinfo=UTC),
            window_end=datetime(2024, 1, 15, 15, 0, tzinfo=UTC),
        )
        assert results == []

    def test_post_with_image_embed(self):
        item = _make_feed_item(
            rkey="img1",
            created_at="2024-01-15T14:00:00Z",
            embed={
                "$type": "app.bsky.embed.images",
                "images": [{"image": {"ref": {"$link": "linkref"}, "mimeType": "image/jpeg"}, "alt": ""}],
            },
        )
        page = {"feed": [item], "cursor": None}
        results = self._collector([page]).collect_posts(
            "patriots.bsky.social",
            window_start=datetime(2024, 1, 15, 13, 0, tzinfo=UTC),
            window_end=datetime(2024, 1, 15, 15, 0, tzinfo=UTC),
        )
        assert len(results) == 1
        assert results[0].media_type == "image"
        assert results[0].has_video is False
        assert "linkref" in (results[0].image_url or "")

    def test_post_with_video_embed(self):
        item = _make_feed_item(
            rkey="vid1",
            created_at="2024-01-15T14:00:00Z",
            embed={
                "$type": "app.bsky.embed.video",
                "video": {"ref": {"$link": "vidlink"}, "mimeType": "video/mp4"},
            },
        )
        page = {"feed": [item], "cursor": None}
        results = self._collector([page]).collect_posts(
            "patriots.bsky.social",
            window_start=datetime(2024, 1, 15, 13, 0, tzinfo=UTC),
            window_end=datetime(2024, 1, 15, 15, 0, tzinfo=UTC),
        )
        assert len(results) == 1
        assert results[0].media_type == "video"
        assert results[0].has_video is True

    def test_skips_item_with_unparseable_uri(self):
        item = _make_feed_item(rkey="r1", created_at="2024-01-15T14:00:00Z")
        item["post"]["uri"] = "at://did:plc:x"  # too short — no rkey segment
        page = {"feed": [item], "cursor": None}
        results = self._collector([page]).collect_posts(
            "patriots.bsky.social",
            window_start=datetime(2024, 1, 15, 13, 0, tzinfo=UTC),
            window_end=datetime(2024, 1, 15, 15, 0, tzinfo=UTC),
        )
        assert results == []

    def test_fetch_page_passes_cursor(self):
        client = MagicMock(spec=httpx.Client)
        resp = MagicMock(spec=httpx.Response)
        resp.json.return_value = {"feed": [], "cursor": None}
        resp.raise_for_status = MagicMock()
        client.get.return_value = resp

        collector = BlueSkyCollector(client=client)
        collector._fetch_page("handle.bsky.social", cursor="tok123")

        call_kwargs = client.get.call_args
        assert call_kwargs[1]["params"]["cursor"] == "tok123"
        assert call_kwargs[1]["params"]["actor"] == "handle.bsky.social"
        assert call_kwargs[1]["params"]["filter"] == "posts_no_replies"


# ---------------------------------------------------------------------------
# Feature flag — load Settings via importlib to avoid lru_cache from prior
# settings singleton if one exists in sys.modules.
# ---------------------------------------------------------------------------

class TestFeatureFlag:
    def _fresh_settings(self, overrides: dict) -> object:
        """Load a fresh Settings instance without triggering validate_env."""
        # Clear cached module so we get a fresh class without lru_cache singleton
        for key in list(sys.modules):
            if key in ("sports_scraper.config", "sports_scraper.validate_env"):
                del sys.modules[key]

        # Stub validate_env so Settings() doesn't try to read the real env
        ve_mod = types.ModuleType("sports_scraper.validate_env")
        ve_mod.validate_env = lambda: None  # type: ignore[attr-defined]
        sys.modules["sports_scraper.validate_env"] = ve_mod

        config_mod = _load_module(
            "sports_scraper.config",
            SCRAPER_ROOT / "sports_scraper/config.py",
            "sports_scraper",
        )
        return config_mod.Settings.model_validate(overrides)

    def test_bluesky_disabled_by_default(self):
        s = self._fresh_settings({
            "DATABASE_URL": "postgresql+psycopg://u:p@localhost/db",
            "REDIS_URL": "redis://localhost:6379/0",
        })
        assert s.bluesky_enabled is False

    def test_bluesky_enabled_via_env(self):
        s = self._fresh_settings({
            "DATABASE_URL": "postgresql+psycopg://u:p@localhost/db",
            "REDIS_URL": "redis://localhost:6379/0",
            "ENABLE_BLUESKY_SOCIAL": "true",
        })
        assert s.bluesky_enabled is True


# ---------------------------------------------------------------------------
# persist_bluesky_posts — schema compliance and write-path tests.
# Stubs the DB layer so no real database connection is required.
# ---------------------------------------------------------------------------

def _make_post(
    rkey: str = "rkey1",
    handle: str = "team.bsky.social",
    text: str = "Game update!",
    media_type: str = "none",
    has_video: bool = False,
) -> CollectedPost:
    return CollectedPost(
        post_url=f"https://bsky.app/profile/{handle}/post/{rkey}",
        external_post_id=rkey,
        platform="bluesky",
        posted_at=datetime(2024, 1, 15, 14, 0, tzinfo=UTC),
        has_video=has_video,
        text=text,
        author_handle=handle,
        media_type=media_type,
    )


def _make_db_stubs():
    """Return (mock_session, fake_db_models, mock_insert_cls) for persist tests."""
    # Stub the insert statement chain: insert(Model).values(...).on_conflict_do_nothing(...)
    mock_result = MagicMock()
    mock_result.rowcount = 1

    mock_stmt = MagicMock()
    mock_stmt.on_conflict_do_nothing.return_value = mock_stmt

    mock_insert_cls = MagicMock(return_value=mock_stmt)
    mock_stmt_with_values = MagicMock()
    mock_stmt_with_values.on_conflict_do_nothing.return_value = mock_stmt_with_values

    # insert(Model) -> obj; obj.values(**kw) -> obj2; obj2.on_conflict_do_nothing(...) -> obj2
    insert_result = MagicMock()
    insert_result.values.return_value = mock_stmt_with_values
    mock_stmt_with_values.on_conflict_do_nothing.return_value = mock_stmt_with_values
    mock_insert_cls.return_value = insert_result

    mock_session = MagicMock()
    mock_session.execute.return_value = mock_result

    fake_tsp = MagicMock()
    fake_db_models = types.SimpleNamespace(TeamSocialPost=fake_tsp)

    # Wire stubs into sys.modules so the lazy imports inside persist_bluesky_posts resolve.
    fake_db_module = types.ModuleType("sports_scraper.db")
    fake_db_module.db_models = fake_db_models  # type: ignore[attr-defined]
    sys.modules["sports_scraper.db"] = fake_db_module

    # Stub sqlalchemy.dialects.postgresql so `from sqlalchemy.dialects.postgresql import insert` works.
    pg_mod = types.ModuleType("sqlalchemy.dialects.postgresql")
    pg_mod.insert = mock_insert_cls  # type: ignore[attr-defined]
    # Ensure parent stubs exist too.
    sys.modules.setdefault("sqlalchemy", types.ModuleType("sqlalchemy"))
    sys.modules.setdefault("sqlalchemy.dialects", types.ModuleType("sqlalchemy.dialects"))
    sys.modules["sqlalchemy.dialects.postgresql"] = pg_mod

    return mock_session, fake_db_models, mock_insert_cls, mock_stmt_with_values


class TestPersistBlueSkyPosts:
    def test_returns_new_count_for_inserted_rows(self):
        session, db_models, insert_cls, stmt = _make_db_stubs()
        posts = [_make_post("r1"), _make_post("r2")]
        count = persist_bluesky_posts(session, team_id=42, posts=posts)
        assert count == 2
        assert session.execute.call_count == 2

    def test_schema_compliance_fields(self):
        """CollectedPost fields map to the expected TeamSocialPost columns."""
        session, db_models, insert_cls, stmt = _make_db_stubs()
        post = _make_post("rkey99", handle="bulls.bsky.social", text="Let's go!")
        persist_bluesky_posts(session, team_id=7, posts=[post])

        # Inspect the values(...) call on the insert statement.
        call_kwargs = insert_cls.return_value.values.call_args[1]
        assert call_kwargs["platform"] == "bluesky"
        assert call_kwargs["team_id"] == 7
        assert call_kwargs["external_post_id"] == "rkey99"
        assert call_kwargs["post_url"] == "https://bsky.app/profile/bulls.bsky.social/post/rkey99"
        assert call_kwargs["tweet_text"] == "Let's go!"
        assert call_kwargs["source_handle"] == "bulls.bsky.social"
        assert call_kwargs["mapping_status"] == "unmapped"
        assert call_kwargs["game_phase"] == "unknown"
        assert call_kwargs["has_video"] is False
        assert call_kwargs["media_type"] == "none"

    def test_zero_rowcount_not_counted(self):
        session, db_models, insert_cls, stmt = _make_db_stubs()
        session.execute.return_value.rowcount = 0
        posts = [_make_post("dup")]
        count = persist_bluesky_posts(session, team_id=1, posts=posts)
        assert count == 0

    def test_empty_posts_returns_zero(self):
        session, db_models, insert_cls, stmt = _make_db_stubs()
        count = persist_bluesky_posts(session, team_id=1, posts=[])
        assert count == 0
        session.execute.assert_not_called()

    def test_none_media_type_defaults_to_none_string(self):
        session, db_models, insert_cls, stmt = _make_db_stubs()
        post = CollectedPost(
            post_url="https://bsky.app/profile/h/post/r",
            external_post_id="r",
            platform="bluesky",
            posted_at=datetime(2024, 1, 15, 14, 0, tzinfo=UTC),
            has_video=False,
            media_type=None,
        )
        persist_bluesky_posts(session, team_id=1, posts=[post])
        call_kwargs = insert_cls.return_value.values.call_args[1]
        assert call_kwargs["media_type"] == "none"

    def test_video_post_schema(self):
        session, db_models, insert_cls, stmt = _make_db_stubs()
        post = _make_post("vid1", media_type="video", has_video=True)
        persist_bluesky_posts(session, team_id=3, posts=[post])
        call_kwargs = insert_cls.return_value.values.call_args[1]
        assert call_kwargs["has_video"] is True
        assert call_kwargs["media_type"] == "video"

    def test_on_conflict_do_nothing_called(self):
        session, db_models, insert_cls, stmt = _make_db_stubs()
        persist_bluesky_posts(session, team_id=1, posts=[_make_post("r1")])
        stmt.on_conflict_do_nothing.assert_called_once_with(
            index_elements=["external_post_id"]
        )
