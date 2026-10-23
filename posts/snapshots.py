"""Post row -> PostSnapshot projection (author, media, comment total)."""

from __future__ import annotations

from uuid import UUID

from core.security import utc_aware
from orgs.interfaces import MediaRepository, UserBrief, UserDirectory
from posts.blocks import load_blocks
from posts.dtos import PostMediaBrief, PostSnapshot
from posts.helpers import post_visibility
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

    def _avatar_url(self, brief: UserBrief | None) -> str | None:
        """Author avatar asset -> semi-public /media/ URL, like profiles."""
        asset_id = getattr(brief, "avatar_media_id", None) if brief else None
        if asset_id is None:
            return None
        asset = self._media.get_asset(asset_id)
        return public_media_url(asset.file_url) if asset is not None else None

    def build(self, row: OrgPost) -> PostSnapshot:
        brief = self._users.get_brief(row.author_id)
        status = "draft" if (row.status or "active") == "draft" else "published"
        return PostSnapshot(
            post_id=row.post_id,
            org_id=row.org_id,
            author_id=row.author_id,
            author_name=brief.full_name if brief else "Unknown user",
            author_avatar_url=self._avatar_url(brief),
            kind=row.kind or "discussion",
            title=row.title or "",
            body=row.body or "",
            pinned_at=utc_aware(row.pinned_at),
            edited_at=utc_aware(row.edited_at),
            media=self.media_briefs(row.post_id),
            tags=list(getattr(row, "tag_names", None) or []),
            comment_count=self._comments.count(row.post_id),
            created_at=utc_aware(row.created_at),
            status=status,
            blocks=load_blocks(getattr(row, "blocks_json", None)),
            cover_media_id=getattr(row, "cover_media_id", None),
            revision_of=getattr(row, "revision_of", None),
            visibility=post_visibility(row),
            published_at=utc_aware(getattr(row, "published_at", None))
            or (utc_aware(row.created_at) if status == "published" else None),
            deleted_at=utc_aware(getattr(row, "deleted_at", None)),
            updated_at=utc_aware(getattr(row, "updated_at", None)),
        )

    def fresh(self, post_id: UUID) -> PostSnapshot:
        row = self._posts.get(post_id)
        assert row is not None
        return self.build(row)
