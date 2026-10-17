"""Depends wiring for the realtime channel (tickets, sockets, ACL)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Depends, WebSocket

from core.config import Settings, get_settings
from core.dependencies import get_access_control, user_directory
from core.realtime import ConnectionManager

if TYPE_CHECKING:
    from rbac.interfaces import AccessControl
    from realtime.service import RealtimeService


def get_connection_manager(websocket: WebSocket) -> ConnectionManager:
    """App-scoped ephemeral socket registry initialized in lifespan."""
    manager = getattr(websocket.app.state, "ws_manager", None)
    if manager is None:
        raise RuntimeError("WebSocket manager is not initialized.")
    return manager


def get_realtime_service(
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
) -> RealtimeService:
    """Build one RealtimeService per ticket/socket request."""
    from activities.repository import CqlActivityStore
    from auth.repository import CqlUserRepository
    from chat.channel_repository import CqlChannelStore
    from chat.events import WsChatEvents
    from chat.repository import CqlChatStore
    from chat.service import ChatService
    from orgs.member_repository import CqlMemberRepository
    from orgs.repository import CqlOrgRepository
    from realtime.access import (
        AuthUserLookup,
        MemberPresenceDirectory,
        OrgAttendanceAccess,
        OrgChannelMembership,
    )
    from realtime.repository import CqlWsTicketStore
    from realtime.service import RealtimeService

    orgs = CqlOrgRepository(settings.scylla_keyspace)
    members = CqlMemberRepository()
    activities = CqlActivityStore(settings.scylla_keyspace)
    return RealtimeService(
        tickets=CqlWsTicketStore(settings.scylla_keyspace),
        membership=OrgChannelMembership(orgs),
        attendance=OrgAttendanceAccess(activities, orgs, access),
        ticket_ttl_seconds=settings.ws_ticket_ttl_seconds,
        users=AuthUserLookup(CqlUserRepository(settings.scylla_keyspace)),
        presence=MemberPresenceDirectory(members),
        # The chat service doubles as the room ACL port so subscribe
        # checks reuse the exact room-resolution rules.
        chat_rooms=ChatService(
            chat=CqlChatStore(settings.scylla_keyspace),
            orgs=orgs,
            members=members,
            users=user_directory(settings),
            access=access,
            events=WsChatEvents(None),
            activities=activities,
            channels=CqlChannelStore(settings.scylla_keyspace),
        ),
    )
