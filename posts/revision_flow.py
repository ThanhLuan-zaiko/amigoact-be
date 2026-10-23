"""Fold a revision draft onto its live post, tags included."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from core.exceptions import InvalidPostStateError
from posts.helpers import is_draft, is_trashed
from posts.interfaces import PostStore
from posts.model import OrgPost
from posts.tag_index import PostTagIndex


def copy_tags(
    post_tags: PostTagIndex | None,
    org_id: UUID,
    names: list[str] | None,
    target_id: UUID,
    now: datetime,
) -> None:
    """Write canonical names onto a post. No-op without an index."""
    if post_tags is None:
        return
    post_tags.replace(org_id, target_id, list(names or []), now)


def forget_tags(
    post_tags: PostTagIndex | None, org_id: UUID, post_id: UUID
) -> None:
    """Drop one post's edges. No-op without an index."""
    if post_tags is None:
        return
    post_tags.forget(org_id, post_id)


def fold_revision(
    posts: PostStore,
    post_tags: PostTagIndex | None,
    rev: OrgPost,
    now: datetime,
) -> OrgPost:
    """Copy the revision onto its live parent, then delete the draft."""
    parent = posts.get(rev.revision_of)
    if (
        parent is None
        or parent.org_id != rev.org_id
        or is_draft(parent)
        or is_trashed(parent)
    ):
        raise InvalidPostStateError("The original post is unavailable.")
    posts.update_content(
        parent,
        parent.kind or "discussion",
        rev.title or "",
        rev.body or "",
        getattr(rev, "blocks_json", "") or "",
        getattr(rev, "cover_media_id", None),
        now,
    )
    posts.replace_media(
        parent.post_id,
        [link.asset_id for link in posts.list_media(rev.post_id)],
    )
    copy_tags(
        post_tags,
        parent.org_id,
        getattr(rev, "tag_names", None),
        parent.post_id,
        now,
    )
    forget_tags(post_tags, rev.org_id, rev.post_id)
    posts.delete(rev)
    return parent
