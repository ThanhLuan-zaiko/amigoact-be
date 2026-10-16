"""Guest-facing post reads: profile teasers plus the public article.

Only `public`-visibility posts reach guests; member-scoped posts,
drafts, revisions and trash stay inside the member board. The feed
projection already holds exactly the published non-trashed ids, so
listing scans visibility-tagged feed rows and hydrates only the slice
the profile renders.
"""

from __future__ import annotations

from uuid import UUID

from core.exceptions import NotFoundError
from orgs.interfaces import (
    MediaRepository,
    OrgPostBrief,
    OrgPostListing,
    OrgRepository,
    PostDirectory,
    UserDirectory,
)
from posts.dtos import (
    PostMediaBrief,
    PostSnapshot,
    TimelineItem,
    TimelineOrg,
    TimelinePage,
)
from posts.helpers import post_visibility
from posts.interfaces import CommentStore, PostStore
from posts.model import OrgPost
from posts.snapshots import PostSnapshots, public_media_url

_PUBLIC = "public"
_FEED_SCAN_LIMIT = 500
_EXCERPT_MAX = 200
_TIMELINE_MAX_SCANS = 4


def _excerpt(text: str, max_len: int = _EXCERPT_MAX) -> str:
    flat = " ".join(text.split())
    if len(flat) <= max_len:
        return flat
    return f"{flat[:max_len].rstrip()}..."


