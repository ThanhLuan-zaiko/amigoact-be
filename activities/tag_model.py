"""cqlengine models for the org-scoped activity tag catalog."""

from __future__ import annotations

import core.database  # noqa: F401  (reactor compat shim must run first)
from cassandra.cqlengine import columns, models


class TagByOrg(models.Model):
    """Per-org catalog row; the (org_id, slug) row is the LWT claim."""

    __table_name__ = "tags_by_org"
    __keyspace__ = "amigoact"

    org_id = columns.UUID(primary_key=True, partition_key=True)
    slug = columns.Text(primary_key=True, clustering_order="ASC")
    tag_id = columns.UUID(required=True)
    name = columns.Text(required=True)
    created_at = columns.DateTime(required=True)
    updated_at = columns.DateTime(required=True)
    deleted_at = columns.DateTime(required=False)


class ActivityTagsByOrg(models.Model):
    """Edge index: org tag slug -> activity ids, live and trashed."""

    __table_name__ = "activity_tags_by_org"
    __keyspace__ = "amigoact"

    org_id = columns.UUID(primary_key=True, partition_key=True)
    tag_slug = columns.Text(primary_key=True, clustering_order="ASC")
    activity_id = columns.UUID(primary_key=True, clustering_order="ASC")


class PublicTagDirectory(models.Model):
    """One row per org catalog row behind the public /tags typeahead."""

    __table_name__ = "public_tag_directory"
    __keyspace__ = "amigoact"

    bucket = columns.Text(primary_key=True, partition_key=True)
    slug = columns.Text(primary_key=True, clustering_order="ASC")
    org_id = columns.UUID(primary_key=True, clustering_order="ASC")
    name = columns.Text(required=True)

class TrashedTagEdgesByOrg(models.Model):
    """Remembered edges of a soft-deleted tag, for exact restore."""

    __table_name__ = "trashed_tag_edges_by_org"
    __keyspace__ = "amigoact"

    org_id = columns.UUID(primary_key=True, partition_key=True)
    tag_slug = columns.Text(primary_key=True, clustering_order="ASC")
    activity_id = columns.UUID(primary_key=True, clustering_order="ASC")
