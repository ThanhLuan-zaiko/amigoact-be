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
    """Canonical post row; detail/edit/delete lookups by primary key."""

    __table_name__ = "org_posts"
    __keyspace__ = "amigoact"

    post_id = columns.UUID(primary_key=True, default=uuid7)
    org_id = columns.UUID(required=True)
    author_id = columns.UUID(required=True)
    kind = columns.Text(required=True, default="discussion")
    title = columns.Text(required=False, default="")
    body = columns.Text(required=True)
    status = columns.Text(required=True, default="active")
    pinned_at = columns.DateTime(required=False)
    edited_at = columns.DateTime(required=False)
    created_at = columns.DateTime(required=True)
    updated_at = columns.DateTime(required=True)


class OrgPostFeed(models.Model):
    """Org board, newest first; slim rows re-read OrgPost per item."""

    __table_name__ = "org_posts_feed"
    __keyspace__ = "amigoact"

    org_id = columns.UUID(primary_key=True, partition_key=True)
    post_id = columns.UUID(
        primary_key=True, clustering_order="DESC", default=uuid7
    )


class OrgPostPinned(models.Model):
    """Pinned posts of one org, newest post first."""

    __table_name__ = "org_posts_pinned"
    __keyspace__ = "amigoact"

    org_id = columns.UUID(primary_key=True, partition_key=True)
    post_id = columns.UUID(
        primary_key=True, clustering_order="DESC", default=uuid7
    )


class OrgPostMedia(models.Model):
    """Gallery attachments per post; the asset stays owned by the org."""

    __table_name__ = "org_post_media"
    __keyspace__ = "amigoact"

    post_id = columns.UUID(primary_key=True, partition_key=True)
    position = columns.Integer(primary_key=True, clustering_order="ASC")
    asset_id = columns.UUID(primary_key=True, clustering_order="ASC")


class OrgPostComment(models.Model):
    """Flat comment thread of one post, oldest first."""

    __table_name__ = "org_post_comments"
    __keyspace__ = "amigoact"

    post_id = columns.UUID(primary_key=True, partition_key=True)
    comment_id = columns.UUID(
        primary_key=True, clustering_order="ASC", default=uuid7
    )
    author_id = columns.UUID(required=True)
    body = columns.Text(required=True)
    created_at = columns.DateTime(required=True)
