"""cqlengine persistence for activities. Slug claims use LWT raw CQL."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from cassandra.cqlengine.connection import get_session

from activities.interfaces import (
    ActivityFields,
    ActivityStore,
    CategoryStore,
)
from activities.model import (
    ActivitiesByCategory,
    ActivitiesByOrg,
    ActivitiesBySlug,
    ActivitiesByStatus,
    Activity,
    ActivityCategory,
)
from core.exceptions import SlugTakenError


def _feeds(row: Activity) -> None:
    """Write every denormalized feed projection for one activity."""
    ActivitiesByOrg.create(
        org_id=row.org_id,
        start_at=row.start_at,
        activity_id=row.id,
        title=row.title,
        status=row.status,
        campus_id=row.campus_id,
    )
    ActivitiesByStatus.create(
        status=row.status,
        start_at=row.start_at,
        activity_id=row.id,
        org_id=row.org_id,
        title=row.title,
    )
    if row.category_id is not None:
        ActivitiesByCategory.create(
            category_id=row.category_id,
            start_at=row.start_at,
            activity_id=row.id,
            org_id=row.org_id,
            title=row.title,
        )
    ActivitiesBySlug.create(
        org_id=row.org_id,
        slug=row.slug,
        activity_id=row.id,
        title=row.title,
        status=row.status,
        start_at=row.start_at,
    )


def _clear_feeds(row: Activity) -> None:
    """Delete feed rows at the coordinates of the passed snapshot."""
    ActivitiesByOrg.objects(
        org_id=row.org_id, start_at=row.start_at, activity_id=row.id
    ).delete()
    ActivitiesByStatus.objects(
        status=row.status, start_at=row.start_at, activity_id=row.id
    ).delete()
    if row.category_id is not None:
        ActivitiesByCategory.objects(
            category_id=row.category_id,
            start_at=row.start_at,
            activity_id=row.id,
        ).delete()
    ActivitiesBySlug.objects(org_id=row.org_id, slug=row.slug).delete()


def _hydrate(ids: list[UUID]) -> list[Activity]:
    """Resolve feed-row ids to full activities, preserving order."""
    rows = {
        row.id: row
        for row in (Activity.objects(id=i).first() for i in ids)
        if row is not None
    }
    return [rows[i] for i in ids if i in rows]


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
            created_at=now,
            updated_at=now,
        )
        _feeds(row)
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
            updated_at=now,
        )
        new = self.get(activity_id)
        assert new is not None
        self._rewrite(old, new)
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


class CqlCategoryStore(CategoryStore):
    """Catalog reads include global rows plus the org's customs."""

    def get(self, category_id: UUID) -> ActivityCategory | None:
        return ActivityCategory.objects(id=category_id).first()

    def list(self, org_id: UUID | None) -> list[ActivityCategory]:
        return sorted(
            (
                row
                for row in ActivityCategory.objects.all()
                if row.org_id is None or row.org_id == org_id
            ),
            key=lambda row: (row.name or "").lower(),
        )

    def create(
        self,
        category_id: UUID,
        org_id: UUID | None,
        name: str,
        slug: str,
        description: str | None,
        icon: str | None,
        default_hours: float | None,
        color: str | None,
    ) -> ActivityCategory:
        return ActivityCategory.create(
            id=category_id,
            org_id=org_id,
            name=name,
            slug=slug,
            description=description,
            icon=icon,
            default_hours=default_hours,
            color=color,
        )
