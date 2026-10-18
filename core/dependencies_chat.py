"""Depends wiring for the chat bounded context.

Split out of dependencies_workspace.py for the 350-line rule; chat
routers import their get_* dependencies straight from this module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Depends, Request

from core.config import Settings, get_settings
from core.dependencies import (
    get_access_control,
    get_media_store,
    get_notification_service,
    user_directory,
)

if TYPE_CHECKING:
    from chat.channel_roster import ChannelRosterService
    from chat.channel_service import ChannelService
    from chat.inbox_service import ChatInboxService
    from chat.media_service import ChatMediaService
    from chat.service import ChatService
    from chat.thread_service import ThreadService
    from notifications.service import NotificationService
    from rbac.interfaces import AccessControl


def get_chat_service(
    request: Request,
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
    notifications: NotificationService = Depends(get_notification_service),
) -> ChatService:
    """Build one ChatService per request over the org chat tables."""
    from activities.repository import CqlActivityStore
    from admin.repository import CqlModerationStore
    from chat.attachments import ChatAttachments
    from chat.channel_repository import CqlChannelStore
    from chat.claim_repository import CqlClaimStore
    from chat.composer import ChatComposer
    from chat.crypto import chat_cipher
    from chat.events import WsChatEvents
    from chat.repository import CqlChatStore
    from chat.service import ChatService
    from orgs.media_repository import CqlMediaRepository
    from orgs.member_repository import CqlMemberRepository
    from orgs.repository import CqlOrgRepository

    store = CqlChatStore(settings.scylla_keyspace)
    channels = CqlChannelStore(settings.scylla_keyspace)
    orgs = CqlOrgRepository(settings.scylla_keyspace)
    members = CqlMemberRepository()
    users = user_directory(settings)
    events = WsChatEvents(getattr(request.app.state, "ws_manager", None))
    activities = CqlActivityStore(settings.scylla_keyspace)
    cipher = chat_cipher(settings)
    attachments = ChatAttachments(
        CqlMediaRepository(),
        get_media_store(settings),
        CqlClaimStore(settings.scylla_keyspace),
        settings.media_max_image_mb * 1024 * 1024,
        settings.media_max_video_mb * 1024 * 1024,
        CqlModerationStore(),
    )
    return ChatService(
        chat=store,
        orgs=orgs,
        members=members,
        users=users,
        access=access,
        events=events,
        activities=activities,
        cipher=cipher,
        media=CqlMediaRepository(),
        channels=channels,
        attachments=attachments,
        composer=ChatComposer(
            chat=store,
            orgs=orgs,
            members=members,
            users=users,
            access=access,
            events=events,
            media=CqlMediaRepository(),
            attachments=attachments,
            activities=activities,
            cipher=cipher,
            notifications=notifications,
            channels=channels,
        ),
    )


def get_chat_media_service(
    request: Request,
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
) -> ChatMediaService:
    """Read-only shared-item tabs over the org_room_media index."""
    from activities.repository import CqlActivityStore
    from chat.channel_repository import CqlChannelStore
    from chat.crypto import chat_cipher
    from chat.media_service import ChatMediaService
    from chat.repository import CqlChatStore
    from orgs.media_repository import CqlMediaRepository
    from orgs.member_repository import CqlMemberRepository
    from orgs.repository import CqlOrgRepository

    return ChatMediaService(
        chat=CqlChatStore(settings.scylla_keyspace),
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        members=CqlMemberRepository(),
        users=user_directory(settings),
        access=access,
        activities=CqlActivityStore(settings.scylla_keyspace),
        cipher=chat_cipher(settings),
        media=CqlMediaRepository(),
        channels=CqlChannelStore(settings.scylla_keyspace),
    )


def get_channel_service(
    request: Request,
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
) -> ChannelService:
    """Build one ChannelService per request over the channel tables."""
    from activities.repository import CqlActivityStore
    from chat.channel_repository import CqlChannelStore
    from chat.channel_service import ChannelService
    from chat.events import WsChatEvents
    from orgs.media_repository import CqlMediaRepository
    from orgs.member_repository import CqlMemberRepository
    from orgs.repository import CqlOrgRepository

    return ChannelService(
        channels=CqlChannelStore(settings.scylla_keyspace),
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        members=CqlMemberRepository(),
        users=user_directory(settings),
        access=access,
        events=WsChatEvents(
            getattr(request.app.state, "ws_manager", None)
        ),
        media=CqlMediaRepository(),
        activities=CqlActivityStore(settings.scylla_keyspace),
    )


def get_channel_roster_service(
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
) -> ChannelRosterService:
    """Build one ChannelRosterService per request (restricted seats)."""
    from chat.channel_repository import CqlChannelStore
    from chat.channel_roster import ChannelRosterService
    from orgs.media_repository import CqlMediaRepository
    from orgs.member_repository import CqlMemberRepository
    from orgs.repository import CqlOrgRepository

    return ChannelRosterService(
        channels=CqlChannelStore(settings.scylla_keyspace),
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        members=CqlMemberRepository(),
        users=user_directory(settings),
        access=access,
        media=CqlMediaRepository(),
    )


def get_thread_service(
    request: Request,
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
) -> ThreadService:
    """Build one ThreadService per request over the channel tables."""
    from activities.repository import CqlActivityStore
    from chat.channel_repository import CqlChannelStore
    from chat.events import WsChatEvents
    from chat.thread_service import ThreadService
    from orgs.member_repository import CqlMemberRepository
    from orgs.repository import CqlOrgRepository

    return ThreadService(
        channels=CqlChannelStore(settings.scylla_keyspace),
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        members=CqlMemberRepository(),
        access=access,
        events=WsChatEvents(
            getattr(request.app.state, "ws_manager", None)
        ),
        activities=CqlActivityStore(settings.scylla_keyspace),
    )


def get_chat_inbox_service(
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
) -> ChatInboxService:
    """Read-only inbox summaries; membership-derived room refs."""
    from activities.repository import CqlActivityStore
    from chat.channel_repository import CqlChannelStore
    from chat.crypto import chat_cipher
    from chat.inbox_service import ChatInboxService
    from chat.repository import CqlChatStore
    from orgs.media_repository import CqlMediaRepository
    from orgs.member_repository import CqlMemberRepository
    from orgs.repository import CqlOrgRepository

    return ChatInboxService(
        chat=CqlChatStore(settings.scylla_keyspace),
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        members=CqlMemberRepository(),
        users=user_directory(settings),
        activities=CqlActivityStore(settings.scylla_keyspace),
        media=CqlMediaRepository(),
        cipher=chat_cipher(settings),
        channels=CqlChannelStore(settings.scylla_keyspace),
        access=access,
    )
