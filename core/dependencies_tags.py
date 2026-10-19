"""Depends wiring for the org-scoped tag services."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Depends, Request

from core.config import Settings, get_settings
from core.dependencies import get_access_control

if TYPE_CHECKING:  # pragma: no cover - type imports only
    from activities.tag_admin_service import TagAdminService
    from activities.tag_service import TagService
    from rbac.interfaces import AccessControl


def get_tag_service(
    settings: Settings = Depends(get_settings),
) -> TagService:
    """Org-scoped claims plus the public /tags directory search."""
    from activities.tag_repository import CqlOrgTagStore
    from activities.tag_service import TagService

    return TagService(CqlOrgTagStore(settings.scylla_keyspace))


def get_tag_admin_service(
    request: Request,
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
) -> TagAdminService:
    """Catalog curation behind tag:manage plus live tag.* hints."""
    from activities.events import WsActivityEvents
    from activities.tag_admin_service import TagAdminService
    from activities.tag_repository import CqlOrgTagStore
    from orgs.repository import CqlOrgRepository

    return TagAdminService(
        tags=CqlOrgTagStore(settings.scylla_keyspace),
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        access=access,
        events=WsActivityEvents(
            getattr(request.app.state, "ws_manager", None)
        ),
    )
