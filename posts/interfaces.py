"""Abstract ports for the posts bounded context (DIP wiring)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any
from uuid import UUID

from posts.model import OrgPost, OrgPostComment, OrgPostMedia


class PostStore(ABC):
    """Persistence port for posts plus their feed, draft, pin and trash
    projections. Publish state lives in status (active | draft); trash is
    the deleted_at stamp, so every projection move happens here."""

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
        status: str = "active",
        blocks_json: str = "",
        cover_media_id: UUID | None = None,
        revision_of: UUID | None = None,
    ) -> OrgPost:
        """Insert the canonical row, its feed or draft entry, media links."""

    @abstractmethod
    def get(self, post_id: UUID) -> OrgPost | None:
        """Load one canonical row by primary key."""

    @abstractmethod
    def list_feed(self, org_id: UUID, limit: int) -> list[Any]:
        """Newest-first feed rows (post_id + kind) of one org, capped."""

    @abstractmethod
    def list_timeline(self, cursor: UUID | None, limit: int) -> list[Any]:
        """Newest-first global announcement rows (post_id + org_id)."""

    @abstractmethod
    def count_feed(self, org_id: UUID) -> int:
        """Published total of one org (partition row count)."""

    @abstractmethod
    def list_pinned(self, org_id: UUID, limit: int = 5) -> list[UUID]:
        """Pinned post ids of one org, newest post first."""

    @abstractmethod
    def list_drafts(
        self, org_id: UUID, author_id: UUID, limit: int
    ) -> list[UUID]:
        """Newest-first draft ids of one author inside one org."""

    @abstractmethod
    def count_drafts(self, org_id: UUID, author_id: UUID) -> int:
        """Live draft total of one author inside one org."""

    @abstractmethod
    def list_trash(self, org_id: UUID, limit: int) -> list[Any]:
        """Newest-first trash rows (post_id + author_id + status)."""

    @abstractmethod
    def update_body(
        self, post: OrgPost, title: str, body: str, now: datetime
    ) -> None:
        """Replace title/body and stamp edited_at."""

    @abstractmethod
    def update_content(
        self,
        post: OrgPost,
        kind: str,
        title: str,
        body: str,
        blocks_json: str,
        cover_media_id: UUID | None,
        now: datetime,
    ) -> None:
        """Replace the article fields and stamp edited_at."""

    @abstractmethod
    def replace_media(self, post_id: UUID, media_ids: list[UUID]) -> None:
        """Swap the post media link rows for the given ordered ids."""

    @abstractmethod
    def set_pinned(
        self, post: OrgPost, pinned_at: datetime | None, now: datetime
    ) -> None:
        """Toggle the pin: canonical pinned_at plus the pinned feed row."""

    @abstractmethod
    def set_status(self, post: OrgPost, status: str, now: datetime) -> None:
        """Publish (active) or unpublish (draft) and move projections."""

    @abstractmethod
    def soft_delete(self, post: OrgPost, now: datetime) -> None:
        """Stamp deleted_at, unpin, and move the post into the trash."""

    @abstractmethod
    def restore(self, post: OrgPost, now: datetime) -> None:
        """Clear deleted_at and return the post to its feed or drafts."""

    @abstractmethod
    def delete(self, post: OrgPost) -> None:
        """Drop the canonical row and every projection plus media links."""

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


class AnnouncementFeedEvents(ABC):
    """Realtime fan-out port for the public timeline (best-effort)."""

    @abstractmethod
    def feed_changed(self, action: str, post_id: UUID, org_id: UUID) -> None:
        """Broadcast a refetch hint to announcements:feed subscribers."""
