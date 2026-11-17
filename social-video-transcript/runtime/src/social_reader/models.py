"""Data model for read_page (docs/IMPLEMENTATION_SPEC.md §3.2).

Extractors fill an Extraction; the service adds request metadata and turns it
into the public PageReadResult dict.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .errors import RightsState


@dataclass
class Notice:
    """A warning surfaced to the user (truncation, low confidence, rights...)."""

    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass
class Stats:
    likes: int | None = None
    collects: int | None = None
    comments: int | None = None
    shares: int | None = None

    def to_dict(self) -> dict[str, int | None]:
        return {
            "likes": self.likes,
            "collects": self.collects,
            "comments": self.comments,
            "shares": self.shares,
        }


@dataclass
class Media:
    images: list[str] = field(default_factory=list)
    video_url: str | None = None
    cover_url: str | None = None
    duration_ms: int = 0
    audio_url: str | None = None


@dataclass
class Comment:
    """A public comment. Commenter identity is deliberately not kept."""

    content: str
    likes: int | None = None


@dataclass
class Extraction:
    platform: str
    type: str  # article | note | video | page
    title: str
    body: str  # plain text, never raw HTML
    extractor_version: str
    author: str = ""
    published_at: datetime | None = None
    stats: Stats = field(default_factory=Stats)
    tags: list[str] = field(default_factory=list)
    media: Media = field(default_factory=Media)
    comments: list[Comment] = field(default_factory=list)
    canonical_url: str | None = None
    rights_state: RightsState = RightsState.PUBLIC
    confidence: float = 0.5
    warnings: list[Notice] = field(default_factory=list)

    def warn(self, code: str, message: str) -> None:
        if all(w.code != code for w in self.warnings):
            self.warnings.append(Notice(code, message))


def media_to_dict(media: Media, include_media: bool) -> dict[str, Any]:
    """Media URLs (often signed CDN links) are only returned when asked for."""
    result = {
        "images": list(media.images) if include_media else [],
        "image_count": len(media.images),
        "video_url": media.video_url if include_media else None,
        "has_video": media.video_url is not None,
        "duration_ms": media.duration_ms,
    }
    if media.audio_url:
        result["has_audio"] = True
        result["audio_url"] = media.audio_url if include_media else None
    return result
