"""Permanent delete of an organization from its owner's trash.

Only a trashed organization can be purged. The purge deletes the organization row, and the
database cascades to its activities, registrations, attendance, posts, chat and members.
Three kinds of record stop the purge:
- an open activity, which the soft delete already refuses;
- an issued certificate, which is the student's proof and would go with its activity;
- a pending hour entry, which nobody can approve once the organization is gone.
Approved hours stay in the ledger, with org_id and activity_id cleared.
"""

import uuid

from fastapi import status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from src.auth.errors import api_error
from src.models.activities import Activity
from src.models.attendance import VolunteerHourLedger
from src.models.certificates import Certificate
from src.models.organizations import Organization
from src.organizations.open_activities import open_activity_count

PENDING = "pending"


def purge_blocker(
    open_activities: int, certificates: int, pending_hours: int
) -> str | None:
    """The error code that stops the purge, or None when it may go ahead."""
    if open_activities > 0:
        return "organization_has_open_activities"
    if certificates > 0:
        return "organization_has_certificates"
    if pending_hours > 0:
        return "organization_has_pending_hours"
    return None


def _certificate_count(db: Session, org_id: uuid.UUID) -> int:
    count = db.scalar(
        select(func.count())
        .select_from(Certificate)
        .join(Activity, Certificate.activity_id == Activity.id)
        .where(Activity.org_id == org_id)
    )
    return count or 0


def _pending_hour_count(db: Session, org_id: uuid.UUID) -> int:
    count = db.scalar(
        select(func.count())
        .select_from(VolunteerHourLedger)
        .where(
            VolunteerHourLedger.org_id == org_id,
            VolunteerHourLedger.status == PENDING,
        )
    )
    return count or 0


def purge_organization(db: Session, owner_id: uuid.UUID, org_id: uuid.UUID) -> None:
    """Delete a trashed organization for good. Only its owner can, and only from the trash."""
    org = db.scalar(
        select(Organization)
        .where(
            Organization.id == org_id,
            Organization.owner_id == owner_id,
            Organization.deleted_at.is_not(None),
        )
        .with_for_update()
    )
    if org is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "organization_not_found")
    error = purge_blocker(
        open_activity_count(db, org.id),
        _certificate_count(db, org.id),
        _pending_hour_count(db, org.id),
    )
    if error is not None:
        raise api_error(status.HTTP_409_CONFLICT, error)
    # A Core delete, so the database cascades apply and nothing is loaded row by row.
    db.execute(delete(Organization).where(Organization.id == org.id))
    db.commit()