class PublicPostService(PostDirectory):
    """Read-only guest surface; only public-safe fields ever leave here."""

    def __init__(
        self,
        orgs: OrgRepository,
        posts: PostStore,
        comments: CommentStore,
        users: UserDirectory,
        media: MediaRepository,
    ) -> None:
        self._orgs = orgs
        self._posts = posts
        self._media = media
        self._snapshots = PostSnapshots(
            posts=posts, comments=comments, users=users, media=media
        )

    def _public_feed(self, org_id: UUID) -> list:
        """Feed rows tagged public (the projection already excludes
        drafts and trash, so the row count is the exact public total)."""
        return [
            item
            for item in self._posts.list_feed(org_id, _FEED_SCAN_LIMIT)
            if post_visibility(item) == _PUBLIC
        ]

    def _briefs(self, feed: list) -> list[OrgPostBrief]:
        rows = {
            item.post_id: row
            for item in feed
            if (row := self._posts.get(item.post_id)) is not None
            and self._is_public(row)
        }
        return [
            self._brief(rows[item.post_id])
            for item in feed
            if item.post_id in rows
        ]

    def list_public(self, org_id: UUID, limit: int = 4) -> OrgPostListing:
        """Public-post briefs for the org profile; feed rows carry kind
        and visibility."""
        feed = self._public_feed(org_id)
        return OrgPostListing(
            total=len(feed),
            items=self._briefs(feed[:limit]),
        )

    def list_public_page(
        self, slug: str, limit: int, page: int
    ) -> OrgPostListing:
        """Paged public-post teasers for the public news listing."""
        org = self._live_org(slug)
        feed = self._public_feed(org.id)
        start = (page - 1) * limit
        return OrgPostListing(
            total=len(feed),
            items=self._briefs(feed[start : start + limit]),
        )

    def list_timeline(
        self, cursor: UUID | None, limit: int
    ) -> TimelinePage:
        """Global guest timeline: newest public posts across orgs.

        Feed rows whose canonical post or org went dead are skipped
        lazily (bounded re-scans); the cursor always advances past the
        last scanned row so dead rows can never stall the pager.
        """
        items: list[TimelineItem] = []
        last_seen = cursor
        exhausted = False
        for _ in range(_TIMELINE_MAX_SCANS):
            if len(items) >= limit or exhausted:
                break
            rows = self._posts.list_timeline(last_seen, limit + 1)
            exhausted = len(rows) < limit + 1
            for feed_row in rows:
                if len(items) >= limit:
                    break
                last_seen = feed_row.post_id
                item = self._timeline_item(feed_row)
                if item is not None:
                    items.append(item)
        next_cursor = (
            str(last_seen)
            if last_seen is not None and not exhausted
            else None
        )
        return TimelinePage(items=items, next_cursor=next_cursor)

    def _timeline_item(self, feed_row) -> TimelineItem | None:  # noqa: ANN001
        """Hydrate one feed row; dead post or dead org reads as None."""
        row = self._posts.get(feed_row.post_id)
        if row is None or not self._is_public(row):
            return None
        org = self._orgs.get_by_id(row.org_id)
        if (
            org is None
            or getattr(org, "deleted_at", None) is not None
            or (getattr(org, "status", "active") or "active") != "active"
        ):
            return None
        snapshot = self._snapshots.build(row)
        media = sorted(
            snapshot.media,
            key=lambda item: item.asset_id != row.cover_media_id,
        )
        return TimelineItem(
            id=row.post_id,
            title=snapshot.title,
            excerpt=_excerpt(snapshot.body),
            cover_url=self._cover_url(row, snapshot),
            author_name=snapshot.author_name,
            author_avatar_url=snapshot.author_avatar_url,
            published_at=snapshot.published_at,
            comment_count=snapshot.comment_count,
            media=media[:6],
            media_count=len(media),
            org=TimelineOrg(
                id=org.id,
                name=org.name,
                slug=org.slug,
                logo_url=self._org_logo(org),
            ),
        )

    def _org_logo(self, org) -> str | None:  # noqa: ANN001, ANN202
        """Resolve the org's logo asset to its semi-public /media/ URL."""
        asset_id = getattr(org, "logo_media_id", None)
        if asset_id is None:
            return None
        asset = self._media.get_asset(asset_id)
        return public_media_url(asset.file_url) if asset is not None else None

    def get_public_post(self, slug: str, post_id: UUID) -> PostSnapshot:
        """One published public post under a live org; everything else 404."""
        org = self._live_org(slug)
        row = self._posts.get(post_id)
        if (
            row is None
            or getattr(row, "org_id", None) != org.id
            or not self._is_public(row)
        ):
            raise NotFoundError("Announcement not found.")
        return self._snapshots.build(row)

    def list_public_post_media(
        self, slug: str, post_id: UUID
    ) -> list[PostMediaBrief]:
        """Complete cover-first media list of one public post.

        The timeline teaser only carries six preview tiles; the in-feed
        lightbox calls this so +N media stay reachable without leaving
        the feed. Same 404 boundary as the public article itself.
        """
        org = self._live_org(slug)
        row = self._posts.get(post_id)
        if (
            row is None
            or getattr(row, "org_id", None) != org.id
            or not self._is_public(row)
        ):
            raise NotFoundError("Announcement not found.")
        return sorted(
            self._snapshots.media_briefs(post_id),
            key=lambda item: item.asset_id != row.cover_media_id,
        )

    def _live_org(self, slug: str):
        """Resolve a live public org by slug; missing/deleted ones 404."""
        org = self._orgs.get_by_slug(slug.strip().lower())
        if (
            org is None
            or getattr(org, "deleted_at", None) is not None
            or (getattr(org, "status", "active") or "active") != "active"
        ):
            raise NotFoundError("Organization not found.")
        return org

    @staticmethod
    def _is_public(row: OrgPost) -> bool:
        """Published public-audience rows only: no drafts, revisions, trash."""
        return (
            (row.status or "active") == "active"
            and getattr(row, "deleted_at", None) is None
            and post_visibility(row) == _PUBLIC
            and getattr(row, "revision_of", None) is None
        )

    def _brief(self, row: OrgPost) -> OrgPostBrief:
        snapshot = self._snapshots.build(row)
        return OrgPostBrief(
            id=row.post_id,
            title=snapshot.title,
            excerpt=_excerpt(snapshot.body),
            cover_url=self._cover_url(row, snapshot),
            author_name=snapshot.author_name,
            published_at=snapshot.published_at,
            comment_count=snapshot.comment_count,
        )

    def _cover_url(self, row: OrgPost, snapshot: PostSnapshot) -> str | None:
        """Cover asset first, then the first linked image, like the FE card."""
        for item in snapshot.media:
            if item.asset_id == row.cover_media_id:
                return item.file_url
        for item in snapshot.media:
            if item.mime.startswith("image/"):
                return item.file_url
        if row.cover_media_id is not None:
            asset = self._media.get_asset(row.cover_media_id)
            if asset is not None:
                return public_media_url(asset.file_url)
        return None
