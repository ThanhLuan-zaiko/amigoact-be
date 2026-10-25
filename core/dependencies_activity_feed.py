"""Depends wiring for the cross-org activity feed (/me/activities).

Kept apart from dependencies_features.py, which sits at the 350-line cap.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import Depends

from activities.browse_interfaces import (
    MyRegistrationBrief,
    RegistrationBriefs,
    SeatCounter,
)
from activities.browse_service import ActivityBrowseService
from activities.mine_service import MyActivitiesService
from core.config import Settings, get_settings
from core.dependencies import get_access_control
from rbac.interfaces import AccessControl

if TYPE_CHECKING:  # pragma: no cover - type imports only
    from registrations.brief_service import RegistrationBriefService
    from registrations.interfaces import RegistrationStore


def get_my_activities_service(
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
) -> MyActivitiesService:
    """Read-only feed over the shared org, activity and media stores."""
    from activities.repository import CqlActivityStore
    from orgs.media_repository import CqlMediaRepository
    from orgs.repository import CqlOrgRepository

    return MyActivitiesService(
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        activities=CqlActivityStore(settings.scylla_keyspace),
        access=access,
        media=CqlMediaRepository(),
    )


class _RegistrationSeats(SeatCounter):
    """Seat port over the registrations store: one count per activity."""

    def __init__(self, store: RegistrationStore) -> None:
        self._store = store

    def registered_count(self, activity_id: UUID) -> int:
        return self._store.count_active(activity_id)


class _RegistrationBriefs(RegistrationBriefs):
    """Brief port over the registrations service, keyed by activity id."""

    def __init__(self, service: RegistrationBriefService) -> None:
        self._service = service

    def briefs_for(self, student_id: UUID) -> dict[UUID, MyRegistrationBrief]:
        return {
            brief.activity_id: MyRegistrationBrief(
                registration_id=brief.registration_id,
                status=brief.status,
                registered_at=brief.registered_at,
            )
            for brief in self._service.briefs_for(student_id)
        }


def get_activity_browse_service(
    settings: Settings = Depends(get_settings),
) -> ActivityBrowseService:
    """Public browse feed over activity feeds, orgs, media and seat counts."""
    from activities.browse_repository import CqlBrowseIndex
    from activities.category_repository import CqlCategoryStore
    from activities.media_repository import CqlActivityMediaStore
    from orgs.media_repository import CqlMediaRepository
    from orgs.repository import CqlOrgRepository
    from core.dependencies_registrations import get_registration_brief_service
    from registrations.repository import CqlRegistrationStore

    return ActivityBrowseService(
        index=CqlBrowseIndex(),
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        entries=CqlActivityMediaStore(),
        media=CqlMediaRepository(),
        seats=_RegistrationSeats(
            CqlRegistrationStore(settings.scylla_keyspace)
        ),
        briefs=_RegistrationBriefs(get_registration_brief_service()),
        categories=CqlCategoryStore(),
    )
