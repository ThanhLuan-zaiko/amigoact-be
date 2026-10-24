"""Depends wiring for the cross-org activity feed (/me/activities).

Kept apart from dependencies_features.py, which sits at the 350-line cap.
"""

from __future__ import annotations

from fastapi import Depends

from activities.mine_service import MyActivitiesService
from core.config import Settings, get_settings
from core.dependencies import get_access_control
from rbac.interfaces import AccessControl


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
