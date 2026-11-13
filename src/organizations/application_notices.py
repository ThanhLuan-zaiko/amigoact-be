"""Telling managers about membership applications, and taking it back on withdrawal."""

import uuid
from typing import Final

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from src.models.auth import User
from src.models.notifications import Notification
from src.models.organizations import Organization
from src.notifications.events import notify, organization_data
from src.notifications.live import deleted_event, queue_push
from src.organizations.access import staff_user_ids
from src.organizations.permissions import APPLICATIONS_REVIEW

REQUESTED: Final = "membership_requested"


def tell_managers(
    db: Session, org: Organization, user_id: uuid.UUID, message: str | None
) -> None:
    """The owner and everyone who reviews applications hear about a new application, with its reason."""
    applicant = db.get(User, user_id)
    data = {
        **organization_data(org),
        "organization_id": str(org.id),
        "applicant_id": str(user_id),
        "applicant_name": applicant.full_name if applicant else None,
        "message": message,
    }
    for manager_id in sorted(
        {org.owner_id, *staff_user_ids(db, org.id, APPLICATIONS_REVIEW)}
    ):
        notify(db, manager_id, REQUESTED, data)


def withdraw_notices(db: Session, org: Organization, user_id: uuid.UUID) -> None:
    """A withdrawn application leaves nothing to review, so its notices go away.

    Older notices have no organization_id, so the slug matches them.
    """
    data = Notification.data_json
    rows = db.scalars(
        select(Notification).where(
            Notification.type == REQUESTED,
            data["applicant_id"].astext == str(user_id),
            or_(
                data["organization_id"].astext == str(org.id),
                data["organization_slug"].astext == org.slug,
            ),
        )
    ).all()
    for row in rows:
        # Leaves after the commit, so the bell and the review page drop it at once.
        queue_push(db, row.user_id, deleted_event(row))
        db.delete(row)
