"""cqlengine models for the posts bounded context (persistence only).

Feed and comment tables cluster by their UUIDv7 entity id, so id order
equals time order and the id doubles as the pagination cursor (schemas.cql
section 16).
"""

from __future__ import annotations

import core.database  # noqa: F401  (reactor compat shim must run first)
from core.ids import uuid7
from cassandra.cqlengine import columns, models


class OrgPost(models.Model):
    """Canonical post row; detail/edit/delete lookups by primary key.

    status is the publish state (active = published | draft); trash is
    the orthogonal deleted_at stamp so restore returns to that state.
    """

    __table_name__ = "org_posts"

    post_id = columns.UUID(primary_key=True, default=uuid7)
    org_id = columns.UUID(required=True)
    author_id = columns.UUID(required=True)
    kind = columns.Text(required=True, default="discussion")
    title = columns.Text(required=False, default="")
    body = columns.Text(required=False, default="")
    blocks_json = columns.Text(required=False, default="")
    cover_media_id = columns.UUID(required=False)
    status = columns.Text(required=True, default="active")
    # audience is orthogonal to kind; NULL on pre-visibility rows derives
    # from kind (announcement -> public, anything else -> members).
    visibility = columns.Text(required=False)
    # Canonical names from the org catalog, at most 3. post_tags_by_org
    # mirrors this list for live and trashed rows.
    tag_names = columns.List(columns.Text, required=False)
    revision_of = columns.UUID(required=False)
    pinned_at = columns.DateTime(required=False)
    edited_at = columns.DateTime(required=False)
    published_at = columns.DateTime(required=False)
    deleted_at = columns.DateTime(required=False)
    created_at = columns.DateTime(required=True)
    updated_at = columns.DateTime(required=True)


class OrgPostFeed(models.Model):
    """Org board, newest first; slim rows re-read OrgPost per item.

    kind is denormalized so kind-filtered page totals and windows never
    have to load the canonical row for every scanned id.
    """

    __table_name__ = "org_posts_feed"

    org_id = columns.UUID(primary_key=True, partition_key=True)
    post_id = columns.UUID(
        primary_key=True, clustering_order="DESC", default=uuid7
    )
    kind = columns.Text(required=True, default="discussion")
    visibility = columns.Text(required=False)


class AnnouncementFeed(models.Model):
    """Global public timeline of published announcements, newest first.

    One literal 'all' bucket partitions every row, so a single bounded
    read serves the guest feed; org_id rides along for the org card.
    """

    __table_name__ = "announcements_feed"

    bucket = columns.Text(primary_key=True, partition_key=True)
    post_id = columns.UUID(
        primary_key=True, clustering_order="DESC", default=uuid7
    )
    org_id = columns.UUID(required=True)


class OrgPostPinned(models.Model):
    """Pinned posts of one org, newest post first."""

    __table_name__ = "org_posts_pinned"

    org_id = columns.UUID(primary_key=True, partition_key=True)
    post_id = columns.UUID(
        primary_key=True, clustering_order="DESC", default=uuid7
    )


class OrgPostDraft(models.Model):
    """One author's unpublished drafts inside one org, newest first."""

    __table_name__ = "org_post_drafts"

    org_id = columns.UUID(primary_key=True, partition_key=True)
    author_id = columns.UUID(primary_key=True, partition_key=True)
    post_id = columns.UUID(
        primary_key=True, clustering_order="DESC", default=uuid7
    )


class OrgPostTrash(models.Model):
    """Soft-deleted posts of one org; author_id lets authors see theirs.

    status is the publish state at delete time so managers can skip
    trashed drafts without loading every canonical row.
    """

    __table_name__ = "org_posts_trash"

    org_id = columns.UUID(primary_key=True, partition_key=True)
    post_id = columns.UUID(
        primary_key=True, clustering_order="DESC", default=uuid7
    )
    author_id = columns.UUID(required=True)
    status = columns.Text(required=True, default="active")


class OrgPostMedia(models.Model):
    """Gallery attachments per post; the asset stays owned by the org."""

    __table_name__ = "org_post_media"

    post_id = columns.UUID(primary_key=True, partition_key=True)
    position = columns.Integer(primary_key=True, clustering_order="ASC")
    asset_id = columns.UUID(primary_key=True, clustering_order="ASC")


class OrgPostComment(models.Model):
    """Flat comment thread of one post, oldest first."""

    __table_name__ = "org_post_comments"

    post_id = columns.UUID(primary_key=True, partition_key=True)
    comment_id = columns.UUID(
        primary_key=True, clustering_order="ASC", default=uuid7
    )
    author_id = columns.UUID(required=True)
    body = columns.Text(required=True)
    created_at = columns.DateTime(required=True)
