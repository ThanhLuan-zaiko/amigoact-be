"""Post row -> PostSnapshot projection (author, media, comment total)."""

from __future__ import annotations

from uuid import UUID

from orgs.interfaces import MediaRepository, UserDirectory
from posts.blocks import load_blocks
from posts.dtos import PostMediaBrief, PostSnapshot
from posts.interfaces import CommentStore, PostStore
from posts.model import OrgPost


def public_media_url(file_url: str) -> str:
    """Stored paths are relative to the media root; serve under /media/."""
    if file_url.startswith(("/", "http://", "https://")):
        return file_url
    return f"/media/{file_url}"


class PostSnapshots:
    """Read-side joins shared by every post service."""

    def __init__(
        self,
        posts: PostStore,
        comments: CommentStore,
        users: UserDirectory,
        media: MediaRepository,
    ) -> None:
        self._posts = posts
        self._comments = comments
        self._users = users
        self._media = media

    def media_briefs(self, post_id: UUID) -> list[PostMediaBrief]:
        briefs: list[PostMediaBrief] = []
        for link in self._posts.list_media(post_id):
            asset = self._media.get_asset(link.asset_id)
            if asset is None:
                continue
            briefs.append(
                PostMediaBrief(
                    asset_id=asset.asset_id,
                    file_url=public_media_url(asset.file_url),
                    mime=asset.mime,
                )
            )
        return briefs

    def build(self, row: OrgPost) -> PostSnapshot:
        brief = self._users.get_brief(row.author_id)
        status = "draft" if (row.status or "active") == "draft" else "published"
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
            media=self.media_briefs(row.post_id),
            comment_count=self._comments.count(row.post_id),
            created_at=row.created_at,
            status=status,
            blocks=load_blocks(getattr(row, "blocks_json", None)),
            cover_media_id=getattr(row, "cover_media_id", None),
            published_at=getattr(row, "published_at", None)
            or (row.created_at if status == "published" else None),
            deleted_at=getattr(row, "deleted_at", None),
            updated_at=getattr(row, "updated_at", None),
        )

    def fresh(self, post_id: UUID) -> PostSnapshot:
        row = self._posts.get(post_id)
        assert row is not None
        return self.build(row)
