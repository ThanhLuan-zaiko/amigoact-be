"""Comment business rules on board posts. No FastAPI, no CQL here."""

from __future__ import annotations

from uuid import UUID

from core.exceptions import ForbiddenError, NotFoundError
from core.ids import uuid7
from core.security import utc_aware, utcnow
from orgs.interfaces import MemberRepository, OrgRepository, UserDirectory
from orgs.member_helpers import is_active_member, live_org
from posts.dtos import CommentPage, CommentSnapshot
from posts.helpers import parse_cursor, post_or_404
from posts.interfaces import (
    AnnouncementFeedEvents,
    CommentStore,
    PostEvents,
    PostStore,
)
from posts.model import OrgPostComment
from rbac.interfaces import AccessControl


class CommentService:
    """Thread rules: members comment, authors or post:manage moderate."""

    def __init__(
        self,
        posts: PostStore,
        comments: CommentStore,
        orgs: OrgRepository,
        members: MemberRepository,
        users: UserDirectory,
        access: AccessControl,
        events: PostEvents,
        announcements: AnnouncementFeedEvents | None = None,
    ) -> None:
        self._posts = posts
        self._comments = comments
        self._orgs = orgs
        self._members = members
        self._users = users
        self._access = access
        self._events = events
        self._announcements = announcements

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

    def _emit(self, org_id: UUID, action: str, post_id: UUID,
              actor_id: UUID) -> None:
        try:
            self._events.feed_changed(org_id, action, post_id, actor_id)
        except Exception:  # noqa: BLE001 - realtime is best-effort
            pass

    def _emit_public(self, org_id: UUID, post_id: UUID) -> None:
        """Refresh the teaser's comment_count on announcements:feed."""
        if self._announcements is None:
            return
        try:
            self._announcements.feed_changed("updated", post_id, org_id)
        except Exception:  # noqa: BLE001 - realtime is best-effort
            pass

    def list_comments(
        self,
        org_id: UUID,
        post_id: UUID,
        viewer_id: UUID,
        *,
        limit: int = 20,
        cursor: str | None = None,
    ) -> CommentPage:
        self._require_member(org_id, viewer_id, "comment.list")
        post_or_404(self._posts, org_id, post_id)
        start = parse_cursor(cursor)
        rows = self._comments.list_page(post_id, start, limit + 1)
        page = rows[:limit]
        next_cursor = (
            str(page[-1].comment_id) if len(rows) > limit else None
        )
        return CommentPage(
            items=[self._snapshot(row) for row in page],
            next_cursor=next_cursor,
        )

    def add_comment(
        self, org_id: UUID, post_id: UUID, actor_id: UUID, body: str
    ) -> CommentSnapshot:
        self._require_member(org_id, actor_id, "comment.create")
        post = post_or_404(self._posts, org_id, post_id)
        row = self._comments.add(post_id, uuid7(), actor_id, body, utcnow())
        self._access.record(
            org_id, actor_id, "comment.create", "post", post_id, "allowed"
        )
        self._emit(org_id, "comment.created", post_id, actor_id)
        if (post.kind or "discussion") == "announcement":
            self._emit_public(org_id, post_id)
        return self._snapshot(row)

    def delete_comment(
        self, org_id: UUID, post_id: UUID, comment_id: UUID, actor_id: UUID
    ) -> None:
        org = self._require_member(org_id, actor_id, "comment.delete")
        post = post_or_404(self._posts, org_id, post_id)
        row = self._comments.get(post_id, comment_id)
        if row is None:
            raise NotFoundError("Comment not found.")
        if row.author_id != actor_id:
            self._require_manage(
                org_id, org.owner_id, actor_id, "comment.delete", post_id
            )
        self._comments.remove(row)
        self._access.record(
            org_id, actor_id, "comment.delete", "post", post_id, "allowed"
        )
        self._emit(org_id, "comment.deleted", post_id, actor_id)
        if (post.kind or "discussion") == "announcement":
            self._emit_public(org_id, post_id)

    def _snapshot(self, row: OrgPostComment) -> CommentSnapshot:
        brief = self._users.get_brief(row.author_id)
        return CommentSnapshot(
            comment_id=row.comment_id,
            post_id=row.post_id,
            author_id=row.author_id,
            author_name=brief.full_name if brief else "Unknown user",
            body=row.body or "",
            created_at=utc_aware(row.created_at),
        )
