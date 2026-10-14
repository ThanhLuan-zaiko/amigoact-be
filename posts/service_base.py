"""Shared wiring for the board services: guards, snapshots, events."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from core.exceptions import PostContentRequiredError, PostTitleRequiredError
from core.media import MediaStore
from notifications.interfaces import NotificationPort
from orgs.interfaces import (
    MediaRepository,
    MemberRepository,
    OrgRepository,
    UserDirectory,
)
from posts.blocks import has_content
from posts.dtos import PostSnapshot
from posts.guards import BoardGuard
from posts.interfaces import (
    AnnouncementFeedEvents,
    CommentStore,
    PostEvents,
    PostStore,
)
from posts.media_rules import PostMediaRules
from posts.model import OrgPost
from posts.snapshots import PostSnapshots
from rbac.interfaces import AccessControl


# Bounded scans for numbered paging: page windows never fetch more than
# WINDOW_LIMIT ids; filtered totals scan up to SCAN_LIMIT projection rows.
WINDOW_LIMIT = 500
SCAN_LIMIT = 3000


def check_publishable(
    kind: str, title: str, body: str, blocks: list[Any]
) -> None:
    """A published post needs content; a published announcement a title."""
    if not (body or has_content(blocks)):
        raise PostContentRequiredError("Post content is required.")
    if kind == "announcement" and not title:
        raise PostTitleRequiredError("Announcements require a title.")


class BoardServiceBase:
    """Constructor + helpers reused by PostService and lifecycle rules."""

    def __init__(
        self,
        posts: PostStore,
        comments: CommentStore,
        orgs: OrgRepository,
        members: MemberRepository,
        users: UserDirectory,
        media: MediaRepository,
        access: AccessControl,
        events: PostEvents,
        notifications: NotificationPort | None = None,
        files: MediaStore | None = None,
        announcements: AnnouncementFeedEvents | None = None,
    ) -> None:
        self._posts = posts
        self._comments = comments
        self._members = members
        self._events = events
        self._notifications = notifications
        self._announcements = announcements
        self._guard = BoardGuard(orgs, members, access)
        self._snapshots = PostSnapshots(posts, comments, users, media)
        self._media_rules = PostMediaRules(media, files)

    def _emit(
        self, org_id: UUID, action: str, post_id: UUID, actor_id: UUID,
        detail: str | None = None,
    ) -> None:
        try:
            self._events.feed_changed(org_id, action, post_id, actor_id, detail)
        except Exception:  # noqa: BLE001 - realtime is best-effort
            pass

    def _emit_public(
        self, org_id: UUID, action: str, post_id: UUID, kind: str | None
    ) -> None:
        """Refetch hint for the guest timeline; announcements only."""
        if (kind or "discussion") != "announcement":
            return
        if self._announcements is None:
            return
        try:
            self._announcements.feed_changed(action, post_id, org_id)
        except Exception:  # noqa: BLE001 - realtime is best-effort
            pass

    def _window(
        self,
        ids: list[UUID],
        page: int,
        limit: int,
        accept: Callable[[OrgPost], bool],
    ) -> list[PostSnapshot]:
        """Slice the numbered page window and join ids to snapshots.

        Only the page slice hits the canonical table; a dropped row means
        projection drift, which the accept check absorbs silently.
        """
        start = (page - 1) * limit
        items: list[PostSnapshot] = []
        for post_id in ids[start : start + limit]:
            row = self._posts.get(post_id)
            if row is None or not accept(row):
                continue
            items.append(self._snapshots.build(row))
        return items
