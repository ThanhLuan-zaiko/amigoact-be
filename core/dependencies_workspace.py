"""Depends wiring for the member-workspace features (posts + chat).

Split out of dependencies_features.py for the 350-line rule; routers
import the get_* dependencies straight from this module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Depends, Request

from core.config import Settings, get_settings
from core.dependencies import (
    get_access_control,
    get_notification_service,
    user_directory,
)

if TYPE_CHECKING:
    from chat.service import ChatService
    from notifications.service import NotificationService
    from posts.comments_service import CommentService
    from posts.service import PostService
    from rbac.interfaces import AccessControl


def get_post_service(
    request: Request,
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
    notifications: NotificationService = Depends(get_notification_service),
) -> PostService:
    """Build one PostService per request over the org board tables."""
    from orgs.media_repository import CqlMediaRepository
    from orgs.member_repository import CqlMemberRepository
    from orgs.repository import CqlOrgRepository
    from posts.events import WsPostEvents
    from posts.repository import CqlCommentStore, CqlPostStore
    from posts.service import PostService

    return PostService(
        posts=CqlPostStore(settings.scylla_keyspace),
        comments=CqlCommentStore(settings.scylla_keyspace),
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        members=CqlMemberRepository(),
        users=user_directory(settings),
        media=CqlMediaRepository(),
        access=access,
        events=WsPostEvents(getattr(request.app.state, "ws_manager", None)),
        notifications=notifications,
    )


def get_comment_service(
    request: Request,
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
) -> CommentService:
    """Build one CommentService per request over the comment tables."""
    from orgs.member_repository import CqlMemberRepository
    from orgs.repository import CqlOrgRepository
    from posts.comments_service import CommentService
    from posts.events import WsPostEvents
    from posts.repository import CqlCommentStore, CqlPostStore

    return CommentService(
        posts=CqlPostStore(settings.scylla_keyspace),
        comments=CqlCommentStore(settings.scylla_keyspace),
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        members=CqlMemberRepository(),
        users=user_directory(settings),
        access=access,
        events=WsPostEvents(getattr(request.app.state, "ws_manager", None)),
    )


def get_chat_service(
    request: Request,
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
) -> ChatService:
    """Build one ChatService per request over the org chat tables."""
    from activities.repository import CqlActivityStore
    from chat.events import WsChatEvents
    from chat.repository import CqlChatStore
    from chat.service import ChatService
    from orgs.member_repository import CqlMemberRepository
    from orgs.repository import CqlOrgRepository

    return ChatService(
        chat=CqlChatStore(settings.scylla_keyspace),
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        members=CqlMemberRepository(),
        users=user_directory(settings),
        access=access,
        events=WsChatEvents(getattr(request.app.state, "ws_manager", None)),
        activities=CqlActivityStore(settings.scylla_keyspace),
    )
