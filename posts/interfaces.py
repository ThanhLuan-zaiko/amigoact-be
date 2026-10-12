"""Abstract ports for the posts bounded context (DIP wiring)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from posts.model import OrgPost, OrgPostComment, OrgPostMedia


class PostStore(ABC):
    """Persistence port for posts plus their feed and pin projections."""

    @abstractmethod
    def create(
        self,
        post_id: UUID,
        org_id: UUID,
        author_id: UUID,
        kind: str,
        title: str,
        body: str,
        media_ids: list[UUID],
        now: datetime,
    ) -> OrgPost:
        """Insert the canonical row, the feed entry and media links."""

    @abstractmethod
    def get(self, post_id: UUID) -> OrgPost | None:
        """Load one canonical row by primary key."""

    @abstractmethod
    def list_feed(
        self, org_id: UUID, cursor: UUID | None, limit: int
    ) -> list[UUID]:
        """Newest-first feed ids; cursor is the last post id seen."""

    @abstractmethod
    def list_pinned(self, org_id: UUID, limit: int = 5) -> list[UUID]:
        """Pinned post ids of one org, newest post first."""

    @abstractmethod
    def update_body(
        self, post: OrgPost, title: str, body: str, now: datetime
    ) -> None:
        """Replace title/body and stamp edited_at."""

    @abstractmethod
    def set_pinned(
        self, post: OrgPost, pinned_at: datetime | None, now: datetime
    ) -> None:
        """Toggle the pin: canonical pinned_at plus the pinned feed row."""

    @abstractmethod
    def delete(self, post: OrgPost) -> None:
        """Drop the canonical row, feed entry, pin entry and media links."""

    @abstractmethod
    def list_media(self, post_id: UUID) -> list[OrgPostMedia]:
        """Attachment link rows of one post, in display order."""


class CommentStore(ABC):
    """Persistence port for comments plus their per-post counter."""

    @abstractmethod
    def add(
        self, post_id: UUID, comment_id: UUID, author_id: UUID, body: str,
        now: datetime,
    ) -> OrgPostComment:
        """Append one comment and increment the post counter."""

    @abstractmethod
    def get(self, post_id: UUID, comment_id: UUID) -> OrgPostComment | None:
        """Load one comment inside its post partition."""

    @abstractmethod
    def list_page(
        self, post_id: UUID, cursor: UUID | None, limit: int
    ) -> list[OrgPostComment]:
        """Oldest-first comment page; cursor is the last comment id seen."""

    @abstractmethod
    def remove(self, comment: OrgPostComment) -> None:
        """Delete one comment row and decrement the post counter."""

    @abstractmethod
    def remove_all(self, post_id: UUID) -> None:
        """Drop the whole comment partition plus the counter row."""

    @abstractmethod
    def count(self, post_id: UUID) -> int:
        """Current comment total (counter row; missing reads as zero)."""


class PostEvents(ABC):
    """Realtime fan-out port for board changes (best-effort)."""

    @abstractmethod
    def feed_changed(
        self,
        org_id: UUID,
        action: str,
        post_id: UUID,
        actor_id: UUID,
        detail: str | None = None,
    ) -> None:
        """Broadcast one post/comment event to posts:{org_id} subscribers."""
