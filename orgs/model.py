"""cqlengine models for the orgs bounded context (persistence only)."""

from __future__ import annotations

import core.database  # noqa: F401  (reactor compat shim must run first)
from core.ids import uuid7
from cassandra.cqlengine import columns, models


class Organization(models.Model):
    """Org row with owner and legal identity for business kinds."""

    __table_name__ = "organizations"
    __keyspace__ = "amigoact"

    id = columns.UUID(primary_key=True, default=uuid7)
    name = columns.Text(required=True)
    slug = columns.Text(required=True)
    description = columns.Text(required=False, default="")
    org_type = columns.Text(required=True, default="organization")
    status = columns.Text(required=True, default="active")
    owner_id = columns.UUID(required=True)
    tax_code = columns.Text(required=False)
    legal_rep_name = columns.Text(required=False)
    legal_rep_id = columns.Text(required=False)
    legal_rep_position = columns.Text(required=False)
    legal_status = columns.Text(required=True, default="none")
    deleted_at = columns.DateTime(required=False)
    created_at = columns.DateTime(required=True)
    updated_at = columns.DateTime(required=True)


class OrganizationsBySlug(models.Model):
    """Unique slug index claimed with LWT on create."""

    __table_name__ = "organizations_by_slug"
    __keyspace__ = "amigoact"

    slug = columns.Text(primary_key=True)
    org_id = columns.UUID(required=True)


class OrganizationMember(models.Model):
    """Membership rows partitioned by org."""

    __table_name__ = "organization_members"
    __keyspace__ = "amigoact"

    org_id = columns.UUID(primary_key=True, partition_key=True)
    user_id = columns.UUID(primary_key=True, clustering_order="ASC")
    status = columns.Text(required=True, default="active")
    joined_at = columns.DateTime(required=True)


class MemberByUser(models.Model):
    """Membership rows partitioned by user for mine listings."""

    __table_name__ = "members_by_user"
    __keyspace__ = "amigoact"

    user_id = columns.UUID(primary_key=True, partition_key=True)
    org_id = columns.UUID(primary_key=True, clustering_order="ASC")
    status = columns.Text(required=True, default="active")
    joined_at = columns.DateTime(required=True)


class MediaAsset(models.Model):
    """Binary metadata; bytes live in MediaStore (local now, cloud later)."""

    __table_name__ = "media_assets"
    __keyspace__ = "amigoact"

    asset_id = columns.UUID(primary_key=True, default=uuid7)
    owner_id = columns.UUID(required=True)
    owner_type = columns.Text(required=True, default="organization")
    file_url = columns.Text(required=True)
    file_hash = columns.Text(required=False)
    mime = columns.Text(required=True)
    width = columns.Integer(required=False)
    height = columns.Integer(required=False)
    size_bytes = columns.BigInt(required=True, default=0)
    role = columns.Text(required=True, default="gallery")
    created_at = columns.DateTime(required=True)


class MediaByOwner(models.Model):
    """Newest-first media feed per owner (org gallery)."""

    __table_name__ = "media_by_owner"
    __keyspace__ = "amigoact"

    owner_id = columns.UUID(primary_key=True, partition_key=True)
    created_at = columns.DateTime(primary_key=True, clustering_order="DESC")
    asset_id = columns.UUID(primary_key=True, clustering_order="ASC")
    file_url = columns.Text(required=True)
    mime = columns.Text(required=True)
    owner_type = columns.Text(required=True, default="organization")
