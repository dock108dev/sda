"""Models for social media post collection."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class GamePhase(str, Enum):
    pregame = "pregame"
    in_game = "in_game"
    postgame = "postgame"
    unknown = "unknown"


class CollectedPost(BaseModel):
    """A post collected from a team's X timeline."""

    post_url: str = Field(..., description="Full URL to the X post")
    external_post_id: str | None = Field(default=None, description="Platform-specific post ID")
    platform: str = Field(default="x", description="Social platform identifier")
    posted_at: datetime = Field(..., description="When the post was published")
    has_video: bool = Field(default=False, description="Whether post contains video")
    text: str | None = Field(default=None, description="Post text/caption")
    author_handle: str | None = Field(default=None, description="X handle of the author")
    # Media content fields for custom embed display
    video_url: str | None = Field(default=None, description="Direct video URL if available")
    image_url: str | None = Field(default=None, description="Thumbnail or image URL")
    media_type: str | None = Field(default=None, description="video, image, or none")
