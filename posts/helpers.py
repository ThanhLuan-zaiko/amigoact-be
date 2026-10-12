"""Shared board helpers: cursor parsing, post lookup, announce fan-out."""

from __future__ import annotations

import json
from uuid import UUID

from core.exceptions import NotFoundError
from notifications.interfaces import NotificationPort
from orgs.interfaces import MemberRepository
from posts.interfaces import PostStore
from posts.model import OrgPost


def parse_cursor(cursor: str | None) -> UUID | None:
    """A cursor is the last entity id seen; anything else is ignored."""
    if not cursor:
        return None
    try:
        return UUID(cursor)
    except ValueError:
        return None


def is_trashed(row: OrgPost) -> bool:
    return getattr(row, "deleted_at", None) is not None


def is_draft(row: OrgPost) -> bool:
    return (row.status or "active") == "draft"


def post_or_404(posts: PostStore, org_id: UUID, post_id: UUID) -> OrgPost:
    """Load a published, non-trashed post inside one org or fail with 404."""
    row = posts.get(post_id)
    if (
        row is None
        or row.org_id != org_id
        or (row.status or "active") != "active"
        or is_trashed(row)
    ):
        raise NotFoundError("Post not found.")
    return row


def visible_post_or_404(
    posts: PostStore, org_id: UUID, post_id: UUID, viewer_id: UUID
) -> OrgPost:
    """Published post, or the viewer's own draft; trash reads as 404."""
    row = posts.get(post_id)
    if (
        row is None
        or row.org_id != org_id
        or is_trashed(row)
        or (row.status or "active") not in ("active", "draft")
        or (is_draft(row) and row.author_id != viewer_id)
    ):
        raise NotFoundError("Post not found.")
    return row


def any_post_or_404(posts: PostStore, org_id: UUID, post_id: UUID) -> OrgPost:
    """Any state (live, draft or trashed) inside one org, else 404."""
    row = posts.get(post_id)
    if row is None or row.org_id != org_id:
        raise NotFoundError("Post not found.")
    return row


def notify_announcement(
    members: MemberRepository,
    notifications: NotificationPort | None,
    org_id: UUID,
    org_name: str,
    post_id: UUID,
    actor_id: UUID,
    title: str,
) -> None:
    """In-app notify every active member except the author."""
    if notifications is None:
        return
    try:
        rows = members.list_by_org(org_id)
    except Exception:  # noqa: BLE001 - fanout is best-effort
        return
    data = json.dumps(
        {"org_id": str(org_id), "post_id": str(post_id),
         "kind": "announcement"}
    )
    for row in rows:
        if (row.status or "active") != "active" or row.user_id == actor_id:
            continue
        try:
            notifications.notify(
                row.user_id,
                "announcement",
                f"Th\u00f4ng b\u00e1o m\u1edbi t\u1eeb {org_name}",
                title,
                data_json=data,
            )
        except Exception:  # noqa: BLE001 - notifications are best-effort
            pass
