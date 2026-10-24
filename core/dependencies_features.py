"""Depends wiring for feature services built on the shared ports."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Depends, Request

from core.config import Settings, get_settings
from core.dependencies import get_access_control, get_media_store
from core.dependencies import get_notification_service, user_directory
from activities.user_tag_service import UserTagService
from core.dependencies_tags import get_user_tag_service

if TYPE_CHECKING:  # pragma: no cover - type imports only
    from activities.category_service import CategoryService
    from activities.delete_service import ActivityDeleteService
    from activities.detail_service import ActivityDetailService
    from activities.service import ActivityService
    from admin.service import AdminService
    from hours.rule_service import RuleService
    from hours.service import HourService
    from notifications.service import NotificationService
    from orgs.public_service import PublicOrgService
    from profiles.service import ProfileService
    from rbac.interfaces import AccessControl
    from reviews.service import ReviewService
    from stats.service import OrgStatsService
    from audit.service import AuditService


def get_admin_service(
    request: Request,
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
    notifications: NotificationService = Depends(get_notification_service),
) -> AdminService:
    """Build one AdminService per request over org plus platform tables."""
    from admin.repository import CqlModerationStore, CqlPlatformRoleStore
    from admin.service import AdminService
    from orgs.directory_events import WsOrgDirectoryEvents
    from orgs.media_repository import CqlMediaRepository
    from orgs.repository import CqlOrgRepository

    return AdminService(
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        platform_roles=CqlPlatformRoleStore(),
        users=user_directory(settings),
        notifications=notifications,
        access=access,
        admin_emails=settings.platform_admin_emails_set,
        directory_events=WsOrgDirectoryEvents(
            getattr(request.app.state, "ws_manager", None)
        ),
        moderation=CqlModerationStore(),
        media=CqlMediaRepository(),
    )


def get_public_org_service(
    settings: Settings = Depends(get_settings),
) -> PublicOrgService:
    """Build the read-only guest surface over org, media and activity rows."""
    from core.dependencies_workspace import get_public_post_service
    from orgs.activity_directory import CqlOrgActivityDirectory
    from orgs.media_repository import CqlMediaRepository
    from orgs.public_service import PublicOrgService
    from orgs.repository import CqlOrgRepository

    return PublicOrgService(
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        media=CqlMediaRepository(),
        activities=CqlOrgActivityDirectory(settings.scylla_keyspace),
        posts=get_public_post_service(settings),
        users=user_directory(settings),
    )


def get_activity_service(
    request: Request,
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
    user_tags: UserTagService = Depends(get_user_tag_service),
) -> ActivityService:
    """Build one ActivityService per request over activity feeds."""
    from activities.category_repository import CqlCategoryStore
    from activities.events import WsActivityEvents
    from activities.repository import CqlActivityStore
    from activities.service import ActivityService
    from activities.tag_repository import CqlOrgTagStore
    from activities.tag_service import TagService
    from orgs.repository import CqlOrgRepository

    return ActivityService(
        activities=CqlActivityStore(settings.scylla_keyspace),
        categories=CqlCategoryStore(),
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        access=access,
        events=WsActivityEvents(getattr(request.app.state, "ws_manager", None)),
        tags=TagService(CqlOrgTagStore(settings.scylla_keyspace)),
        user_tags=user_tags,
    )


def get_category_service(
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
) -> CategoryService:
    """Category catalog reads/writes share the activity stores."""
    from activities.category_repository import CqlCategoryStore
    from activities.category_service import CategoryService
    from orgs.repository import CqlOrgRepository

    return CategoryService(
        categories=CqlCategoryStore(),
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        access=access,
    )


def get_activity_delete_service(
    request: Request,
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
) -> ActivityDeleteService:
    """Trash lifecycle: soft delete, restore, hard purge + bytes."""
    from activities.delete_service import ActivityDeleteService
    from activities.events import WsActivityEvents
    from activities.repository import CqlActivityStore
    from core.dependencies_chat import build_activity_chat_link
    from core.dependencies_tags import get_user_tag_service
    from orgs.repository import CqlOrgRepository

    return ActivityDeleteService(
        activities=CqlActivityStore(settings.scylla_keyspace),
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        access=access,
        events=WsActivityEvents(getattr(request.app.state, "ws_manager", None)),
        store=get_media_store(settings),
        user_tags=get_user_tag_service(settings),
        chat=build_activity_chat_link(request, settings),
    )


# Tag services live in core/dependencies_tags.py (350-line split).


def get_activity_detail_service(
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
    notifications: NotificationService = Depends(get_notification_service),
) -> ActivityDetailService:
    """Build one ActivityDetailService per request over edge tables."""
    from activities.detail_service import ActivityDetailService
    from activities.links_repository import (
        CqlActivityLinkStore,
        CqlActivityStaffStore,
    )
    from activities.ops_repository import (
        CqlAnnouncementStore,
        CqlScheduleStore,
    )
    from activities.repository import CqlActivityStore
    from orgs.repository import CqlOrgRepository
    from profiles.repository import CqlProfileStore

    return ActivityDetailService(
        activities=CqlActivityStore(settings.scylla_keyspace),
        links=CqlActivityLinkStore(),
        staff=CqlActivityStaffStore(),
        schedules=CqlScheduleStore(),
        announcements=CqlAnnouncementStore(),
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        users=user_directory(settings),
        skills=CqlProfileStore(),
        access=access,
        notifications=notifications,
    )


def get_hour_service(
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
    notifications: NotificationService = Depends(get_notification_service),
) -> HourService:
    """Build one HourService per request over the ledger tables."""
    from activities.repository import CqlActivityStore
    from hours.repository import (
        CqlHourLedgerStore,
        CqlHourRuleStore,
        CqlLeaderboardStore,
    )
    from hours.service import HourService
    from orgs.repository import CqlOrgRepository

    return HourService(
        ledger=CqlHourLedgerStore(settings.scylla_keyspace),
        activities=CqlActivityStore(settings.scylla_keyspace),
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        access=access,
        notifications=notifications,
        leaderboard=CqlLeaderboardStore(),
        users=user_directory(settings),
        rules=CqlHourRuleStore(),
    )


def get_rule_service(
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
    notifications: NotificationService = Depends(get_notification_service),
) -> RuleService:
    """Build one RuleService per request over rules/adjustments."""
    from activities.repository import CqlActivityStore
    from hours.repository import (
        CqlAdjustmentStore,
        CqlHourLedgerStore,
        CqlHourRuleStore,
    )
    from hours.rule_service import RuleService
    from orgs.repository import CqlOrgRepository

    return RuleService(
        rules=CqlHourRuleStore(),
        adjustments=CqlAdjustmentStore(),
        ledger=CqlHourLedgerStore(settings.scylla_keyspace),
        activities=CqlActivityStore(settings.scylla_keyspace),
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        access=access,
        notifications=notifications,
    )


def get_review_service(
    settings: Settings = Depends(get_settings),
    notifications: NotificationService = Depends(get_notification_service),
) -> ReviewService:
    """Build one ReviewService per request over review feeds."""
    from activities.repository import CqlActivityStore
    from orgs.repository import CqlOrgRepository
    from registrations.repository import CqlRegistrationStore
    from reviews.repository import CqlReviewStore
    from reviews.service import ReviewService

    return ReviewService(
        reviews=CqlReviewStore(),
        activities=CqlActivityStore(settings.scylla_keyspace),
        registrations=CqlRegistrationStore(settings.scylla_keyspace),
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        users=user_directory(settings),
        notifications=notifications,
    )


def get_stats_service(
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
) -> OrgStatsService:
    """Build one OrgStatsService over existing feature stores."""
    from activities.repository import CqlActivityStore
    from certificates.repository import CqlCertificateStore
    from hours.repository import CqlHourLedgerStore
    from orgs.member_repository import CqlMemberRepository
    from orgs.repository import CqlOrgRepository
    from registrations.attendance_repository import (
        CqlAttendanceStore,
    )
    from stats.service import OrgStatsService

    return OrgStatsService(
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        members=CqlMemberRepository(),
        activities=CqlActivityStore(settings.scylla_keyspace),
        hours=CqlHourLedgerStore(settings.scylla_keyspace),
        attendance=CqlAttendanceStore(settings.scylla_keyspace),
        certificates=CqlCertificateStore(settings.scylla_keyspace),
        access=access,
    )


def get_audit_service(
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
) -> AuditService:
    """Build one AuditService over the rbac audit partition."""
    from audit.service import AuditService
    from orgs.member_repository import CqlMemberRepository
    from orgs.repository import CqlOrgRepository
    from rbac.repository import CqlAuditReader

    return AuditService(
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        members=CqlMemberRepository(),
        access=access,
        reader=CqlAuditReader(),
        users=user_directory(settings),
    )


# Certificate providers (issue/revoke/file/templates) live in
# core/dependencies_certificates.py (split for the 350-line rule).


def get_profile_service(
    settings: Settings = Depends(get_settings),
) -> ProfileService:
    """Build one ProfileService per request over profile/skill tables."""
    from auth.repository import CqlUserRepository
    from orgs.media_repository import CqlMediaRepository
    from profiles.repository import CqlProfileStore
    from profiles.service import ProfileService

    return ProfileService(
        profiles=CqlProfileStore(),
        users=CqlUserRepository(settings.scylla_keyspace),
        media=CqlMediaRepository(),
        store=get_media_store(settings),
        max_image_bytes=settings.media_max_image_mb * 1024 * 1024,
    )


# Member-workspace dependencies (posts/comments/chat) live in
# core/dependencies_workspace.py (split for the 350-line rule).


def get_projection_service(
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
) -> "StatsProjectionService":
    """Build one StatsProjectionService over feeds + rollup tables."""
    from activities.repository import CqlActivityStore
    from certificates.repository import CqlCertificateStore
    from hours.repository import CqlHourLedgerStore
    from orgs.repository import CqlOrgRepository
    from registrations.attendance_repository import CqlAttendanceStore
    from registrations.repository import CqlRegistrationStore
    from stats.projection_service import StatsProjectionService
    from stats.repository import CqlDailyStatsStore, CqlMonthlyStatsStore

    return StatsProjectionService(
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        activities=CqlActivityStore(settings.scylla_keyspace),
        registrations=CqlRegistrationStore(settings.scylla_keyspace),
        attendance=CqlAttendanceStore(settings.scylla_keyspace),
        hours=CqlHourLedgerStore(settings.scylla_keyspace),
        certificates=CqlCertificateStore(settings.scylla_keyspace),
        daily=CqlDailyStatsStore(),
        monthly=CqlMonthlyStatsStore(),
        access=access,
    )
