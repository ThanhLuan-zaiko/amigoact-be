"""Depends wiring for feature services built on the shared ports."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Depends, Request

from core.config import Settings, get_settings
from core.dependencies import get_access_control, get_media_store
from core.dependencies import get_notification_service, user_directory

if TYPE_CHECKING:
    from uuid import UUID

    from activities.detail_service import ActivityDetailService
    from activities.service import ActivityService
    from admin.service import AdminService
    from certificates.service import CertificateService
    from core.realtime import ConnectionManager
    from hours.service import HourService
    from notifications.service import NotificationService
    from profiles.service import ProfileService
    from rbac.interfaces import AccessControl
    from registrations.attendance_service import AttendanceService
    from registrations.service import RegistrationService
    from reviews.service import ReviewService
    from stats.service import OrgStatsService
    from audit.service import AuditService


def get_admin_service(
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
    notifications: NotificationService = Depends(get_notification_service),
) -> AdminService:
    """Build one AdminService per request over org plus platform tables."""
    from admin.repository import CqlPlatformRoleStore
    from admin.service import AdminService
    from orgs.repository import CqlOrgRepository

    return AdminService(
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        platform_roles=CqlPlatformRoleStore(),
        users=user_directory(settings),
        notifications=notifications,
        access=access,
        admin_emails=settings.platform_admin_emails_set,
    )


def get_activity_service(
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
) -> ActivityService:
    """Build one ActivityService per request over activity feeds."""
    from activities.repository import CqlActivityStore, CqlCategoryStore
    from activities.service import ActivityService
    from orgs.repository import CqlOrgRepository

    return ActivityService(
        activities=CqlActivityStore(settings.scylla_keyspace),
        categories=CqlCategoryStore(),
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        access=access,
    )


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


def get_registration_service(
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
    notifications: NotificationService = Depends(get_notification_service),
) -> RegistrationService:
    """Build one RegistrationService per request over reg tables."""
    from activities.repository import CqlActivityStore
    from orgs.repository import CqlOrgRepository
    from registrations.attendance_repository import CqlAttendanceStore
    from registrations.repository import CqlRegistrationStore
    from registrations.service import RegistrationService

    return RegistrationService(
        registrations=CqlRegistrationStore(settings.scylla_keyspace),
        attendance=CqlAttendanceStore(settings.scylla_keyspace),
        activities=CqlActivityStore(settings.scylla_keyspace),
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        users=user_directory(settings),
        access=access,
        notifications=notifications,
    )


def get_attendance_service(
    request: Request,
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
    notifications: NotificationService = Depends(get_notification_service),
) -> AttendanceService:
    """Build one AttendanceService per request over attendance tables."""
    from activities.repository import CqlActivityStore
    from hours.repository import CqlHourLedgerStore
    from hours.service import HourService
    from orgs.repository import CqlOrgRepository
    from registrations.attendance_repository import CqlAttendanceStore
    from registrations.attendance_service import AttendanceService
    from registrations.interfaces import AttendanceEvents
    from registrations.repository import CqlRegistrationStore

    class _WsAttendanceEvents(AttendanceEvents):
        """Fan check-in/out events onto the socket registry (best-effort)."""

        def __init__(self, manager: ConnectionManager | None) -> None:
            self._manager = manager

        def attendance_changed(
            self,
            activity_id: UUID,
            action: str,
            record_id: UUID,
            student_id: UUID,
            actor_id: UUID,
        ) -> None:
            if self._manager is not None:
                self._manager.schedule_publish(
                    f"attendance:{activity_id}",
                    {
                        "action": action,
                        "record_id": str(record_id),
                        "student_id": str(student_id),
                        "actor_id": str(actor_id),
                    },
                )

    return AttendanceService(
        registrations=CqlRegistrationStore(settings.scylla_keyspace),
        attendance=CqlAttendanceStore(settings.scylla_keyspace),
        activities=CqlActivityStore(settings.scylla_keyspace),
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        users=user_directory(settings),
        access=access,
        notifications=notifications,
        events=_WsAttendanceEvents(
            getattr(request.app.state, "ws_manager", None)
        ),
        hours=HourService(
            ledger=CqlHourLedgerStore(settings.scylla_keyspace),
            activities=CqlActivityStore(settings.scylla_keyspace),
            orgs=CqlOrgRepository(settings.scylla_keyspace),
            access=access,
            notifications=notifications,
        ),
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


def get_certificate_service(
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
    notifications: NotificationService = Depends(get_notification_service),
) -> CertificateService:
    """Build one CertificateService per request over cert tables."""
    from activities.repository import CqlActivityStore
    from certificates.repository import CqlCertificateStore
    from certificates.service import CertificateService
    from orgs.repository import CqlOrgRepository
    from registrations.repository import CqlRegistrationStore

    return CertificateService(
        certificates=CqlCertificateStore(settings.scylla_keyspace),
        registrations=CqlRegistrationStore(settings.scylla_keyspace),
        activities=CqlActivityStore(settings.scylla_keyspace),
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        users=user_directory(settings),
        access=access,
        notifications=notifications,
    )


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
