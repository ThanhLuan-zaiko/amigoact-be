"""cqlengine models for the activities bounded context."""

from __future__ import annotations

import core.database  # noqa: F401  (reactor compat shim must run first)
from core.ids import uuid7
from core.tags import tag_fold, tag_slug  # noqa: F401  (re-export)
from cassandra.cqlengine import columns, models


class Activity(models.Model):
    """Source-of-truth row; every feed below is a denormalized projection."""

    __table_name__ = "activities"

    id = columns.UUID(primary_key=True, default=uuid7)
    org_id = columns.UUID(required=True)
    campus_id = columns.UUID(required=False)
    title = columns.Text(required=True)
    description = columns.Text(required=False, default="")
    category_id = columns.UUID(required=False)
    status = columns.Text(required=True, default="draft")
    location = columns.Text(required=False)
    max_participants = columns.Integer(required=False)
    start_at = columns.DateTime(required=False)
    end_at = columns.DateTime(required=False)
    hours_awarded = columns.Double(required=False, default=0.0)
    requirements_json = columns.Text(required=False)
    cover_media_id = columns.UUID(required=False)
    created_by = columns.UUID(required=True)
    slug = columns.Text(required=True)
    person_in_charge_id = columns.UUID(required=False)
    address = columns.Text(required=False)
    city = columns.Text(required=False)
    latitude = columns.Decimal(required=False)
    longitude = columns.Decimal(required=False)
    is_remote = columns.Boolean(required=False, default=False)
    registration_deadline = columns.DateTime(required=False)
    published_at = columns.DateTime(required=False)
    # Canonical display names resolved by TagService.ensure; tag_slug(name)
    # keys the activities_by_tag read model, so no second slug column.
    tag_names = columns.List(columns.Text, required=False)
    deleted_at = columns.DateTime(required=False)
    created_at = columns.DateTime(required=True)
    updated_at = columns.DateTime(required=True)


class ActivitiesByOrg(models.Model):
    """Org feed: newest-first by start_at for the manage screens."""

    __table_name__ = "activities_by_org"

    org_id = columns.UUID(primary_key=True, partition_key=True)
    start_at = columns.DateTime(primary_key=True, clustering_order="DESC")
    activity_id = columns.UUID(
        primary_key=True, clustering_order="ASC", default=uuid7
    )
    title = columns.Text(required=True)
    status = columns.Text(required=True)
    campus_id = columns.UUID(required=False)


class ActivitiesByStatus(models.Model):
    """Public feed partitioned by status for the discovery surface."""

    __table_name__ = "activities_by_status"

    status = columns.Text(primary_key=True, partition_key=True)
    start_at = columns.DateTime(primary_key=True, clustering_order="DESC")
    activity_id = columns.UUID(
        primary_key=True, clustering_order="ASC", default=uuid7
    )
    org_id = columns.UUID(required=True)
    title = columns.Text(required=True)


class ActivitiesByCategory(models.Model):
    """Discovery feed partitioned by catalog category."""

    __table_name__ = "activities_by_category"

    category_id = columns.UUID(primary_key=True, partition_key=True)
    start_at = columns.DateTime(primary_key=True, clustering_order="DESC")
    activity_id = columns.UUID(
        primary_key=True, clustering_order="ASC", default=uuid7
    )
    org_id = columns.UUID(required=True)
    title = columns.Text(required=True)


class ActivitiesByTag(models.Model):
    """Community-tag feed partitioned by canonical slug."""

    __table_name__ = "activities_by_tag"

    tag_slug = columns.Text(primary_key=True, partition_key=True)
    start_at = columns.DateTime(primary_key=True, clustering_order="DESC")
    activity_id = columns.UUID(
        primary_key=True, clustering_order="ASC", default=uuid7
    )
    org_id = columns.UUID(required=True)
    title = columns.Text(required=True)
    status = columns.Text(required=True)


class ActivitiesTrashByOrg(models.Model):
    """Manager trash bin: soft-deleted rows stay listable per org."""

    __table_name__ = "activities_trash_by_org"

    org_id = columns.UUID(primary_key=True, partition_key=True)
    deleted_at = columns.DateTime(primary_key=True, clustering_order="DESC")
    activity_id = columns.UUID(primary_key=True, clustering_order="ASC")
    title = columns.Text(required=True)
    status = columns.Text(required=True)
    start_at = columns.DateTime(required=False)


class ActivityMedia(models.Model):
    """Ordered gallery entries bound to one activity."""

    __table_name__ = "activity_media"

    activity_id = columns.UUID(partition_key=True, primary_key=True)
    position = columns.Integer(primary_key=True)
    asset_id = columns.UUID(primary_key=True)
    role = columns.Text(required=True, default="gallery")
    caption = columns.Text(required=False)


