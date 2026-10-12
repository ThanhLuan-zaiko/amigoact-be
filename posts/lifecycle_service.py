"""Article lifecycle: drafts, publish/unpublish, trash, restore, purge.

Mirrors the org CRUD contract: DELETE moves a post to the trash (soft,
restorable, comments kept), restore puts it back where it was (feed or
drafts), hard delete erases the row, comments, media links and the
post's own attachment uploads. Authors manage their posts; owners and
post:manage holders manage every post in the org trash.
"""

from __future__ import annotations

from uuid import UUID

from core.exceptions import InvalidPostStateError, NotFoundError
from core.security import utcnow
from posts.blocks import load_blocks
from posts.dtos import PostPage, PostSnapshot
from posts.helpers import (
    any_post_or_404,
    is_draft,
    is_trashed,
    notify_announcement,
    visible_post_or_404,
)
from posts.service_base import (
    SCAN_LIMIT,
    WINDOW_LIMIT,
    BoardServiceBase,
    check_publishable,
)


class PostLifecycleService(BoardServiceBase):
    """Drafts list, publish state moves and the trash bin."""

    # ---- lists -----------------------------------------------------------

    def list_drafts(
        self, org_id: UUID, viewer_id: UUID, *, limit: int = 20,
        page: int = 1,
    ) -> PostPage:
        """The caller's own unpublished drafts, numbered newest first."""
        org = self._guard.require_member(org_id, viewer_id, "post.drafts")
        ids = self._posts.list_drafts(
            org_id, viewer_id, min(page * limit, WINDOW_LIMIT)
        )
        items = self._window(
            ids, page, limit,
            lambda row: is_draft(row) and not is_trashed(row)
            and row.author_id == viewer_id,
        )
        role, permissions = self._guard.viewer(org_id, org.owner_id, viewer_id)
        return PostPage(
            items, [], self._posts.count_drafts(org_id, viewer_id),
            role, permissions,
        )

    def list_trash(
        self, org_id: UUID, viewer_id: UUID, *, limit: int = 20,
        page: int = 1,
    ) -> PostPage:
        """Managers see the whole org trash; authors only their own.

        Visibility comes off the denormalized trash row (author_id +
        status), so the page total never loads trashed canonical rows.
        """
        org = self._guard.require_member(org_id, viewer_id, "post.trash")
        manager = self._guard.can_manage(org_id, org.owner_id, viewer_id)
        rows = self._posts.list_trash(org_id, SCAN_LIMIT)
        ids = [
            row.post_id
            for row in rows
            if row.author_id == viewer_id
            or (manager and (row.status or "active") != "draft")
        ]
        items = self._window(ids, page, limit, lambda row: is_trashed(row))
        role, permissions = self._guard.viewer(org_id, org.owner_id, viewer_id)
        return PostPage(items, [], len(ids), role, permissions)

    # ---- publish state ---------------------------------------------------

    def publish(
        self, org_id: UUID, post_id: UUID, actor_id: UUID
    ) -> PostSnapshot:
        """Author moves a draft onto the board (and notifies if announce)."""
        org = self._guard.require_member(org_id, actor_id, "post.publish")
        row = visible_post_or_404(self._posts, org_id, post_id, actor_id)
        self._guard.require_author(
            org_id, row.author_id, actor_id, "post.publish", post_id
        )
        if not is_draft(row):
            raise InvalidPostStateError("Post is already published.")
        kind = row.kind or "discussion"
        if kind == "announcement":
            self._guard.require_announce(
                org_id, org.owner_id, actor_id, "post.publish", post_id
            )
        check_publishable(
            kind, row.title or "", row.body or "",
            load_blocks(getattr(row, "blocks_json", None)),
        )
        self._posts.set_status(row, "active", utcnow())
        self._guard.record(org_id, actor_id, "post.publish", post_id)
        self._emit(org_id, "post.created", post_id, actor_id, detail=kind)
        if kind == "announcement":
            notify_announcement(
                self._members, self._notifications, org_id, org.name,
                post_id, actor_id, row.title or "",
            )
        return self._snapshots.fresh(post_id)

    def unpublish(
        self, org_id: UUID, post_id: UUID, actor_id: UUID
    ) -> PostSnapshot:
        """Author pulls a published post back into their drafts."""
        self._guard.require_member(org_id, actor_id, "post.unpublish")
        row = visible_post_or_404(self._posts, org_id, post_id, actor_id)
        self._guard.require_author(
            org_id, row.author_id, actor_id, "post.unpublish", post_id
        )
        if is_draft(row):
            raise InvalidPostStateError("Post is already a draft.")
        self._posts.set_status(row, "draft", utcnow())
        self._guard.record(org_id, actor_id, "post.unpublish", post_id)
        self._emit(org_id, "post.unpublished", post_id, actor_id)
        return self._snapshots.fresh(post_id)

    # ---- trash -----------------------------------------------------------

    def _own_or_public(self, org_id: UUID, post_id: UUID, actor_id: UUID):  # noqa: ANN202
        """Any state, but other authors' drafts (live or trashed) read 404."""
        row = any_post_or_404(self._posts, org_id, post_id)
        if is_draft(row) and row.author_id != actor_id:
            raise NotFoundError("Post not found.")
        return row

    def soft_delete(self, org_id: UUID, post_id: UUID, actor_id: UUID) -> None:
        """Author or manager moves a live post or draft to the trash."""
        org = self._guard.require_member(org_id, actor_id, "post.delete")
        row = visible_post_or_404(self._posts, org_id, post_id, actor_id)
        self._guard.require_author_or_manage(
            org_id, org.owner_id, row.author_id, actor_id, "post.delete",
            post_id,
        )
        was_draft = is_draft(row)
        self._posts.soft_delete(row, utcnow())
        self._guard.record(org_id, actor_id, "post.delete", post_id)
        if not was_draft:
            self._emit(org_id, "post.deleted", post_id, actor_id)

    def restore(
        self, org_id: UUID, post_id: UUID, actor_id: UUID
    ) -> PostSnapshot:
        """Return a trashed post to its feed (published) or drafts."""
        org = self._guard.require_member(org_id, actor_id, "post.restore")
        row = self._own_or_public(org_id, post_id, actor_id)
        self._guard.require_author_or_manage(
            org_id, org.owner_id, row.author_id, actor_id, "post.restore",
            post_id,
        )
        if not is_trashed(row):
            raise InvalidPostStateError("Post is not in the trash.")
        self._posts.restore(row, utcnow())
        self._guard.record(org_id, actor_id, "post.restore", post_id)
        if not is_draft(row):
            self._emit(org_id, "post.restored", post_id, actor_id)
        return self._snapshots.fresh(post_id)

    def hard_delete(self, org_id: UUID, post_id: UUID, actor_id: UUID) -> None:
        """Erase the post everywhere, from the trash or straight from live."""
        org = self._guard.require_member(org_id, actor_id, "post.purge")
        row = self._own_or_public(org_id, post_id, actor_id)
        self._guard.require_author_or_manage(
            org_id, org.owner_id, row.author_id, actor_id, "post.purge",
            post_id,
        )
        was_public = not is_draft(row) and not is_trashed(row)
        asset_ids = [link.asset_id for link in self._posts.list_media(post_id)]
        self._comments.remove_all(post_id)
        self._posts.delete(row)
        self._media_rules.purge_attachments(org_id, asset_ids)
        self._guard.record(org_id, actor_id, "post.purge", post_id)
        if was_public:
            self._emit(org_id, "post.deleted", post_id, actor_id)
        else:
            self._emit(org_id, "post.purged", post_id, actor_id)
