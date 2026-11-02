"""Issuing, revoking, and verifying certificates."""

import secrets
import uuid
from decimal import Decimal

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.activities.rules import ATTENDED, COMPLETED
from src.attendance.rules import CODE_ALPHABET
from src.auth.errors import api_error
from src.certificates.schemas import (
    ActivityCertificates,
    CertificateEntry,
    IssueResult,
    MyCertificate,
    VerifiedCertificate,
)
from src.models.activities import Activity, Registration
from src.models.attendance import VolunteerHourLedger
from src.models.auth import User
from src.models.certificates import Certificate, CertificateRevocation
from src.models.organizations import Organization
from src.notifications.events import activity_data, notify

ISSUED = "issued"
REVOKED = "revoked"
SERIAL_GROUPS = 3
SERIAL_GROUP_LENGTH = 4
SERIAL_ATTEMPTS = 5


def new_serial() -> str:
    """Random and unrelated to any ID, so serials cannot be listed or guessed."""
    groups = (
        "".join(secrets.choice(CODE_ALPHABET) for _ in range(SERIAL_GROUP_LENGTH))
        for _ in range(SERIAL_GROUPS)
    )
    return "AMG-" + "-".join(groups)


def _hours(db: Session, activity_id: uuid.UUID, student_id: uuid.UUID) -> float:
    total = db.scalar(
        select(func.sum(VolunteerHourLedger.hours)).where(
            VolunteerHourLedger.activity_id == activity_id,
            VolunteerHourLedger.student_id == student_id,
            VolunteerHourLedger.status == "approved",
        )
    )
    return float(total or Decimal(0))


def _attendees_without_certificate(
    db: Session, activity_id: uuid.UUID
) -> dict[uuid.UUID, uuid.UUID]:
    """Map each such person to one registration. Several shifts earn one certificate."""
    has_certificate = select(Certificate.student_id).where(
        Certificate.activity_id == activity_id
    )
    rows = db.execute(
        select(Registration.student_id, Registration.registration_id)
        .where(
            Registration.activity_id == activity_id,
            Registration.status == ATTENDED,
            Registration.student_id.not_in(has_certificate),
        )
        .order_by(Registration.registration_id)
    ).all()
    found: dict[uuid.UUID, uuid.UUID] = {}
    for student_id, registration_id in rows:
        found.setdefault(student_id, registration_id)
    return found


def issue_certificates(
    db: Session,
    activity: Activity,
    actor_id: uuid.UUID,
    template_id: uuid.UUID | None = None,
) -> IssueResult:
    """Issue to everyone who attended and has none. Safe to run again after appeals."""
    if activity.status != COMPLETED:
        raise api_error(status.HTTP_409_CONFLICT, "activity_not_completed")
    attendees = _attendees_without_certificate(db, activity.id)
    data = activity_data(db, activity.id)
    for student_id, registration_id in attendees.items():
        certificate = Certificate(
            certificate_id=uuid.uuid7(),
            activity_id=activity.id,
            student_id=student_id,
            registration_id=registration_id,
            issued_by=actor_id,
            serial_no=_unused_serial(db),
            template_id=template_id,
            status=ISSUED,
        )
        db.add(certificate)
        notify(
            db,
            student_id,
            "certificate_issued",
            {**data, "serial_no": certificate.serial_no},
        )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise api_error(status.HTTP_409_CONFLICT, "conflict") from exc
    return IssueResult(issued=len(attendees))


def _unused_serial(db: Session) -> str:
    for _ in range(SERIAL_ATTEMPTS):
        serial = new_serial()
        taken = db.scalar(
            select(Certificate.certificate_id).where(Certificate.serial_no == serial)
        )
        if taken is None:
            return serial
    raise api_error(status.HTTP_409_CONFLICT, "conflict")


def load_certificate(db: Session, certificate_id: uuid.UUID) -> Certificate:
    certificate = db.get(Certificate, certificate_id)
    if certificate is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "certificate_not_found")
    return certificate