class ActivitiesBySlug(models.Model):
    """Pretty-URL lookup; also the per-org slug uniqueness claim."""

    __table_name__ = "activities_by_slug"

    org_id = columns.UUID(primary_key=True, partition_key=True)
    slug = columns.Text(primary_key=True, clustering_order="ASC")
    activity_id = columns.UUID(required=True)
    title = columns.Text(required=True)
    status = columns.Text(required=True)
    start_at = columns.DateTime(required=False)


class ActivityCategory(models.Model):
    """Catalog row; org_id NULL means the row is global."""

    __table_name__ = "activity_categories"

    id = columns.UUID(primary_key=True, default=uuid7)
    org_id = columns.UUID(required=False)
    name = columns.Text(required=True)
    slug = columns.Text(required=True)
    description = columns.Text(required=False)
    icon = columns.Text(required=False)
    default_hours = columns.Double(required=False)
    color = columns.Text(required=False)


class ActivitySkill(models.Model):
    """Activity -> skill edge (required or desired)."""

    __table_name__ = "activity_skills"

    activity_id = columns.UUID(primary_key=True, partition_key=True)
    skill_id = columns.UUID(primary_key=True, clustering_order="ASC")
    is_required = columns.Boolean(required=True, default=False)


class ActivityPartner(models.Model):
    """Activity -> partner org edge (co_organizer | sponsor)."""

    __table_name__ = "activity_partners"

    activity_id = columns.UUID(primary_key=True, partition_key=True)
    org_id = columns.UUID(primary_key=True, clustering_order="ASC")
    role = columns.Text(required=True)
    note = columns.Text(required=False)


class PartnerActivitiesByOrg(models.Model):
    """Reverse feed: activities one org partners on."""

    __table_name__ = "partner_activities_by_org"

    org_id = columns.UUID(primary_key=True, partition_key=True)
    start_at = columns.DateTime(primary_key=True, clustering_order="DESC")
    activity_id = columns.UUID(
        primary_key=True, clustering_order="ASC", default=uuid7
    )
    title = columns.Text(required=True)
    role = columns.Text(required=True)


class ActivitySchedule(models.Model):
    """One session inside an activity (shifts hang off slots later)."""

    __table_name__ = "activity_schedules"

    id = columns.UUID(primary_key=True, default=uuid7)
    activity_id = columns.UUID(required=True)
    title = columns.Text(required=True)
    location = columns.Text(required=False)
    start_at = columns.DateTime(required=False)
    end_at = columns.DateTime(required=False)
    status = columns.Text(required=True, default="scheduled")
    created_at = columns.DateTime(required=True)


class ScheduleByActivity(models.Model):
    """Session feed per activity; the main row stays keyed by id."""

    __table_name__ = "schedules_by_activity"

    activity_id = columns.UUID(primary_key=True, partition_key=True)
    start_at = columns.DateTime(primary_key=True, clustering_order="ASC")
    schedule_id = columns.UUID(
        primary_key=True, clustering_order="ASC", default=uuid7
    )
    title = columns.Text(required=True)
    status = columns.Text(required=True, default="scheduled")


class ActivityStaff(models.Model):
    """Staff assignment: organizer | supervisor | supporter."""

    __table_name__ = "activity_staff"

    activity_id = columns.UUID(primary_key=True, partition_key=True)
    user_id = columns.UUID(primary_key=True, clustering_order="ASC")
    staff_role = columns.Text(required=True)
    assigned_by = columns.UUID(required=True)
    assigned_at = columns.DateTime(required=True)


class ActivityAnnouncement(models.Model):
    """News board per activity, newest first."""

    __table_name__ = "activity_announcements"

    activity_id = columns.UUID(primary_key=True, partition_key=True)
    published_at = columns.DateTime(
        primary_key=True, clustering_order="DESC"
    )
    announcement_id = columns.UUID(
        primary_key=True, clustering_order="ASC", default=uuid7
    )
    title = columns.Text(required=True)
    body = columns.Text(required=False)
    created_by = columns.UUID(required=True)


class RegistrationForm(models.Model):
    """One custom question on an activity's sign-up form."""

    __table_name__ = "registration_forms"

    activity_id = columns.UUID(primary_key=True, partition_key=True)
    position = columns.Integer(
        primary_key=True, clustering_order="ASC"
    )
    question_id = columns.UUID(
        primary_key=True, clustering_order="ASC", default=uuid7
    )
    label = columns.Text(required=True)
    field_type = columns.Text(required=True, default="text")
    required = columns.Boolean(required=True, default=False)


class ActivitySlot(models.Model):
    """One capacity-bounded shift inside a schedule."""

    __table_name__ = "activity_slots"

    schedule_id = columns.UUID(primary_key=True, partition_key=True)
    slot_id = columns.UUID(
        primary_key=True, clustering_order="ASC", default=uuid7
    )
    title = columns.Text(required=True)
    capacity = columns.Integer(required=False)
    registered = columns.Integer(required=False, default=0)
    start_at = columns.DateTime(required=False)
    end_at = columns.DateTime(required=False)
