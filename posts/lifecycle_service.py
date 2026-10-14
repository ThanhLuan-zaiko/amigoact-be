"""Article lifecycle: drafts, publish/unpublish, trash, restore, purge.

Mirrors the org CRUD contract: DELETE moves a post to the trash (soft,
restorable, comments kept), restore puts it back where it was (feed or
drafts), hard delete erases the row, comments, media links and the
post's own attachment uploads. Authors manage their posts; owners and
post:manage holders manage every post in the org trash.

Parallel drafts: a published post keeps a private revision draft
(revision_of = post_id) so edits never go live mid-typing; publishing
the revision folds it back onto the live post instead of adding a
second board entry.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from core.exceptions import InvalidPostStateError, NotFoundError
from core.ids import uuid7
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
from posts.model import OrgPost
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

    def _revisions_of(self, post: OrgPost, *, trashed: bool = False) -> list[OrgPost]:
        """Revision drafts staged on this post (live or trashed rows).

        A revision belongs to the post's author, so the author's draft
        ids or the org trash projection locate them without a new table.
        """
        if trashed:
            rows = self._posts.list_trash(post.org_id, SCAN_LIMIT)
            candidates = (
                self._posts.get(row.post_id)
                for row in rows
                if row.author_id == post.author_id
                and (row.status or "active") == "draft"
            )
        else:
            ids = self._posts.list_drafts(
                post.org_id, post.author_id, WINDOW_LIMIT
            )
            candidates = (self._posts.get(post_id) for post_id in ids)
        return [
            row
            for row in candidates
            if row is not None
            and getattr(row, "revision_of", None) == post.post_id
        ]

    def get_or_create_revision(
        self, org_id: UUID, post_id: UUID, actor_id: UUID
    ) -> PostSnapshot:
        """Open the author's private revision of a live post (idempotent).

        The revision is a normal draft row copying the post's content;
        it shows on the author's draft shelf until publish folds it back.
        """
        self._guard.require_member(org_id, actor_id, "post.revise")
        row = visible_post_or_404(self._posts, org_id, post_id, actor_id)
        self._guard.require_author(
            org_id, row.author_id, actor_id, "post.revise", post_id
        )
        if is_draft(row) or getattr(row, "revision_of", None) is not None:
            raise InvalidPostStateError(
                "Only a published post can have a revision draft."
            )
        for rev in self._revisions_of(row):
            return self._snapshots.build(rev)
        revision_id = uuid7()
        self._posts.create(
            revision_id,
            org_id,
            actor_id,
            row.kind or "discussion",
            row.title or "",
            row.body or "",
            [link.asset_id for link in self._posts.list_media(post_id)],
            utcnow(),
            status="draft",
            blocks_json=getattr(row, "blocks_json", "") or "",
            cover_media_id=getattr(row, "cover_media_id", None),
            revision_of=post_id,
        )
        self._guard.record(org_id, actor_id, "post.revise", post_id)
        return self._snapshots.fresh(revision_id)

    def publish(
        self, org_id: UUID, post_id: UUID, actor_id: UUID
    ) -> PostSnapshot:
        """Author moves a draft onto the board (and notifies if announce).

        A draft carrying revision_of folds back into its live post via
        _publish_revision - the board entry keeps its id, comments and
        pin instead of becoming a second copy.
        """
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
        if getattr(row, "revision_of", None) is not None:
            return self._publish_revision(org, row, actor_id)
        self._posts.set_status(row, "active", utcnow())
        self._guard.record(org_id, actor_id, "post.publish", post_id)
        self._emit(org_id, "post.created", post_id, actor_id, detail=kind)
        self._emit_public(org_id, "created", post_id, kind)
        if kind == "announcement":
            notify_announcement(
                self._members, self._notifications, org_id, org.name,
                post_id, actor_id, row.title or "",
            )
        return self._snapshots.fresh(post_id)

    def _publish_revision(
        self, org: Any, rev: OrgPost, actor_id: UUID
    ) -> PostSnapshot:
        """Fold a revision draft into its live post, then drop the draft."""
        parent = self._posts.get(rev.revision_of)
        if (
            parent is None
            or parent.org_id != rev.org_id
            or is_draft(parent)
            or is_trashed(parent)
        ):
            raise InvalidPostStateError("The original post is unavailable.")
        self._posts.update_content(
            parent,
            parent.kind or "discussion",
            rev.title or "",
            rev.body or "",
            getattr(rev, "blocks_json", "") or "",
            getattr(rev, "cover_media_id", None),
            utcnow(),
        )
        self._posts.replace_media(
            parent.post_id,
            [link.asset_id for link in self._posts.list_media(rev.post_id)],
        )
        self._posts.delete(rev)
        self._guard.record(rev.org_id, actor_id, "post.publish", parent.post_id)
        self._emit(rev.org_id, "post.updated", parent.post_id, actor_id)
        self._emit_public(rev.org_id, "updated", parent.post_id, parent.kind)
        return self._snapshots.fresh(parent.post_id)

    def unpublish(
        self, org_id: UUID, post_id: UUID, actor_id: UUID
    ) -> PostSnapshot:
        """Author pulls a published post back into their drafts.

        Open revisions fold in first so the post comes down carrying the
        newest edits and no duplicate draft rows remain.
        """
        self._guard.require_member(org_id, actor_id, "post.unpublish")
        row = visible_post_or_404(self._posts, org_id, post_id, actor_id)
        self._guard.require_author(
            org_id, row.author_id, actor_id, "post.unpublish", post_id
        )
        if is_draft(row):
            raise InvalidPostStateError("Post is already a draft.")
        now = utcnow()
        revisions = self._revisions_of(row)
        if revisions:
            newest = revisions[0]
            self._posts.update_content(
                row,
                row.kind or "discussion",
                newest.title or "",
                newest.body or "",
                getattr(newest, "blocks_json", "") or "",
                getattr(newest, "cover_media_id", None),
                now,
            )
            self._posts.replace_media(
                row.post_id,
                [l.asset_id for l in self._posts.list_media(newest.post_id)],
            )
            for rev in revisions:
                self._posts.delete(rev)
        self._posts.set_status(row, "draft", now)
        self._guard.record(org_id, actor_id, "post.unpublish", post_id)
        self._emit(org_id, "post.unpublished", post_id, actor_id)
        self._emit_public(org_id, "removed", post_id, row.kind)
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
        now = utcnow()
        self._posts.soft_delete(row, now)
        if getattr(row, "revision_of", None) is None:
            for rev in self._revisions_of(row):
                self._posts.soft_delete(rev, now)
        self._guard.record(org_id, actor_id, "post.delete", post_id)
        if not was_draft:
            self._emit(org_id, "post.deleted", post_id, actor_id)
            self._emit_public(org_id, "removed", post_id, row.kind)

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
            self._emit_public(org_id, "created", post_id, row.kind)
        return self._snapshots.fresh(post_id)

    def hard_delete(self, org_id: UUID, post_id: UUID, actor_id: UUID) -> None:
        """Erase the post everywhere, from the trash or straight from live.

        Deleting a post also erases every revision staged on it. Deleting
        a lone revision keeps attachment assets its live post still uses.
        """
        org = self._guard.require_member(org_id, actor_id, "post.purge")
        row = self._own_or_public(org_id, post_id, actor_id)
        self._guard.require_author_or_manage(
            org_id, org.owner_id, row.author_id, actor_id, "post.purge",
            post_id,
        )
        was_public = not is_draft(row) and not is_trashed(row)
        asset_ids = [link.asset_id for link in self._posts.list_media(post_id)]
        if getattr(row, "revision_of", None) is not None:
            parent = self._posts.get(row.revision_of)
            if parent is not None and parent.org_id == org_id:
                shared = {
                    link.asset_id
                    for link in self._posts.list_media(parent.post_id)
                }
                asset_ids = [a for a in asset_ids if a not in shared]
        else:
            for rev in self._revisions_of(row) + self._revisions_of(
                row, trashed=True
            ):
                asset_ids.extend(
                    link.asset_id
                    for link in self._posts.list_media(rev.post_id)
                )
                self._comments.remove_all(rev.post_id)
                self._posts.delete(rev)
        self._comments.remove_all(post_id)
        self._posts.delete(row)
        self._media_rules.purge_attachments(org_id, asset_ids)
        self._guard.record(org_id, actor_id, "post.purge", post_id)
        if was_public:
            self._emit(org_id, "post.deleted", post_id, actor_id)
            self._emit_public(org_id, "removed", post_id, row.kind)
        else:
            self._emit(org_id, "post.purged", post_id, actor_id)