def revoke_certificate(
    db: Session, certificate: Certificate, actor_id: uuid.UUID, reason: str
) -> None:
    if certificate.status != ISSUED:
        raise api_error(status.HTTP_409_CONFLICT, "certificate_not_issued")
    certificate.status = REVOKED
    db.add(
        CertificateRevocation(
            revocation_id=uuid.uuid7(),
            certificate_id=certificate.certificate_id,
            reason=reason,
            revoked_by=actor_id,
        )
    )
    notify(
        db,
        certificate.student_id,
        "certificate_revoked",
        {
            **activity_data(db, certificate.activity_id),
            "serial_no": certificate.serial_no,
            "reason": reason,
        },
    )
    db.commit()


def reinstate_certificate(db: Session, certificate: Certificate) -> None:
    """Undo a revocation made by mistake. The revocation stays on record."""
    if certificate.status != REVOKED:
        raise api_error(status.HTTP_409_CONFLICT, "certificate_not_revoked")
    certificate.status = ISSUED
    notify(
        db,
        certificate.student_id,
        "certificate_issued",
        {
            **activity_data(db, certificate.activity_id),
            "serial_no": certificate.serial_no,
        },
    )
    db.commit()


def activity_certificates(db: Session, activity_id: uuid.UUID) -> ActivityCertificates:
    rows = db.execute(
        select(Certificate, User.full_name)
        .join(User, User.id == Certificate.student_id)
        .where(Certificate.activity_id == activity_id)
        .order_by(User.full_name, Certificate.certificate_id)
    ).all()
    return ActivityCertificates(
        items=[
            CertificateEntry(
                id=certificate.certificate_id,
                user_id=certificate.student_id,
                full_name=full_name,
                serial_no=certificate.serial_no,
                status=certificate.status,
                hours=_hours(db, activity_id, certificate.student_id),
                issued_at=certificate.issued_at,
            )
            for certificate, full_name in rows
        ],
        missing_count=len(_attendees_without_certificate(db, activity_id)),
    )


def my_certificates(db: Session, user_id: uuid.UUID) -> list[MyCertificate]:
    rows = db.execute(
        select(Certificate, Activity.title, Organization.name)
        .join(Activity, Activity.id == Certificate.activity_id)
        .join(Organization, Organization.id == Activity.org_id)
        .where(Certificate.student_id == user_id)
        .order_by(Certificate.certificate_id.desc())
    ).all()
    return [
        MyCertificate(
            id=certificate.certificate_id,
            serial_no=certificate.serial_no,
            status=certificate.status,
            hours=_hours(db, certificate.activity_id, user_id),
            issued_at=certificate.issued_at,
            activity_id=certificate.activity_id,
            activity_title=title,
            organization_name=org_name,
        )
        for certificate, title, org_name in rows
    ]


def verify_certificate(db: Session, serial: str) -> VerifiedCertificate:
    """Public lookup. A revoked certificate is still found, with its status shown."""
    row = db.execute(
        select(Certificate, User.full_name, Activity, Organization.name)
        .join(User, User.id == Certificate.student_id)
        .join(Activity, Activity.id == Certificate.activity_id)
        .join(Organization, Organization.id == Activity.org_id)
        .where(Certificate.serial_no == serial.upper())
    ).first()
    if row is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "certificate_not_found")
    certificate, full_name, activity, org_name = row
    revoked_at = None
    if certificate.status == REVOKED:
        revoked_at = db.scalar(
            select(func.max(CertificateRevocation.revoked_at)).where(
                CertificateRevocation.certificate_id == certificate.certificate_id
            )
        )
    return VerifiedCertificate(
        serial_no=certificate.serial_no,
        status=certificate.status,
        full_name=full_name,
        hours=_hours(db, activity.id, certificate.student_id),
        issued_at=certificate.issued_at,
        revoked_at=revoked_at,
        activity_title=activity.title,
        activity_start_at=activity.start_at,
        organization_name=org_name,
    )
