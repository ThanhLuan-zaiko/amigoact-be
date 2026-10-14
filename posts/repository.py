"""cqlengine persistence for posts, feeds, pins, media links, comments."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from cassandra.cqlengine.connection import get_session

from posts.interfaces import CommentStore, PostStore
from posts.model import (
    AnnouncementFeed,
    OrgPost,
    OrgPostComment,
    OrgPostDraft,
    OrgPostFeed,
    OrgPostMedia,
    OrgPostPinned,
    OrgPostTrash,
)

TIMELINE_BUCKET = "all"


class CqlPostStore(PostStore):
    """Post canonical row plus feed/draft/pin/trash/media projections."""

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
        status: str = "active",
        blocks_json: str = "",
        cover_media_id: UUID | None = None,
        revision_of: UUID | None = None,
    ) -> OrgPost:
        row = OrgPost.create(
            post_id=post_id,
            org_id=org_id,
            author_id=author_id,
            kind=kind,
            title=title,
            body=body,
            blocks_json=blocks_json,
            cover_media_id=cover_media_id,
            status=status,
            revision_of=revision_of,
            published_at=now if status == "active" else None,
            created_at=now,
            updated_at=now,
        )
        self._place(row)
        self.replace_media(post_id, media_ids)
        return row

    def _place(self, post: OrgPost) -> None:
        """Insert the live projection matching the post's status."""
        if (post.status or "active") == "draft":
            OrgPostDraft.create(
                org_id=post.org_id, author_id=post.author_id,
                post_id=post.post_id,
            )
        else:
            OrgPostFeed.create(
                org_id=post.org_id, post_id=post.post_id,
                kind=post.kind or "discussion",
            )
            if (post.kind or "discussion") == "announcement":
                AnnouncementFeed.create(
                    bucket=TIMELINE_BUCKET,
                    post_id=post.post_id,
                    org_id=post.org_id,
                )

    def _unplace(self, post: OrgPost) -> None:
        """Drop every live projection (feed, pin, draft) of the post."""
        if (
            (post.kind or "discussion") == "announcement"
            and (post.status or "active") != "draft"
        ):
            AnnouncementFeed.objects(
                bucket=TIMELINE_BUCKET, post_id=post.post_id
            ).delete()
        OrgPostFeed.objects(
            org_id=post.org_id, post_id=post.post_id
        ).delete()
        OrgPostPinned.objects(
            org_id=post.org_id, post_id=post.post_id
        ).delete()
        OrgPostDraft.objects(
            org_id=post.org_id, author_id=post.author_id,
            post_id=post.post_id,
        ).delete()

    def get(self, post_id: UUID) -> OrgPost | None:
        return OrgPost.objects(post_id=post_id).first()

    def list_feed(self, org_id: UUID, limit: int) -> list[OrgPostFeed]:
        return list(OrgPostFeed.objects(org_id=org_id).limit(limit))

    def list_timeline(
        self, cursor: UUID | None, limit: int
    ) -> list[AnnouncementFeed]:
        query = AnnouncementFeed.objects(bucket=TIMELINE_BUCKET)
        if cursor is not None:
            query = query.filter(post_id__lt=cursor)
        return list(query.limit(limit))

    def count_feed(self, org_id: UUID) -> int:
        row = get_session().execute(
            f"SELECT COUNT(*) AS c FROM {self._keyspace}.org_posts_feed"
            " WHERE org_id = %s",
            [org_id],
        ).one()
        return int(row["c"]) if row is not None else 0

    def list_pinned(self, org_id: UUID, limit: int = 5) -> list[UUID]:
        rows = OrgPostPinned.objects(org_id=org_id).limit(limit)
        return [row.post_id for row in rows]

    def list_drafts(
        self, org_id: UUID, author_id: UUID, limit: int
    ) -> list[UUID]:
        rows = OrgPostDraft.objects(
            org_id=org_id, author_id=author_id
        ).limit(limit)
        return [row.post_id for row in rows]

    def count_drafts(self, org_id: UUID, author_id: UUID) -> int:
        row = get_session().execute(
            f"SELECT COUNT(*) AS c FROM {self._keyspace}.org_post_drafts"
            " WHERE org_id = %s AND author_id = %s",
            [org_id, author_id],
        ).one()
        return int(row["c"]) if row is not None else 0

    def list_trash(self, org_id: UUID, limit: int) -> list[OrgPostTrash]:
        return list(OrgPostTrash.objects(org_id=org_id).limit(limit))

    def update_body(
        self, post: OrgPost, title: str, body: str, now: datetime
    ) -> None:
        OrgPost.objects(post_id=post.post_id).update(
            title=title, body=body, edited_at=now, updated_at=now
        )

    def update_content(
        self,
        post: OrgPost,
        kind: str,
        title: str,
        body: str,
        blocks_json: str,
        cover_media_id: UUID | None,
        now: datetime,
    ) -> None:
        OrgPost.objects(post_id=post.post_id).update(
            kind=kind, title=title, body=body, blocks_json=blocks_json,
            cover_media_id=cover_media_id, edited_at=now, updated_at=now,
        )

    def replace_media(self, post_id: UUID, media_ids: list[UUID]) -> None:
        OrgPostMedia.objects(post_id=post_id).delete()
        for position, asset_id in enumerate(media_ids):
            OrgPostMedia.create(
                post_id=post_id, position=position, asset_id=asset_id
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

    def set_status(self, post: OrgPost, status: str, now: datetime) -> None:
        self._unplace(post)
        fields: dict[str, object] = {
            "status": status, "pinned_at": None, "updated_at": now,
        }
        if status == "active" and post.published_at is None:
            fields["published_at"] = now
        OrgPost.objects(post_id=post.post_id).update(**fields)
        post.status = status
        self._place(post)

    def soft_delete(self, post: OrgPost, now: datetime) -> None:
        self._unplace(post)
        OrgPost.objects(post_id=post.post_id).update(
            deleted_at=now, pinned_at=None, updated_at=now
        )
        OrgPostTrash.create(
            org_id=post.org_id, post_id=post.post_id,
            author_id=post.author_id, status=post.status or "active",
        )

    def restore(self, post: OrgPost, now: datetime) -> None:
        OrgPostTrash.objects(
            org_id=post.org_id, post_id=post.post_id
        ).delete()
        OrgPost.objects(post_id=post.post_id).update(
            deleted_at=None, updated_at=now
        )
        self._place(post)

    def delete(self, post: OrgPost) -> None:
        self._unplace(post)
        OrgPostTrash.objects(
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
