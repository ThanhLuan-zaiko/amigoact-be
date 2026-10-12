"""Org board business rules: posts and pins. No FastAPI here."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from core.exceptions import ForbiddenError, NotFoundError
from core.ids import uuid7
from core.security import utcnow
from notifications.interfaces import NotificationPort
from orgs.interfaces import (
    MediaRepository,
    MemberRepository,
    OrgRepository,
    UserDirectory,
)
from orgs.member_helpers import is_active_member, live_org
from posts.dtos import PostMediaBrief, PostPage, PostSnapshot
from posts.helpers import notify_announcement, parse_cursor, post_or_404
from posts.interfaces import CommentStore, PostEvents, PostStore
from posts.model import OrgPost
from rbac.interfaces import AccessControl

KINDS: tuple[str, ...] = ("announcement", "discussion")
MAX_ATTACHMENTS = 4


class PostService:
    """Board rules: member posting, manager announce/pin/moderate."""

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
    ) -> None:
        self._posts = posts
        self._comments = comments
        self._orgs = orgs
        self._members = members
        self._users = users
        self._media = media
        self._access = access
        self._events = events
        self._notifications = notifications

    # ---- guards ----------------------------------------------------------

    def _require_member(self, org_id: UUID, user_id: UUID, action: str):
        org = live_org(self._orgs, org_id)
        if org.owner_id == user_id or is_active_member(
            self._members, org_id, user_id
        ):
            return org
        self._access.record(
            org_id, user_id, action, "post", None, "denied"
        )
        raise ForbiddenError("Only org members can do this.")

    def _require_manage(
        self, org_id: UUID, org_owner: UUID, user_id: UUID, action: str,
        target_id: UUID | None = None,
    ) -> None:
        if org_owner == user_id:
            return
        if is_active_member(
            self._members, org_id, user_id
        ) and self._access.has_permission(org_id, user_id, "post:manage"):
            return
        self._access.record(
            org_id, user_id, action, "post", target_id, "denied"
        )
        raise ForbiddenError("Only org managers can do this.")

    def _emit(self, org_id: UUID, action: str, post_id: UUID, actor_id: UUID,
              detail: str | None = None) -> None:
        try:
            self._events.feed_changed(org_id, action, post_id, actor_id, detail)
        except Exception:  # noqa: BLE001 - realtime is best-effort
            pass

    # ---- snapshots --------------------------------------------------------

    def _media_briefs(self, post_id: UUID) -> list[PostMediaBrief]:
        briefs: list[PostMediaBrief] = []
        for link in self._posts.list_media(post_id):
            asset = self._media.get_asset(link.asset_id)
            if asset is None:
                continue
            briefs.append(
                PostMediaBrief(
                    asset_id=asset.asset_id,
                    file_url=asset.file_url,
                    mime=asset.mime,
                )
            )
        return briefs

    def _snapshot(self, row: OrgPost, *, with_media: bool) -> PostSnapshot:
        brief = self._users.get_brief(row.author_id)
        return PostSnapshot(
            post_id=row.post_id,
            org_id=row.org_id,
            author_id=row.author_id,
            author_name=brief.full_name if brief else "Unknown user",
            kind=row.kind or "discussion",
            title=row.title or "",
            body=row.body or "",
            pinned_at=row.pinned_at,
            edited_at=row.edited_at,
            media=self._media_briefs(row.post_id) if with_media else [],
            comment_count=self._comments.count(row.post_id),
            created_at=row.created_at,
        )

    # ---- board reads ------------------------------------------------------

    def list_posts(
        self,
        org_id: UUID,
        viewer_id: UUID,
        *,
        limit: int = 20,
        cursor: str | None = None,
        kind: str | None = None,
    ) -> PostPage:
        """Newest-first page; kind filter over-fetches, never skips items."""
        org = self._require_member(org_id, viewer_id, "post.list")
        start = parse_cursor(cursor)
        # Feed ids are uuid7-ordered, so the last scanned id is always a
        # safe resume point: nothing filtered out is ever skipped.
        fetch = min(limit * 3, 150) if kind is not None else limit + 1
        scanned = self._posts.list_feed(org_id, start, fetch)
        items: list[PostSnapshot] = []
        last_scanned = start
        for post_id in scanned:
            last_scanned = post_id
            row = self._posts.get(post_id)
            if row is None or (row.status or "active") != "active":
                continue
            if kind is not None and (row.kind or "discussion") != kind:
                continue
            items.append(self._snapshot(row, with_media=True))
            if len(items) >= limit:
                break
        next_cursor = (
            str(last_scanned)
            if len(scanned) == fetch and last_scanned is not None
            else None
        )
        pinned: list[PostSnapshot] = []
        if start is None:
            for post_id in self._posts.list_pinned(org_id):
                row = self._posts.get(post_id)
                if row is not None and (row.status or "active") == "active":
                    pinned.append(self._snapshot(row, with_media=True))
        viewer_permissions = (
            sorted(self._access.effective_permissions(org_id, viewer_id))
            if org.owner_id != viewer_id
            else []
        )
        return PostPage(
            items=items,
            pinned=pinned,
            next_cursor=next_cursor,
            viewer_role="owner" if org.owner_id == viewer_id else "member",
            viewer_permissions=viewer_permissions,
        )

    def get_post(
        self, org_id: UUID, post_id: UUID, viewer_id: UUID
    ) -> PostSnapshot:
        self._require_member(org_id, viewer_id, "post.read")
        return self._snapshot(
            post_or_404(self._posts, org_id, post_id), with_media=True
        )

    # ---- board writes -----------------------------------------------------

    def create_post(
        self,
        org_id: UUID,
        actor_id: UUID,
        kind: str,
        title: str,
        body: str,
        media_ids: list[UUID],
    ) -> PostSnapshot:
        """Member posts a discussion; announcements need post:announce."""
        org = self._require_member(org_id, actor_id, "post.create")
        if kind == "announcement":
            if org.owner_id != actor_id and not (
                is_active_member(self._members, org_id, actor_id)
                and self._access.has_permission(
                    org_id, actor_id, "post:announce"
                )
            ):
                self._access.record(
                    org_id, actor_id, "post.create", "post", None, "denied"
                )
                raise ForbiddenError(
                    "Only org managers can publish announcements."
                )
        assets = self._validate_media(org_id, media_ids)
        now = utcnow()
        post_id = uuid7()
        row = self._posts.create(
            post_id, org_id, actor_id, kind, title, body,
            [asset.asset_id for asset in assets], now,
        )
        self._access.record(
            org_id, actor_id, "post.create", "post", post_id, "allowed"
        )
        self._emit(org_id, "post.created", post_id, actor_id, detail=kind)
        if kind == "announcement":
            notify_announcement(
                self._members, self._notifications, org_id, org.name,
                post_id, actor_id, title,
            )
        fresh = self._posts.get(post_id)
        assert fresh is not None
        return self._snapshot(fresh, with_media=True)

    def _validate_media(self, org_id: UUID, media_ids: list[UUID]):
        ids = list(dict.fromkeys(media_ids))[:MAX_ATTACHMENTS]
        assets = []
        for asset_id in ids:
            asset = self._media.get_asset(asset_id)
            if (
                asset is None
                or asset.owner_id != org_id
                or not (asset.mime or "").startswith("image/")
                or (asset.upload_status or "active") != "active"
            ):
                raise NotFoundError("Attachment not found.")
            assets.append(asset)
        return assets

    def update_post(
        self,
        org_id: UUID,
        post_id: UUID,
        actor_id: UUID,
        title: str,
        body: str,
    ) -> PostSnapshot:
        """Only the author edits; managers moderate by deleting instead."""
        self._require_member(org_id, actor_id, "post.update")
        row = post_or_404(self._posts, org_id, post_id)
        if row.author_id != actor_id:
            self._access.record(
                org_id, actor_id, "post.update", "post", post_id, "denied"
            )
            raise ForbiddenError("Only the author can edit this post.")
        now = utcnow()
        self._posts.update_body(row, title, body, now)
        self._access.record(
            org_id, actor_id, "post.update", "post", post_id, "allowed"
        )
        self._emit(org_id, "post.updated", post_id, actor_id)
        fresh = self._posts.get(post_id)
        assert fresh is not None
        return self._snapshot(fresh, with_media=True)

    def delete_post(self, org_id: UUID, post_id: UUID, actor_id: UUID) -> None:
        org = self._require_member(org_id, actor_id, "post.delete")
        row = post_or_404(self._posts, org_id, post_id)
        if row.author_id != actor_id:
            self._require_manage(
                org_id, org.owner_id, actor_id, "post.delete", post_id
            )
        self._comments.remove_all(post_id)
        self._posts.delete(row)
        self._access.record(
            org_id, actor_id, "post.delete", "post", post_id, "allowed"
        )
        self._emit(org_id, "post.deleted", post_id, actor_id)

    def set_pinned(
        self, org_id: UUID, post_id: UUID, actor_id: UUID, pinned: bool
    ) -> PostSnapshot:
        org = self._require_member(org_id, actor_id, "post.pin")
        row = post_or_404(self._posts, org_id, post_id)
        self._require_manage(
            org_id, org.owner_id, actor_id, "post.pin", post_id
        )
        now = utcnow()
        self._posts.set_pinned(row, now if pinned else None, now)
        self._access.record(
            org_id, actor_id, "post.pin", "post", post_id, "allowed"
        )
        self._emit(
            org_id, "post.pinned" if pinned else "post.unpinned",
            post_id, actor_id,
        )
        fresh = self._posts.get(post_id)
        assert fresh is not None
        return self._snapshot(fresh, with_media=True)
