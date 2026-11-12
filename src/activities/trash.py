"""The activity trash: deleted drafts, restoring them, and removing them for good.

Only drafts can be deleted, and a draft never had registrations, so removing one
for good takes nothing people signed up for. Its shifts go with it by cascade.
"""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.activities.trash_rules import TRASH_DAYS, may_purge, may_restore, trash_expired
from src.auth.errors import api_error
from src.models.activities import Activity
from src.models.organizations import Organization
from src.organizations.access import Access, get_access


def _not_found() -> HTTPException:
    return api_error(status.HTTP_404_NOT_FOUND, "activity_not_found")


def _forbidden() -> HTTPException:
    return api_error(status.HTTP_403_FORBIDDEN, "organization_forbidden")


def purge_expired(db: Session, org_id: uuid.UUID, now: datetime) -> int:
    """Remove activities that stayed in the trash longer than the keep period."""
    cutoff = now - timedelta(days=TRASH_DAYS)
    result = db.execute(
        delete(Activity).where(
            Activity.org_id == org_id,
            Activity.deleted_at.is_not(None),
            Activity.deleted_at <= cutoff,
        )
    )
    return int(getattr(result, "rowcount", 0) or 0)


def list_trash(
    db: Session,
    org: Organization,
    user_id: uuid.UUID,
    *,
    before: uuid.UUID | None,
    limit: int,
) -> list[Activity]:
    """Deleted activities of the organization, newest first. Expired ones go first."""
    if not may_restore(get_access(db, org, user_id)):
        raise _forbidden()
    purge_expired(db, org.id, datetime.now(UTC))
    db.commit()
    query = select(Activity).where(
        Activity.org_id == org.id, Activity.deleted_at.is_not(None)
    )
    if before is not None:
        query = query.where(Activity.id < before)
    return list(db.scalars(query.order_by(Activity.id.desc()).limit(limit + 1)))


def _load_trashed(
    db: Session,
    activity_id: uuid.UUID,
    user_id: uuid.UUID,
    allowed: Callable[[Access], bool],
) -> Activity:
    """A deleted activity the caller may act on. Outsiders get a 404, not a 403."""
    activity = db.get(Activity, activity_id)
    if activity is None:
        raise _not_found()
    org = db.scalar(
        select(Organization).where(
            Organization.id == activity.org_id,
            Organization.deleted_at.is_(None),
            Organization.status == "active",
        )
    )
    if org is None:
        raise _not_found()
    access = get_access(db, org, user_id)
    if not allowed(access):
        raise _not_found() if access.status is None else _forbidden()
    if activity.deleted_at is None:
        raise api_error(status.HTTP_409_CONFLICT, "activity_not_in_trash")
    if trash_expired(activity.deleted_at, datetime.now(UTC)):
        # Past the keep period it is as good as gone, even before the purge runs.
        raise _not_found()
    return activity


def restore_activity(
    db: Session, activity_id: uuid.UUID, user_id: uuid.UUID
) -> Activity:
    """Bring a deleted draft back. It comes back as a draft."""
    activity = _load_trashed(db, activity_id, user_id, may_restore)
    activity.deleted_at = None
    db.commit()
    return activity


def purge_activity(db: Session, activity_id: uuid.UUID, user_id: uuid.UUID) -> None:
    activity = _load_trashed(db, activity_id, user_id, may_purge)
    db.delete(activity)
    db.commit()
