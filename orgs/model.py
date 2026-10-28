"""cqlengine models for the orgs bounded context (persistence only)."""

from __future__ import annotations

import core.database  # noqa: F401  (reactor compat shim must run first)
from core.ids import uuid7
from cassandra.cqlengine import columns, models


class Organization(models.Model):
    """Org row with owner and legal identity for business kinds."""

    __table_name__ = "organizations"

    id = columns.UUID(primary_key=True, default=uuid7)
    name = columns.Text(required=True)
    slug = columns.Text(required=True)
    description = columns.Text(required=False, default="")
    org_type = columns.Text(required=True, default="organization")
    status = columns.Text(required=True, default="active")
    join_policy = columns.Text(required=True, default="invite")
    owner_id = columns.UUID(required=True)
    tax_code = columns.Text(required=False)
    legal_rep_name = columns.Text(required=False)
    legal_rep_id = columns.Text(required=False)
    legal_rep_position = columns.Text(required=False)
    legal_status = columns.Text(required=True, default="none")
    email = columns.Text(required=False)
    phone = columns.Text(required=False)
    website = columns.Text(required=False)
    address = columns.Text(required=False)
    city = columns.Text(required=False)
    country = columns.Text(required=False)
    legal_name = columns.Text(required=False)
    license_number = columns.Text(required=False)
    is_personal = columns.Boolean(required=True, default=False)
    logo_media_id = columns.UUID(required=False)
    cover_media_id = columns.UUID(required=False)
    verified_at = columns.DateTime(required=False)
    verified_by = columns.UUID(required=False)
    previous_slug = columns.Text(required=False)
    deleted_at = columns.DateTime(required=False)
    created_at = columns.DateTime(required=True)
    updated_at = columns.DateTime(required=True)


class OrganizationsBySlug(models.Model):
    """Unique slug index claimed with LWT on create."""

    __table_name__ = "organizations_by_slug"

    slug = columns.Text(primary_key=True)
    org_id = columns.UUID(required=True)


class OrganizationsByTaxCode(models.Model):
    """One org per tax code; claimed with LWT like the slug index."""

    __table_name__ = "organizations_by_tax_code"

    tax_code = columns.Text(primary_key=True)
    org_id = columns.UUID(required=True)


class OrganizationsByLegalStatus(models.Model):
    """Platform-admin verification queue, oldest first."""

    __table_name__ = "organizations_by_legal_status"

    legal_status = columns.Text(primary_key=True, partition_key=True)
    created_at = columns.DateTime(primary_key=True, clustering_order="ASC")
    org_id = columns.UUID(primary_key=True, clustering_order="ASC")
    name = columns.Text(required=True)
    slug = columns.Text(required=True)


class OrganizationsPublic(models.Model):
    """Public directory feed partitioned by kind, newest first.

    Carries only the join fields (like the legal-status queue); the
    canonical Organization row is re-read per item at request time.
    """

    __table_name__ = "organizations_public"

    kind = columns.Text(primary_key=True, partition_key=True)
    created_at = columns.DateTime(primary_key=True, clustering_order="DESC")
    org_id = columns.UUID(primary_key=True, clustering_order="ASC")
    name = columns.Text(required=True)
    slug = columns.Text(required=True)


class OrganizationMember(models.Model):
    """Membership rows partitioned by org."""

    __table_name__ = "organization_members"

    org_id = columns.UUID(primary_key=True, partition_key=True)
    user_id = columns.UUID(primary_key=True, clustering_order="ASC")
    status = columns.Text(required=True, default="active")
    invited_by = columns.UUID(required=False)
    joined_at = columns.DateTime(required=True)


class MemberByUser(models.Model):
    """Membership rows partitioned by user for mine listings."""

    __table_name__ = "members_by_user"

    user_id = columns.UUID(primary_key=True, partition_key=True)
    org_id = columns.UUID(primary_key=True, clustering_order="ASC")
    status = columns.Text(required=True, default="active")
    invited_by = columns.UUID(required=False)
    joined_at = columns.DateTime(required=True)


class MembershipForm(models.Model):
    """One question on an org's membership application form."""

    __table_name__ = "membership_forms"

    org_id = columns.UUID(primary_key=True, partition_key=True)
    position = columns.Integer(primary_key=True, clustering_order="ASC")
    question_id = columns.UUID(primary_key=True, clustering_order="ASC")
    label = columns.Text(required=True)
    field_type = columns.Text(required=True, default="text")
    required = columns.Boolean(required=True, default=False)


