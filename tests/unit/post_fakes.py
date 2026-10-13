"""In-memory PostStore for post service unit tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID

from posts.interfaces import PostStore


def _add_sorted(rows: list[UUID], post_id: UUID) -> None:
    if post_id not in rows:
        rows.append(post_id)
        rows.sort(reverse=True)


def _drop(rows: list[UUID] | None, post_id: UUID) -> None:
    if rows is not None and post_id in rows:
        rows.remove(post_id)


class FakePostStore(PostStore):
    """Canonical rows plus sorted feed/draft/pin/trash/media projections."""

    def __init__(self) -> None:
        self.posts: dict[UUID, Any] = {}
        self.feed: dict[UUID, list[UUID]] = {}
        self.pinned: dict[UUID, list[UUID]] = {}
        self.drafts: dict[tuple[UUID, UUID], list[UUID]] = {}
        self.trash: dict[UUID, list[UUID]] = {}
        self.media: dict[UUID, list[Any]] = {}

    def create(self, post_id, org_id, author_id, kind, title, body, media_ids, now, status="active", blocks_json="", cover_media_id=None, revision_of=None):  # noqa: ANN001, ANN202, E501
        row = SimpleNamespace(
            post_id=post_id, org_id=org_id, author_id=author_id,
            kind=kind, title=title, body=body, status=status,
            blocks_json=blocks_json, cover_media_id=cover_media_id,
            revision_of=revision_of,
            pinned_at=None, edited_at=None, deleted_at=None,
            published_at=now if status == "active" else None,
            created_at=now, updated_at=now,
        )
        self.posts[post_id] = row
        self._place(row)
        self.replace_media(post_id, media_ids)
        return row

    def _place(self, post):  # noqa: ANN001, ANN202
        if post.status == "draft":
            key = (post.org_id, post.author_id)
            _add_sorted(self.drafts.setdefault(key, []), post.post_id)
        else:
            _add_sorted(self.feed.setdefault(post.org_id, []), post.post_id)

    def _unplace(self, post):  # noqa: ANN001, ANN202
        _drop(self.feed.get(post.org_id), post.post_id)
        _drop(self.pinned.get(post.org_id), post.post_id)
        _drop(self.drafts.get((post.org_id, post.author_id)), post.post_id)

    def get(self, post_id):  # noqa: ANN001, ANN202
        return self.posts.get(post_id)

    def list_feed(self, org_id, limit):  # noqa: ANN001, ANN202
        rows = self.feed.get(org_id, [])
        return [
            SimpleNamespace(post_id=p, kind=self.posts[p].kind)
            for p in rows[:limit]
            if p in self.posts
        ]

    def count_feed(self, org_id):  # noqa: ANN001, ANN202
        return len(self.feed.get(org_id, []))

    def list_pinned(self, org_id, limit=5):  # noqa: ANN001, ANN202
        return self.pinned.get(org_id, [])[:limit]

    def list_drafts(self, org_id, author_id, limit):  # noqa: ANN001, ANN202
        return self.drafts.get((org_id, author_id), [])[:limit]

    def count_drafts(self, org_id, author_id):  # noqa: ANN001, ANN202
        return len(self.drafts.get((org_id, author_id), []))

    def list_trash(self, org_id, limit):  # noqa: ANN001, ANN202
        rows = self.trash.get(org_id, [])
        return [
            SimpleNamespace(
                org_id=org_id, post_id=p,
                author_id=self.posts[p].author_id,
                status=self.posts[p].status,
            )
            for p in rows[:limit]
            if p in self.posts
        ]

    def update_body(self, post, title, body, now):  # noqa: ANN001, ANN202
        post.title = title
        post.body = body
        post.edited_at = now
        post.updated_at = now

    def update_content(self, post, kind, title, body, blocks_json, cover_media_id, now):  # noqa: ANN001, ANN202, E501
        post.kind = kind
        post.title = title
        post.body = body
        post.blocks_json = blocks_json
        post.cover_media_id = cover_media_id
        post.edited_at = now
        post.updated_at = now

    def replace_media(self, post_id, media_ids):  # noqa: ANN001, ANN202
        self.media[post_id] = [
            SimpleNamespace(post_id=post_id, position=i, asset_id=a)
            for i, a in enumerate(media_ids)
        ]

    def set_pinned(self, post, pinned_at, now):  # noqa: ANN001, ANN202
        post.pinned_at = pinned_at
        post.updated_at = now
        rows = self.pinned.setdefault(post.org_id, [])
        if pinned_at is None:
            _drop(rows, post.post_id)
        else:
            _add_sorted(rows, post.post_id)

    def set_status(self, post, status, now):  # noqa: ANN001, ANN202
        self._unplace(post)
        post.status = status
        post.pinned_at = None
        post.updated_at = now
        if status == "active" and post.published_at is None:
            post.published_at = now
        self._place(post)

    def soft_delete(self, post, now):  # noqa: ANN001, ANN202
        self._unplace(post)
        post.deleted_at = now
        post.pinned_at = None
        _add_sorted(self.trash.setdefault(post.org_id, []), post.post_id)

    def restore(self, post, now):  # noqa: ANN001, ANN202
        _drop(self.trash.get(post.org_id), post.post_id)
        post.deleted_at = None
        post.updated_at = now
        self._place(post)

    def delete(self, post):  # noqa: ANN001, ANN202
        self._unplace(post)
        _drop(self.trash.get(post.org_id), post.post_id)
        self.posts.pop(post.post_id, None)
        self.media.pop(post.post_id, None)

    def list_media(self, post_id):  # noqa: ANN001, ANN202
        return list(self.media.get(post_id, []))
