"""Depends wiring for the member-workspace features (posts + activities).

Split out of dependencies_features.py for the 350-line rule; routers
import the get_* dependencies straight from this module. Chat wiring
lives in dependencies_chat.py.
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
    from activities.form_service import FormService
    from activities.slot_service import SlotService
    from notifications.service import NotificationService
    from posts.comments_service import CommentService
    from posts.lifecycle_service import PostLifecycleService
    from posts.public_service import PublicPostService
    from posts.service import PostService
    from posts.uploads import PostUploads
    from rbac.interfaces import AccessControl


def get_public_post_service(
    settings: Settings = Depends(get_settings),
) -> PublicPostService:
    """Guest announcement reads over the same posts tables (no auth)."""
    from orgs.media_repository import CqlMediaRepository
    from orgs.repository import CqlOrgRepository
    from posts.public_service import PublicPostService
    from posts.repository import CqlCommentStore, CqlPostStore

    return PublicPostService(
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        posts=CqlPostStore(settings.scylla_keyspace),
        comments=CqlCommentStore(settings.scylla_keyspace),
        users=user_directory(settings),
        media=CqlMediaRepository(),
    )


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
    from posts.events import WsAnnouncementFeedEvents, WsPostEvents
    from posts.repository import CqlCommentStore, CqlPostStore
    from posts.service import PostService

    manager = getattr(request.app.state, "ws_manager", None)
    return PostService(
        posts=CqlPostStore(settings.scylla_keyspace),
        comments=CqlCommentStore(settings.scylla_keyspace),
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        members=CqlMemberRepository(),
        users=user_directory(settings),
        media=CqlMediaRepository(),
        access=access,
        events=WsPostEvents(manager),
        notifications=notifications,
        announcements=WsAnnouncementFeedEvents(manager),
    )


def get_post_upload_service(
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
) -> PostUploads:
    """Build one PostUploads per request for board-editor media."""
    from admin.repository import CqlModerationStore
    from orgs.media_repository import CqlMediaRepository
    from orgs.member_repository import CqlMemberRepository
    from orgs.repository import CqlOrgRepository
    from posts.uploads import PostUploads

    return PostUploads(
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        members=CqlMemberRepository(),
        access=access,
        media=CqlMediaRepository(),
        store=get_media_store(settings),
        max_image_bytes=settings.media_max_image_mb * 1024 * 1024,
        max_video_bytes=settings.media_max_video_mb * 1024 * 1024,
        moderation=CqlModerationStore(),
    )


def get_post_lifecycle_service(
    request: Request,
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
    notifications: NotificationService = Depends(get_notification_service),
) -> PostLifecycleService:
    """Drafts, publish moves and the trash bin (hard delete purges files)."""
    from core.media import LocalMediaStore
    from orgs.media_repository import CqlMediaRepository
    from orgs.member_repository import CqlMemberRepository
    from orgs.repository import CqlOrgRepository
    from posts.events import WsAnnouncementFeedEvents, WsPostEvents
    from posts.lifecycle_service import PostLifecycleService
    from posts.repository import CqlCommentStore, CqlPostStore

    manager = getattr(request.app.state, "ws_manager", None)
    return PostLifecycleService(
        posts=CqlPostStore(settings.scylla_keyspace),
        comments=CqlCommentStore(settings.scylla_keyspace),
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        members=CqlMemberRepository(),
        users=user_directory(settings),
        media=CqlMediaRepository(),
        access=access,
        events=WsPostEvents(manager),
        notifications=notifications,
        files=LocalMediaStore(settings.media_root),
        announcements=WsAnnouncementFeedEvents(manager),
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
    from posts.events import WsAnnouncementFeedEvents, WsPostEvents
    from posts.repository import CqlCommentStore, CqlPostStore

    manager = getattr(request.app.state, "ws_manager", None)
    return CommentService(
        posts=CqlPostStore(settings.scylla_keyspace),
        comments=CqlCommentStore(settings.scylla_keyspace),
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        members=CqlMemberRepository(),
        users=user_directory(settings),
        access=access,
        events=WsPostEvents(manager),
        announcements=WsAnnouncementFeedEvents(manager),
    )


def get_form_service(
    request: Request,
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
) -> "FormService":
    """Build one FormService over the registration_forms table."""
    from activities.events import WsActivityEvents
    from activities.form_service import FormService
    from activities.slot_service import SlotService
    from activities.links_repository import CqlRegistrationFormStore
    from activities.repository import CqlActivityStore
    from orgs.repository import CqlOrgRepository

    return FormService(
        activities=CqlActivityStore(settings.scylla_keyspace),
        forms=CqlRegistrationFormStore(),
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        access=access,
        events=WsActivityEvents(
            getattr(request.app.state, "ws_manager", None)
        ),
    )


def get_slot_service(
    request: Request,
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
) -> "SlotService":
    """Build one SlotService over activity_slots + registrations."""
    from activities.events import WsActivityEvents
    from activities.ops_repository import CqlScheduleStore, CqlSlotStore
    from activities.repository import CqlActivityStore
    from activities.slot_service import SlotService
    from orgs.repository import CqlOrgRepository
    from registrations.repository import CqlRegistrationStore

    return SlotService(
        activities=CqlActivityStore(settings.scylla_keyspace),
        schedules=CqlScheduleStore(),
        slots=CqlSlotStore(),
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        access=access,
        registrations=CqlRegistrationStore(settings.scylla_keyspace),
        events=WsActivityEvents(
            getattr(request.app.state, "ws_manager", None)
        ),
    )


def get_activity_media_service(
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
) -> "ActivityMediaService":
    """Build one ActivityMediaService over activity_media + media_assets."""
    from activities.media_repository import CqlActivityMediaStore
    from activities.media_service import ActivityMediaService
    from activities.repository import CqlActivityStore
    from admin.repository import CqlModerationStore
    from core.dependencies import get_media_store
    from orgs.media_repository import CqlMediaRepository
    from orgs.repository import CqlOrgRepository

    return ActivityMediaService(
        activities=CqlActivityStore(settings.scylla_keyspace),
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        media=CqlMediaRepository(),
        entries=CqlActivityMediaStore(),
        store=get_media_store(settings),
        access=access,
        max_image_bytes=settings.media_max_image_mb * 1024 * 1024,
        max_video_bytes=settings.media_max_video_mb * 1024 * 1024,
        moderation=CqlModerationStore(),
    )


def get_structure_service(
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
) -> "StructureService":
    """Build one StructureService over campuses + departments."""
    from orgs.repository import CqlOrgRepository
    from orgs.structure_repository import CqlOrgTypeStore, CqlStructureStore
    from orgs.structure_service import StructureService
    from profiles.repository import CqlProfileStore

    return StructureService(
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        structure=CqlStructureStore(),
        access=access,
        profiles=CqlProfileStore(),
        types=CqlOrgTypeStore(),
    )