class MembershipApplication(models.Model):
    """One applicant's answers, kept per org for the reviewer."""

    __table_name__ = "membership_applications"

    org_id = columns.UUID(primary_key=True, partition_key=True)
    user_id = columns.UUID(primary_key=True, clustering_order="ASC")
    answers = columns.Text(required=True, default="{}")
    submitted_at = columns.DateTime(required=True)
    rejected_at = columns.DateTime(required=False)


class MediaAsset(models.Model):
    """Binary metadata; bytes live in MediaStore (local now, cloud later)."""

    __table_name__ = "media_assets"

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
    uploader_id = columns.UUID(required=False)
    storage_key = columns.Text(required=False)
    backend = columns.Text(required=False, default="local")
    original_name = columns.Text(required=False)
    visibility = columns.Text(required=False, default="organization")
    upload_status = columns.Text(required=False, default="active")
    metadata_json = columns.Text(required=False)
    thumb_url = columns.Text(required=False)
    created_at = columns.DateTime(required=True)
    updated_at = columns.DateTime(required=False)
    deleted_at = columns.DateTime(required=False)


class MediaByOwner(models.Model):
    """Newest-first media feed per owner (org gallery)."""

    __table_name__ = "media_by_owner"

    owner_id = columns.UUID(primary_key=True, partition_key=True)
    created_at = columns.DateTime(primary_key=True, clustering_order="DESC")
    asset_id = columns.UUID(primary_key=True, clustering_order="ASC")
    file_url = columns.Text(required=True)
    mime = columns.Text(required=True)
    owner_type = columns.Text(required=True, default="organization")


class MediaByHash(models.Model):
    """Content-checksum lookup for dedup and integrity checks."""

    __table_name__ = "media_by_hash"

    file_hash = columns.Text(primary_key=True)
    asset_id = columns.UUID(required=True)


class MediaByUploader(models.Model):
    """Newest-first feed of one user's uploads across owners."""

    __table_name__ = "media_by_uploader"

    uploader_id = columns.UUID(primary_key=True, partition_key=True)
    created_at = columns.DateTime(primary_key=True, clustering_order="DESC")
    asset_id = columns.UUID(primary_key=True, clustering_order="ASC")
    file_url = columns.Text(required=True)
    mime = columns.Text(required=True)
    owner_type = columns.Text(required=True, default="organization")


class Campus(models.Model):
    """One physical site belonging to an organization."""

    __table_name__ = "campuses"

    id = columns.UUID(primary_key=True, default=uuid7)
    org_id = columns.UUID(required=True)
    name = columns.Text(required=True)
    address = columns.Text(required=False)
    status = columns.Text(required=True, default="active")
    created_at = columns.DateTime(required=True)


class CampusByOrg(models.Model):
    """Denormalized per-org campus listing."""

    __table_name__ = "campuses_by_org"

    org_id = columns.UUID(primary_key=True, partition_key=True)
    campus_id = columns.UUID(primary_key=True)
    name = columns.Text(required=True)


class Department(models.Model):
    """One faculty/office inside an org, optionally bound to a campus."""

    __table_name__ = "departments"

    id = columns.UUID(primary_key=True, default=uuid7)
    org_id = columns.UUID(required=True)
    campus_id = columns.UUID(required=False)
    name = columns.Text(required=True)
    code = columns.Text(required=False)
    status = columns.Text(required=True, default="active")
    created_at = columns.DateTime(required=True)


class DepartmentByCampus(models.Model):
    """Departments grouped under one campus for the org tree."""

    __table_name__ = "departments_by_campus"

    campus_id = columns.UUID(primary_key=True, partition_key=True)
    department_id = columns.UUID(primary_key=True)
    name = columns.Text(required=True)
    code = columns.Text(required=False)


class DepartmentByOrg(models.Model):
    """Org-level department listing, also covering campus-less rows."""

    __table_name__ = "departments_by_org"

    org_id = columns.UUID(primary_key=True, partition_key=True)
    department_id = columns.UUID(primary_key=True)
    name = columns.Text(required=True)
    code = columns.Text(required=False)
    campus_id = columns.UUID(required=False)


class OrgType(models.Model):
    """Org-kind lookup row; seeds replace the hard-coded enum."""

    __table_name__ = "org_types"

    code = columns.Text(primary_key=True)
    name = columns.Text(required=True)
    sort_order = columns.Integer(required=False, default=0)
