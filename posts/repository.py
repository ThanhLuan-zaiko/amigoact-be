"""cqlengine persistence for posts, feeds, pins, media links, comments."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from cassandra.cqlengine.connection import get_session

from posts.interfaces import CommentStore, PostStore
from posts.model import (
    OrgPost,
    OrgPostComment,
    OrgPostFeed,
    OrgPostMedia,
    OrgPostPinned,
)


class CqlPostStore(PostStore):
    """Post canonical row plus feed/pin/media projections."""

    def __init__(self, keyspace: str) -> None:
        self._keyspace = keyspace

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
    ) -> OrgPost:
        row = OrgPost.create(
            post_id=post_id,
            org_id=org_id,
            author_id=author_id,
            kind=kind,
            title=title,
            body=body,
            status="active",
            created_at=now,
            updated_at=now,
        )
        OrgPostFeed.create(org_id=org_id, post_id=post_id)
        for position, asset_id in enumerate(media_ids):
            OrgPostMedia.create(
                post_id=post_id, position=position, asset_id=asset_id
            )
        return row

    def get(self, post_id: UUID) -> OrgPost | None:
        return OrgPost.objects(post_id=post_id).first()

    def list_feed(
        self, org_id: UUID, cursor: UUID | None, limit: int
    ) -> list[UUID]:
        query = OrgPostFeed.objects(org_id=org_id)
        if cursor is not None:
            query = query.filter(post_id__lt=cursor)
        return [row.post_id for row in query.limit(limit)]

    def list_pinned(self, org_id: UUID, limit: int = 5) -> list[UUID]:
        rows = OrgPostPinned.objects(org_id=org_id).limit(limit)
        return [row.post_id for row in rows]

    def update_body(
        self, post: OrgPost, title: str, body: str, now: datetime
    ) -> None:
        OrgPost.objects(post_id=post.post_id).update(
            title=title, body=body, edited_at=now, updated_at=now
        )

    def set_pinned(
        self, post: OrgPost, pinned_at: datetime | None, now: datetime
    ) -> None:
        OrgPost.objects(post_id=post.post_id).update(
            pinned_at=pinned_at, updated_at=now
        )
        if pinned_at is None:
            OrgPostPinned.objects(
                org_id=post.org_id, post_id=post.post_id
            ).delete()
        else:
            OrgPostPinned.create(org_id=post.org_id, post_id=post.post_id)

    def delete(self, post: OrgPost) -> None:
        OrgPostFeed.objects(
            org_id=post.org_id, post_id=post.post_id
        ).delete()
        if post.pinned_at is not None:
            OrgPostPinned.objects(
                org_id=post.org_id, post_id=post.post_id
            ).delete()
        OrgPostMedia.objects(post_id=post.post_id).delete()
        OrgPost.objects(post_id=post.post_id).delete()

    def list_media(self, post_id: UUID) -> list[OrgPostMedia]:
        return list(OrgPostMedia.objects(post_id=post_id).all())


class CqlCommentStore(CommentStore):
    """Comment partition plus the raw-CQL counter (counter column, so no
    typed cqlengine increment - same pattern as CqlRateLimiter)."""

    def __init__(self, keyspace: str) -> None:
        self._keyspace = keyspace

    def _bump(self, post_id: UUID, delta: int) -> None:
        get_session().execute(
            f"UPDATE {self._keyspace}.org_post_comment_counts"
            " SET comments = comments + %s WHERE post_id = %s",
            [delta, post_id],
        )

    def add(
        self, post_id: UUID, comment_id: UUID, author_id: UUID, body: str,
        now: datetime,
    ) -> OrgPostComment:
        row = OrgPostComment.create(
            post_id=post_id,
            comment_id=comment_id,
            author_id=author_id,
            body=body,
            created_at=now,
        )
        self._bump(post_id, 1)
        return row

    def get(self, post_id: UUID, comment_id: UUID) -> OrgPostComment | None:
        return OrgPostComment.objects(
            post_id=post_id, comment_id=comment_id
        ).first()

    def list_page(
        self, post_id: UUID, cursor: UUID | None, limit: int
    ) -> list[OrgPostComment]:
        query = OrgPostComment.objects(post_id=post_id)
        if cursor is not None:
            query = query.filter(comment_id__gt=cursor)
        return list(query.limit(limit))

    def remove(self, comment: OrgPostComment) -> None:
        OrgPostComment.objects(
            post_id=comment.post_id, comment_id=comment.comment_id
        ).delete()
        self._bump(comment.post_id, -1)

    def remove_all(self, post_id: UUID) -> None:
        OrgPostComment.objects(post_id=post_id).delete()
        get_session().execute(
            f"DELETE FROM {self._keyspace}.org_post_comment_counts"
            " WHERE post_id = %s",
            [post_id],
        )

    def count(self, post_id: UUID) -> int:
        row = get_session().execute(
            f"SELECT comments FROM {self._keyspace}.org_post_comment_counts"
            " WHERE post_id = %s",
            [post_id],
        ).one()
        return int(row["comments"]) if row is not None else 0
