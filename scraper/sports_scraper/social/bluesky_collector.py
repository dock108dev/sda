"""
Bluesky AT Protocol collector for team social posts.

Prototype integration — gated by the ENABLE_BLUESKY_SOCIAL feature flag.
Does not affect production X/Twitter scraping paths.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from .models import CollectedPost

logger = logging.getLogger(__name__)

_BSKY_PUBLIC_API = "https://public.api.bsky.app/xrpc"
_BSKY_APP_BASE = "https://bsky.app/profile"
_DEFAULT_LIMIT = 25
_REQUEST_TIMEOUT = 15


def _parse_at_uri(uri: str) -> tuple[str, str] | tuple[None, None]:
    """Return (did_or_handle, rkey) from an AT Protocol URI, or (None, None)."""
    if not uri.startswith("at://"):
        return None, None
    parts = uri[5:].split("/")
    if len(parts) < 3:
        return None, None
    return parts[0], parts[2]


def _build_post_url(handle: str, rkey: str) -> str:
    return f"{_BSKY_APP_BASE}/{handle}/post/{rkey}"


def _extract_media(record: dict[str, Any]) -> tuple[str | None, str | None, str]:
    """Return (image_url, video_url, media_type) from a Bluesky post record."""
    embed = record.get("embed") or {}
    embed_type = embed.get("$type", "")

    if "images" in embed_type:
        images = embed.get("images", [])
        if images:
            link = images[0].get("image", {}).get("ref", {}).get("$link")
            image_url = f"https://cdn.bsky.app/img/feed_fullsize/plain/{link}@jpeg" if link else None
            return image_url, None, "image"

    if "video" in embed_type:
        link = embed.get("video", {}).get("ref", {}).get("$link")
        video_url = f"https://video.bsky.app/watch/{link}" if link else None
        return None, video_url, "video"

    if "external" in embed_type and embed.get("external", {}).get("thumb"):
        return None, None, "image"

    return None, None, "none"


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class BlueSkyCollector:
    """
    Collect posts from a Bluesky actor feed using the public AT Protocol API.

    No authentication is required for public accounts. Uses cursor-based
    pagination and stops as soon as posts fall before the window start.

    Feature flag: check ``settings.bluesky_enabled`` before calling this
    class from any production task.
    """

    def __init__(
        self,
        *,
        api_base: str = _BSKY_PUBLIC_API,
        limit: int = _DEFAULT_LIMIT,
        timeout: int = _REQUEST_TIMEOUT,
        client: httpx.Client | None = None,
    ) -> None:
        self._api_base = api_base
        self._limit = limit
        self._timeout = timeout
        self._client = client or httpx.Client()

    def collect_posts(
        self,
        bsky_handle: str,
        window_start: datetime,
        window_end: datetime,
    ) -> list[CollectedPost]:
        """
        Return CollectedPost records for *bsky_handle* within [window_start, window_end].

        Skips reposts. Stops paginating once posts are older than window_start.
        """
        posts: list[CollectedPost] = []
        cursor: str | None = None

        start_utc = _to_utc(window_start)
        end_utc = _to_utc(window_end)

        while True:
            try:
                batch, cursor = self._fetch_page(bsky_handle, cursor)
            except httpx.HTTPError as exc:
                logger.warning(
                    "Bluesky API request failed for @%s: %s",
                    bsky_handle,
                    exc,
                    exc_info=True,
                )
                break

            if not batch:
                break

            stop_early = False
            for item in batch:
                # Feed items with a "reason" key are reposts — skip them.
                if "reason" in item:
                    continue

                post = item.get("post", {})
                record = post.get("record", {})
                created_raw = record.get("createdAt") or post.get("indexedAt")
                if not created_raw:
                    continue

                try:
                    posted_at = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
                except ValueError:
                    logger.debug(
                        "Unparseable createdAt %r for @%s — skipping",
                        created_raw,
                        bsky_handle,
                    )
                    continue

                if posted_at > end_utc:
                    continue
                if posted_at < start_utc:
                    stop_early = True
                    break

                uri = post.get("uri", "")
                author = post.get("author", {})
                author_handle = author.get("handle", bsky_handle)
                _, rkey = _parse_at_uri(uri)
                if not rkey:
                    logger.debug("Could not parse AT URI %r — skipping", uri)
                    continue

                image_url, video_url, media_type = _extract_media(record)

                posts.append(
                    CollectedPost(
                        post_url=_build_post_url(author_handle, rkey),
                        external_post_id=rkey,
                        platform="bluesky",
                        posted_at=posted_at,
                        has_video=(media_type == "video"),
                        text=record.get("text"),
                        author_handle=author_handle,
                        video_url=video_url,
                        image_url=image_url,
                        media_type=media_type,
                    )
                )

            if stop_early or not cursor:
                break

        logger.info(
            "BlueSkyCollector: %d posts for @%s in [%s, %s]",
            len(posts),
            bsky_handle,
            start_utc.isoformat(),
            end_utc.isoformat(),
        )
        return posts

    def _fetch_page(
        self, handle: str, cursor: str | None
    ) -> tuple[list[dict[str, Any]], str | None]:
        params: dict[str, Any] = {
            "actor": handle,
            "limit": self._limit,
            "filter": "posts_no_replies",
        }
        if cursor:
            params["cursor"] = cursor

        resp = self._client.get(
            f"{self._api_base}/app.bsky.feed.getAuthorFeed",
            params=params,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("feed", []), data.get("cursor")


def persist_bluesky_posts(
    session: Any,
    team_id: int,
    posts: list[CollectedPost],
) -> int:
    """Persist Bluesky CollectedPost records to TeamSocialPost via upsert.

    Sets mapping_status='unmapped' and game_phase='unknown' so the existing
    tweet_mapper flow can assign game context without modification.
    Duplicate external_post_id rows are silently ignored.

    Args:
        session: Synchronous SQLAlchemy Session.
        team_id: ID of the team in sports_teams.
        posts: Records from BlueSkyCollector.collect_posts().

    Returns:
        Count of newly inserted rows.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from ..db import db_models

    new_count = 0
    for post in posts:
        stmt = (
            pg_insert(db_models.TeamSocialPost)
            .values(
                team_id=team_id,
                platform="bluesky",
                external_post_id=post.external_post_id,
                post_url=post.post_url,
                posted_at=post.posted_at,
                tweet_text=post.text,
                has_video=post.has_video,
                video_url=post.video_url,
                image_url=post.image_url,
                media_type=post.media_type or "none",
                source_handle=post.author_handle,
                mapping_status="unmapped",
                game_phase="unknown",
            )
            .on_conflict_do_nothing(index_elements=["external_post_id"])
        )
        result = session.execute(stmt)
        if result.rowcount:
            new_count += 1
    return new_count
