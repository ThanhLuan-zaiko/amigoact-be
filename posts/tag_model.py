"""Edge indexes for org tags attached to board posts."""

from __future__ import annotations

import core.database  # noqa: F401  (reactor compat shim must run first)
from cassandra.cqlengine import columns, models


class PostTagsByOrg(models.Model):
    """Edge index: org tag slug -> post ids, live and trashed.

    Mirrors org_posts.tag_names. Soft-deleting a post does not touch
    these rows; a tag soft-delete strips them after snapshotting.
    """

    __table_name__ = "post_tags_by_org"

    org_id = columns.UUID(primary_key=True, partition_key=True)
    tag_slug = columns.Text(primary_key=True, clustering_order="ASC")
    post_id = columns.UUID(primary_key=True, clustering_order="ASC")


class TrashedPostTagEdgesByOrg(models.Model):
    """Remembered post edges of a soft-deleted tag, for exact restore."""

    __table_name__ = "trashed_post_tag_edges_by_org"

    org_id = columns.UUID(primary_key=True, partition_key=True)
    tag_slug = columns.Text(primary_key=True, clustering_order="ASC")
    post_id = columns.UUID(primary_key=True, clustering_order="ASC")
