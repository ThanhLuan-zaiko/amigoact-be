"""cqlengine persistence for activities. Slug claims use LWT raw CQL."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from cassandra.cqlengine.connection import get_session

from activities.feed_helpers import (
    _clear_feeds,
    _clear_tag_edges,
    _clear_trash_edges,
    _feeds,
    _hydrate,
    _tag_edges,
)
from activities.interfaces import (
    ActivityFields,
    ActivityStore,
)
from activities.model import (
    ActivitiesByCategory,
    ActivitiesByOrg,
    ActivitiesBySlug,
    ActivitiesByStatus,
    ActivitiesByTag,
    ActivitiesTrashByOrg,
    Activity,
    ActivityAnnouncement,
    ActivityMedia,
    ActivityPartner,
    ActivitySchedule,
    ActivitySkill,
    ActivitySlot,
    ActivityStaff,
    PartnerActivitiesByOrg,
    RegistrationForm,
    ScheduleByActivity,
)
from core.exceptions import SlugTakenError
from orgs.media_repository import media_feeds_delete
from orgs.model import MediaAsset, MediaByOwner


class CqlActivityStore(ActivityStore):
    """Model-backed store; the service never sees cqlengine objects."""

    def __init__(self, keyspace: str) -> None:
        self._keyspace = keyspace

    def create(
        self,
        org_id: UUID,
        created_by: UUID,
        fields: ActivityFields,
        now: datetime,
    ) -> Activity:
        from core.ids import uuid7

        activity_id = uuid7()
        session = get_session()
        claim = session.execute(
            f"INSERT INTO {self._keyspace}.activities_by_slug"
            " (org_id, slug, activity_id, title, status, start_at)"
            " VALUES (%s, %s, %s, %s, %s, %s) IF NOT EXISTS",
            [
                org_id,
                fields.slug,
                activity_id,
                fields.title,
                "draft",
                fields.start_at,
            ],
        )
        if not claim.was_applied:
            raise SlugTakenError("Activity slug is already taken.")
        row = Activity.create(
            id=activity_id,
            org_id=org_id,
            campus_id=fields.campus_id,
            title=fields.title,
            description=fields.description or "",
            category_id=fields.category_id,
            status="draft",
            location=fields.location,
            max_participants=fields.max_participants,
            start_at=fields.start_at,
            end_at=fields.end_at,
            hours_awarded=fields.hours_awarded,
            requirements_json=fields.requirements_json,
            created_by=created_by,
            slug=fields.slug,
            person_in_charge_id=fields.person_in_charge_id,
            address=fields.address,
            city=fields.city,
            latitude=fields.latitude,
            longitude=fields.longitude,
            is_remote=fields.is_remote,
            registration_deadline=fields.registration_deadline,
            tag_names=fields.tag_names,
            created_at=now,
            updated_at=now,
        )
        _feeds(row)
        _tag_edges(row)
        return row

    def get(self, activity_id: UUID) -> Activity | None:
        return Activity.objects(id=activity_id).first()

    def get_by_slug(
        self, org_id: UUID, slug: str
    ) -> ActivitiesBySlug | None:
        return ActivitiesBySlug.objects(org_id=org_id, slug=slug).first()

    def _rewrite(self, old: Activity, new: Activity) -> None:
        """Re-key feeds when clustering columns moved."""
        _clear_feeds(old)
        _feeds(new)

    def update_details(
        self, activity_id: UUID, fields: ActivityFields, now: datetime
    ) -> Activity | None:
        old = self.get(activity_id)
        if old is None:
            return None
        if fields.slug != old.slug:
            session = get_session()
            claim = session.execute(
                f"INSERT INTO {self._keyspace}.activities_by_slug"
                " (org_id, slug, activity_id, title, status, start_at)"
                " VALUES (%s, %s, %s, %s, %s, %s) IF NOT EXISTS",
                [
                    old.org_id,
                    fields.slug,
                    activity_id,
                    fields.title,
                    old.status,
                    fields.start_at,
                ],
            )
            if not claim.was_applied:
                raise SlugTakenError("Activity slug is already taken.")
        Activity.objects(id=activity_id).update(
            title=fields.title,
            description=fields.description or "",
            category_id=fields.category_id,
            location=fields.location,
            max_participants=fields.max_participants,
            start_at=fields.start_at,
            end_at=fields.end_at,
            hours_awarded=fields.hours_awarded,
            requirements_json=fields.requirements_json,
            slug=fields.slug,
            person_in_charge_id=fields.person_in_charge_id,
            address=fields.address,
            city=fields.city,
            latitude=fields.latitude,
            longitude=fields.longitude,
            is_remote=fields.is_remote,
            registration_deadline=fields.registration_deadline,
            campus_id=fields.campus_id,
            tag_names=fields.tag_names,
            updated_at=now,
        )
        new = self.get(activity_id)
        assert new is not None
        self._rewrite(old, new)
        _clear_tag_edges(old)
        _tag_edges(new)
        return new

    def set_status(
        self,
        activity_id: UUID,
        status: str,
        published_at: datetime | None,
        now: datetime,
    ) -> Activity | None:
        old = self.get(activity_id)
        if old is None:
            return None
        updates: dict[str, object] = {"status": status, "updated_at": now}
        if published_at is not None:
            updates["published_at"] = published_at
        Activity.objects(id=activity_id).update(**updates)
        new = self.get(activity_id)
        assert new is not None
        self._rewrite(old, new)
        return new

    def list_by_org(self, org_id: UUID, limit: int = 50) -> list[Activity]:
        feed = list(
            ActivitiesByOrg.objects(org_id=org_id).limit(limit).all()
        )
        return _hydrate([row.activity_id for row in feed])

    def list_by_status(
        self, status: str, limit: int = 50
    ) -> list[Activity]:
        feed = list(
            ActivitiesByStatus.objects(status=status).limit(limit).all()
        )
        return _hydrate([row.activity_id for row in feed])

    def list_by_category(
        self, category_id: UUID, limit: int = 50
    ) -> list[Activity]:
        feed = list(
            ActivitiesByCategory.objects(category_id=category_id)
            .limit(limit)
            .all()
        )
        return _hydrate([row.activity_id for row in feed])

    def list_by_tag(
        self, slug: str, limit: int = 50
    ) -> list[Activity]:
        feed = list(
            ActivitiesByTag.objects(tag_slug=slug).limit(limit).all()
        )
        return _hydrate([row.activity_id for row in feed])

    def mark_deleted(
        self, activity_id: UUID, now: datetime
    ) -> Activity | None:
        row = self.get(activity_id)
        if row is None:
            return None
        _clear_feeds(row, keep_slug=True)
        ActivitiesTrashByOrg.create(
            org_id=row.org_id,
            deleted_at=now,
            activity_id=row.id,
            title=row.title,
            status=row.status,
            start_at=row.start_at,
        )
        row.deleted_at = now
        row.updated_at = now
        row.save()
        return row

    def mark_restored(
        self, activity_id: UUID, now: datetime
    ) -> Activity | None:
        row = self.get(activity_id)
        if row is None:
            return None
        _feeds(row)
        if row.deleted_at is not None:
            ActivitiesTrashByOrg.objects(
                org_id=row.org_id,
                deleted_at=row.deleted_at,
                activity_id=row.id,
            ).delete()
        row.deleted_at = None
        row.updated_at = now
        row.save()
        return row

    def list_trash(self, org_id: UUID, limit: int = 50) -> list[Activity]:
        feed = list(
            ActivitiesTrashByOrg.objects(org_id=org_id)
            .limit(limit)
            .all()
        )
        return _hydrate([row.activity_id for row in feed])

    def delete_everything(self, activity_id: UUID) -> list[str]:
        row = self.get(activity_id)
        if row is None:
            return []
        _clear_feeds(row)
        _clear_tag_edges(row)
        _clear_trash_edges(row)
        if row.deleted_at is not None:
            ActivitiesTrashByOrg.objects(
                org_id=row.org_id,
                deleted_at=row.deleted_at,
                activity_id=row.id,
            ).delete()
        for edge in ActivityPartner.objects(activity_id=activity_id):
            PartnerActivitiesByOrg.objects(
                org_id=edge.org_id,
                start_at=row.start_at,
                activity_id=activity_id,
            ).delete()
            edge.delete()
        ActivitySkill.objects(activity_id=activity_id).delete()
        ActivityStaff.objects(activity_id=activity_id).delete()
        ActivityAnnouncement.objects(activity_id=activity_id).delete()
        RegistrationForm.objects(activity_id=activity_id).delete()
        # activity_id is not the schedule PK, so the purge scans once;
        # it also catches start_at-less schedules the feed never indexed.
        for schedule in (
            ActivitySchedule.objects.filter(activity_id=activity_id)
            .allow_filtering()
            .all()
        ):
            ActivitySlot.objects(schedule_id=schedule.id).delete()
            schedule.delete()
        ScheduleByActivity.objects(activity_id=activity_id).delete()
        ActivityMedia.objects(activity_id=activity_id).delete()
        paths: list[str] = []
        for link in MediaByOwner.objects(owner_id=activity_id).all():
            asset = MediaAsset.objects(asset_id=link.asset_id).first()
            if asset is not None:
                paths.append(asset.file_url)
                media_feeds_delete(asset)
                asset.delete()
            link.delete()
        row.delete()
        return paths
