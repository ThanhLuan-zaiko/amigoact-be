"""Personal tag catalog. A tag belongs to the user, not to an org."""

from __future__ import annotations

import core.database  # noqa: F401  (reactor compat shim must run first)
from cassandra.cqlengine import columns, models


class UserTag(models.Model):
    """One display name the user can attach to posts later."""

    __table_name__ = "tags_by_user"
    __keyspace__ = "amigoact"

    user_id = columns.UUID(primary_key=True, partition_key=True)
    slug = columns.Text(primary_key=True, clustering_order="ASC")
    name = columns.Text(required=True)
    created_at = columns.DateTime(required=True)
    updated_at = columns.DateTime(required=True)


class UserPostTag(models.Model):
    """Posts that carry one of the user's tags, newest post first."""

    __table_name__ = "post_tags_by_user"
    __keyspace__ = "amigoact"

    user_id = columns.UUID(primary_key=True, partition_key=True)
    tag_slug = columns.Text(primary_key=True, clustering_order="ASC")
    post_id = columns.UUID(primary_key=True, clustering_order="DESC")
    org_id = columns.UUID(required=True)


class UserPostTagSet(models.Model):
    """Slugs currently bound to one post, so a save can drop the old ones."""

    __table_name__ = "user_post_tag_sets"
    __keyspace__ = "amigoact"

    user_id = columns.UUID(primary_key=True, partition_key=True)
    post_id = columns.UUID(primary_key=True, clustering_order="ASC")
    org_id = columns.UUID(required=True)
    slugs = columns.List(columns.Text, required=True)


class UserActivityTag(models.Model):
    """Activities that carry one of the user's tags."""

    __table_name__ = "activity_tags_by_user"
    __keyspace__ = "amigoact"

    user_id = columns.UUID(primary_key=True, partition_key=True)
    tag_slug = columns.Text(primary_key=True, clustering_order="ASC")
    activity_id = columns.UUID(primary_key=True, clustering_order="DESC")
    org_id = columns.UUID(required=True)


class UserActivityTagSet(models.Model):
    """Slugs last written onto one activity by this user."""

    __table_name__ = "user_activity_tag_sets"
    __keyspace__ = "amigoact"

    user_id = columns.UUID(primary_key=True, partition_key=True)
    activity_id = columns.UUID(primary_key=True, clustering_order="ASC")
    org_id = columns.UUID(required=True)
    slugs = columns.List(columns.Text, required=True)
