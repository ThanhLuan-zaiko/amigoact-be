"""Depends wiring for the registrations aggregate (apply + attendance)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Depends, Request

from core.config import Settings, get_settings
from core.dependencies import get_access_control, get_notification_service
from core.dependencies import user_directory

if TYPE_CHECKING:
    from uuid import UUID

    from core.realtime import ConnectionManager
    from notifications.service import NotificationService
    from rbac.interfaces import AccessControl
    from registrations.appeal_service import AppealService
    from registrations.attendance_service import AttendanceService
    from registrations.service import RegistrationService
    from registrations.session_service import SessionService


def get_registration_service(
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
    notifications: NotificationService = Depends(get_notification_service),
) -> RegistrationService:
    """Build one RegistrationService per request over reg tables."""
    from activities.links_repository import CqlRegistrationFormStore
    from activities.ops_repository import CqlSlotStore
    from activities.repository import CqlActivityStore
    from orgs.repository import CqlOrgRepository
    from registrations.attendance_repository import CqlAttendanceStore
    from registrations.repository import CqlRegistrationStore
    from registrations.service import RegistrationService

    return RegistrationService(
        registrations=CqlRegistrationStore(settings.scylla_keyspace),
        forms=CqlRegistrationFormStore(),
        slots=CqlSlotStore(),
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


def get_session_service(
    request: Request,
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
    notifications: NotificationService = Depends(get_notification_service),
) -> SessionService:
    """Build one SessionService over sessions/QR/scan-log tables."""
    from activities.ops_repository import CqlScheduleStore, CqlSlotStore
    from activities.repository import CqlActivityStore
    from orgs.repository import CqlOrgRepository
    from registrations.attendance_repository import CqlAttendanceStore
    from registrations.interfaces import AttendanceEvents
    from registrations.repository import CqlRegistrationStore
    from registrations.session_repository import (
        CqlQrStore,
        CqlScanLogStore,
        CqlSessionStore,
        CqlSummaryStore,
    )
    from registrations.session_service import SessionService

    class _WsAttendanceEvents(AttendanceEvents):
        """Fan scan events onto the socket registry (best-effort)."""

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

    return SessionService(
        registrations=CqlRegistrationStore(settings.scylla_keyspace),
        attendance=CqlAttendanceStore(settings.scylla_keyspace),
        activities=CqlActivityStore(settings.scylla_keyspace),
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        users=user_directory(settings),
        access=access,
        notifications=notifications,
        slots=CqlSlotStore(),
        events=_WsAttendanceEvents(
            getattr(request.app.state, "ws_manager", None)
        ),
        sessions=CqlSessionStore(),
        qrcodes=CqlQrStore(),
        scanlogs=CqlScanLogStore(),
        schedules=CqlScheduleStore(),
        summaries=CqlSummaryStore(),
    )


def get_appeal_service(
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
    notifications: NotificationService = Depends(get_notification_service),
) -> AppealService:
    """Build one AppealService over the appeals partition."""
    from activities.repository import CqlActivityStore
    from orgs.repository import CqlOrgRepository
    from registrations.appeal_service import AppealService
    from registrations.attendance_repository import CqlAttendanceStore
    from registrations.repository import CqlRegistrationStore
    from registrations.session_repository import CqlAppealStore

    return AppealService(
        registrations=CqlRegistrationStore(settings.scylla_keyspace),
        attendance=CqlAttendanceStore(settings.scylla_keyspace),
        activities=CqlActivityStore(settings.scylla_keyspace),
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        users=user_directory(settings),
        access=access,
        notifications=notifications,
        appeals=CqlAppealStore(),
    )
