"""Depends wiring for role seniority and the org member baseline."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Depends, Request

from core.config import Settings, get_settings
from core.dependencies import get_access_control

if TYPE_CHECKING:  # pragma: no cover - type imports only
    from rbac.defaults_service import MemberDefaultsService
    from rbac.interfaces import AccessControl
    from rbac.order_service import RoleOrderService


def get_role_order_service(
    request: Request,
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
) -> RoleOrderService:
    """Build one RoleOrderService per request for role seniority."""
    from orgs.member_events import WsMemberEvents
    from orgs.repository import CqlOrgRepository
    from rbac.order_service import RoleOrderService
    from rbac.repository import CqlRoleRepository

    return RoleOrderService(
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        roles=CqlRoleRepository(),
        access=access,
        events=WsMemberEvents(
            getattr(request.app.state, "ws_manager", None)
        ),
    )


def get_defaults_service(
    request: Request,
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
) -> MemberDefaultsService:
    """Build one MemberDefaultsService per request for the baseline."""
    from orgs.member_events import WsMemberEvents
    from orgs.member_repository import CqlMemberRepository
    from orgs.repository import CqlOrgRepository
    from rbac.defaults_service import MemberDefaultsService
    from rbac.repository import CqlMemberDefaultsRepository

    return MemberDefaultsService(
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        members=CqlMemberRepository(),
        defaults=CqlMemberDefaultsRepository(),
        access=access,
        events=WsMemberEvents(
            getattr(request.app.state, "ws_manager", None)
        ),
    )
