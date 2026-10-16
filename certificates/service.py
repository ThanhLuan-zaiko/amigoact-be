"""Certificate business rules: issue for attended registrations, revoke,
public serial verification (no FastAPI, no CQL)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from activities.interfaces import ActivityStore
from certificates.interfaces import CertificateStore, TemplateStore
from certificates.model import Certificate
from core.exceptions import (
    CertificateExistsError,
    ForbiddenError,
    InvalidRegistrationStateError,
    NotFoundError,
)
from core.ids import uuid7
from core.security import utcnow
from notifications.interfaces import NotificationPort
from orgs.interfaces import OrgRepository, UserDirectory
from rbac.interfaces import AccessControl
from registrations.interfaces import RegistrationStore

SERIAL_ATTEMPTS = 3


@dataclass(frozen=True)
class VerifyResult:
    """Public serial-check payload."""

    serial_no: str
    status: str
    activity_title: str
    student_name: str
    issued_at: object


@dataclass(frozen=True)
class MyCertificate:
    """Student wall row with the activity title resolved."""

    certificate: Certificate
    activity_title: str


class CertificateService:
    """Issue/revoke/verify around the (activity, student) aggregate."""

    def __init__(
        self,
        certificates: CertificateStore,
        registrations: RegistrationStore,
        activities: ActivityStore,
        orgs: OrgRepository,
        users: UserDirectory,
        access: AccessControl,
        notifications: NotificationPort | None = None,
        templates: TemplateStore | None = None,
    ) -> None:
        self._certificates = certificates
        self._registrations = registrations
        self._activities = activities
        self._orgs = orgs
        self._users = users
        self._access = access
        self._notifications = notifications
        self._templates = templates

    def _require_manager(self, org_id: UUID, actor: UUID, action: str) -> None:
        org = self._orgs.get_by_id(org_id)
        if org is None or getattr(org, "deleted_at", None) is not None:
            raise NotFoundError("Organization not found.")
        if (
            getattr(org, "owner_id", None) != actor
            and not self._access.has_permission(
                org_id, actor, "activity:manage"
            )
        ):
            self._access.record(
                org_id, actor, action, "certificate", None, "denied"
            )
            raise ForbiddenError("Only org managers can do this.")

    def _notify(self, user_id: UUID, title: str, body: str = "") -> None:
        if self._notifications is None:
            return
        try:
            self._notifications.notify(
                user_id, "certificate", title, body, None
            )
        except Exception:  # noqa: BLE001 - notifications are best-effort
            pass

    @staticmethod
    def _serial(now) -> str:  # noqa: ANN001, ANN205
        return f"AMG-{now.year}-{uuid7().hex[:8].upper()}"

    def issue(
        self,
        activity_id: UUID,
        student_id: UUID,
        staff_id: UUID,
        template_id: UUID | None = None,
    ) -> Certificate:
        """One certificate per attended registration, once only."""
        activity = self._activities.get(activity_id)
        if activity is None:
            raise NotFoundError("Activity not found.")
        self._require_manager(
            activity.org_id, staff_id, "certificate.issue"
        )
        if template_id is not None:
            if self._templates is None:
                raise NotFoundError("Template not found.")
            tpl = self._templates.get(template_id)
            if (
                tpl is None
                or tpl.org_id != activity.org_id
                or tpl.is_active is not True
            ):
                raise NotFoundError("Template not found.")
        existing = self._certificates.get(activity_id, student_id)
        if existing is not None and existing.status == "issued":
            raise CertificateExistsError(
                "A certificate was already issued for this student."
            )
        guard = self._registrations.get_for_student(
            activity_id, student_id, UUID(int=0)
        )
        if guard is None or guard.status != "attended":
            raise InvalidRegistrationStateError(
                "Only attended registrations earn certificates."
            )
        now = utcnow()
        last_error: CertificateExistsError | None = None
        for _ in range(SERIAL_ATTEMPTS):
            try:
                row = self._certificates.issue(
                    uuid7(), activity_id, student_id,
                    guard.registration_id, self._serial(now),
                    staff_id, now, template_id,
                )
            except CertificateExistsError as exc:  # serial collision
                last_error = exc
                continue
            self._access.record(
                activity.org_id, staff_id, "certificate.issue",
                "certificate", row.certificate_id, "allowed",
            )
            self._notify(
                student_id,
                "Ch\u1ee9ng nh\u1eadn m\u1edbi",
                f"B\u1ea1n nh\u1eadn \u0111\u01b0\u1ee3c ch\u1ee9ng nh\u1eadn t\u1eeb {activity.title}.",
            )
            return row
        assert last_error is not None
        raise last_error

    def revoke(
        self,
        activity_id: UUID,
        student_id: UUID,
        staff_id: UUID,
        reason: str | None,
    ) -> Certificate:
        """Revoke keeps the row but flips status across every feed."""
        activity = self._activities.get(activity_id)
        if activity is None:
            raise NotFoundError("Activity not found.")
        self._require_manager(
            activity.org_id, staff_id, "certificate.revoke"
        )
        row = self._certificates.get(activity_id, student_id)
        if row is None or row.status != "issued":
            raise NotFoundError("Certificate not found.")
        now = utcnow()
        updated = self._certificates.revoke(
            row, reason, staff_id, now
        )
        self._access.record(
            activity.org_id, staff_id, "certificate.revoke",
            "certificate", row.certificate_id, "allowed",
        )
        return updated

    def for_activity(
        self, activity_id: UUID, staff_id: UUID
    ) -> list[Certificate]:
        """Manager list of every certificate issued for one activity."""
        activity = self._activities.get(activity_id)
        if activity is None:
            raise NotFoundError("Activity not found.")
        self._require_manager(
            activity.org_id, staff_id, "certificate.list"
        )
        return self._certificates.list_by_activity(activity_id)

    def verify(self, serial_no: str) -> VerifyResult:
        """Public endpoint: anyone resolves a printed serial."""
        index = self._certificates.get_by_serial(serial_no.strip())
        if index is None:
            raise NotFoundError("Certificate serial not found.")
        activity = self._activities.get(index.activity_id)
        brief = self._users.get_brief(index.student_id)
        issued = None
        row = (
            self._certificates.get(index.activity_id, index.student_id)
            if index.certificate_id is not None
            else None
        )
        if row is not None:
            issued = row.issued_at
        return VerifyResult(
            serial_no=serial_no.strip(),
            status=index.status or "issued",
            activity_title=(
                activity.title if activity is not None else ""
            ),
            student_name=(
                brief.full_name if brief is not None else "Ng\u01b0\u1eddi d\u00f9ng"
            ),
            issued_at=issued,
        )

    def mine(self, student_id: UUID) -> list[MyCertificate]:
        """Student wall with activity titles attached."""
        out: list[MyCertificate] = []
        for row in self._certificates.list_by_student(student_id):
            activity = self._activities.get(row.activity_id)
            out.append(
                MyCertificate(
                    certificate=row,
                    activity_title=(
                        activity.title if activity is not None else ""
                    ),
                )
            )
        return out
