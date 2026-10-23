"""Org board business rules: feed reads, writes and pins. No FastAPI here.

Publish/unpublish and the trash lifecycle (soft delete, restore, hard
delete) live in posts/lifecycle_service.py.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from core.exceptions import InvalidPostStateError
from core.ids import uuid7
from core.security import utcnow
from core.tags import tag_slug
from posts.tag_rules import take_post_tags
from posts.blocks import blocks_to_text, compact_blocks, dump_blocks
from posts.dtos import PostPage, PostSnapshot
from posts.helpers import (
    is_draft,
    is_trashed,
    notify_announcement,
    post_or_404,
    post_visibility,
    visible_post_or_404,
)
from posts.service_base import (
    SCAN_LIMIT,
    WINDOW_LIMIT,
    BoardServiceBase,
    check_publishable,
)

KINDS: tuple[str, ...] = ("announcement", "discussion")


def _published(row: Any) -> bool:
    return (row.status or "active") == "active" and not is_trashed(row)


class PostService(BoardServiceBase):
    """Board rules: member posting, manager announce/pin/moderate."""

    # ---- board reads ------------------------------------------------------

    def list_posts(
        self,
        org_id: UUID,
        viewer_id: UUID,
        *,
        limit: int = 20,
        page: int = 1,
        kind: str | None = None,
        tag: str | None = None,
    ) -> PostPage:
        """Numbered newest-first page. A tag reads the post edge index."""
        org = self._guard.require_member(org_id, viewer_id, "post.list")
        slug = tag_slug(tag) if tag and tag.strip() else ""
        filtering = bool(tag and tag.strip())
        if filtering:
            ids = self._tagged_ids(org_id, slug, kind) if slug else []
            total = len(ids)
        elif kind is None:
            rows = self._posts.list_feed(
                org_id, min(page * limit, WINDOW_LIMIT)
            )
            ids = [row.post_id for row in rows]
            total = self._posts.count_feed(org_id)
        else:
            scanned = self._posts.list_feed(org_id, SCAN_LIMIT)
            ids = [
                row.post_id
                for row in scanned
                if (row.kind or "discussion") == kind
            ]
            total = len(ids)
        allowed = set(ids) if filtering else None
        items = self._window(
            ids, page, limit,
            lambda row: _published(row)
            and (kind is None or (row.kind or "discussion") == kind),
        )
        pinned: list[PostSnapshot] = []
        if page == 1:
            for post_id in self._posts.list_pinned(org_id):
                if allowed is not None and post_id not in allowed:
                    continue
                row = self._posts.get(post_id)
                if row is not None and _published(row):
                    pinned.append(self._snapshots.build(row))
        role, permissions = self._guard.viewer(org_id, org.owner_id, viewer_id)
        return PostPage(
            items=items,
            pinned=pinned,
            total=total,
            viewer_role=role,
            viewer_permissions=permissions,
        )

    def _tagged_ids(
        self, org_id: UUID, slug: str, kind: str | None
    ) -> list[UUID]:
        """Published posts edged to the slug, optionally one kind."""
        if self._post_tags is None or not slug:
            return []
        ids: list[UUID] = []
        for post_id in self._post_tags.list_ids(org_id, slug):
            row = self._posts.get(post_id)
            if row is None or not _published(row):
                continue
            if kind is not None and (row.kind or "discussion") != kind:
                continue
            ids.append(row.post_id)
        return ids

    def _canonical_tags(
        self, org_id: UUID, user_id: UUID, names: list[str] | None
    ) -> list[str] | None:
        """Claim names before the post write. None means tags stay put."""
        if names is None:
            return None
        sliced = take_post_tags(names)
        if self._user_tags is not None:
            sliced = self._user_tags.ensure(user_id, sliced)
        if self._tag_claims is None:
            return sliced if self._user_tags is not None else None
        return self._tag_claims.ensure(org_id, sliced)

    def _write_tags(
        self,
        org_id: UUID,
        post_id: UUID,
        user_id: UUID,
        names: list[str] | None,
        now: datetime,
    ) -> None:
        if names is None:
            return
        if self._post_tags is not None:
            self._post_tags.replace(org_id, post_id, names, now)
        self._bind_user_tags(user_id, org_id, post_id, names)

    def get_post(
        self, org_id: UUID, post_id: UUID, viewer_id: UUID
    ) -> PostSnapshot:
        """Published post, or the viewer's own draft."""
        self._guard.require_member(org_id, viewer_id, "post.read")
        return self._snapshots.build(
            visible_post_or_404(self._posts, org_id, post_id, viewer_id)
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
        *,
        blocks: list[Any] | None = None,
        cover_media_id: UUID | None = None,
        status: str = "published",
        visibility: str | None = None,
        tags: list[str] | None = None,
    ) -> PostSnapshot:
        """Members post discussions; announcements need post:announce.

        `visibility` is the audience axis orthogonal to kind: "public"
        reaches the guest surfaces, "members" stays on the board. Both
        announcement kind and public audience need post:announce, so a
        plain member can only ever write member-scoped discussions.
        Drafts land only in the author's draft list: no feed row, no
        realtime fan-out and no announcement notifications until publish.
        """
        org = self._guard.require_member(org_id, actor_id, "post.create")
        audience = visibility or (
            "public" if kind == "announcement" else "members"
        )
        if kind == "announcement" or audience == "public":
            self._guard.require_announce(
                org_id, org.owner_id, actor_id, "post.create"
            )
        article = compact_blocks(blocks or [])
        media = self._media_rules.attachments(org_id, media_ids)
        for asset_id in self._media_rules.article(
            org_id, article, cover_media_id
        ):
            if asset_id not in media:
                media.append(asset_id)
        text = blocks_to_text(article) if article else body
        draft = status == "draft"
        if not draft:
            check_publishable(kind, title, text, article)
        canonical = self._canonical_tags(org_id, actor_id, tags)
        now = utcnow()
        post_id = uuid7()
        created = self._posts.create(
            post_id, org_id, actor_id, kind, title, text, media, now,
            status="draft" if draft else "active",
            blocks_json=dump_blocks(article),
            cover_media_id=cover_media_id,
            visibility=audience,
        )
        self._write_tags(org_id, post_id, actor_id, canonical, now)
        self._guard.record(org_id, actor_id, "post.create", post_id)
        if not draft:
            self._emit(org_id, "post.created", post_id, actor_id, detail=kind)
            self._emit_public(org_id, "created", created)
            if kind == "announcement":
                notify_announcement(
                    self._members, self._notifications, org_id, org.name,
                    post_id, actor_id, title,
                )
        return self._snapshots.fresh(post_id)

    def update_post(
        self,
        org_id: UUID,
        post_id: UUID,
        actor_id: UUID,
        title: str,
        body: str,
        *,
        blocks: list[Any] | None = None,
        cover_media_id: UUID | None = None,
        touch_cover: bool = False,
        kind: str | None = None,
        visibility: str | None = None,
        tags: list[str] | None = None,
        touch_tags: bool = False,
    ) -> PostSnapshot:
        """Only the author edits (drafts too); managers moderate by delete.

        blocks=None keeps the legacy title/body edit. The kind may only
        change while the post is still a draft.
        """
        org = self._guard.require_member(org_id, actor_id, "post.update")
        row = visible_post_or_404(self._posts, org_id, post_id, actor_id)
        self._guard.require_author(
            org_id, row.author_id, actor_id, "post.update", post_id
        )
        current_kind = row.kind or "discussion"
        next_kind = kind or current_kind
        if next_kind != current_kind:
            if not is_draft(row) or getattr(row, "revision_of", None):
                raise InvalidPostStateError(
                    "Kind can only change on a standalone draft."
                )
            if next_kind == "announcement":
                self._guard.require_announce(
                    org_id, org.owner_id, actor_id, "post.update", post_id
                )
        was_public = post_visibility(row) == "public"
        current_visibility = "public" if was_public else "members"
        next_visibility = visibility or current_visibility
        visibility_changed = next_visibility != current_visibility
        if visibility_changed:
            if getattr(row, "revision_of", None) is not None:
                raise InvalidPostStateError(
                    "Audience follows the live post and cannot change here."
                )
            if next_visibility == "public":
                self._guard.require_announce(
                    org_id, org.owner_id, actor_id, "post.update", post_id
                )
        canonical = (
            self._canonical_tags(org_id, actor_id, tags or [])
            if touch_tags
            else None
        )
        now = utcnow()
        if blocks is None:
            if not is_draft(row):
                check_publishable(next_kind, title, body, [])
            self._posts.update_body(row, title, body, now)
        else:
            article = compact_blocks(blocks)
            cover = cover_media_id if touch_cover else row.cover_media_id
            media = self._media_rules.article(org_id, article, cover)
            text = blocks_to_text(article)
            if not is_draft(row):
                check_publishable(next_kind, title, text, article)
            self._posts.update_content(
                row, next_kind, title, text, dump_blocks(article), cover, now
            )
            self._posts.replace_media(post_id, media)
        if visibility_changed:
            self._posts.set_visibility(row, next_visibility, now)
        if touch_tags:
            self._write_tags(org_id, post_id, actor_id, canonical, now)
        self._guard.record(org_id, actor_id, "post.update", post_id)
        if not is_draft(row):
            self._emit(org_id, "post.updated", post_id, actor_id)
            is_public = next_visibility == "public"
            if was_public or is_public:
                action = "updated"
                if was_public != is_public:
                    action = "created" if is_public else "removed"
                self._emit_public(org_id, action, row, force=True)
        return self._snapshots.fresh(post_id)

    def set_pinned(
        self, org_id: UUID, post_id: UUID, actor_id: UUID, pinned: bool
    ) -> PostSnapshot:
        org = self._guard.require_member(org_id, actor_id, "post.pin")
        row = post_or_404(self._posts, org_id, post_id)
        self._guard.require_manage(
            org_id, org.owner_id, actor_id, "post.pin", post_id
        )
        now = utcnow()
        self._posts.set_pinned(row, now if pinned else None, now)
        self._guard.record(org_id, actor_id, "post.pin", post_id)
        self._emit(
            org_id, "post.pinned" if pinned else "post.unpinned",
            post_id, actor_id,
        )
        return self._snapshots.fresh(post_id)
