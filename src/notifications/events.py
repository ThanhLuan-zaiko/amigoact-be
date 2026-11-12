"""Creating notifications when something happens.

notify joins the caller's transaction, so a failed action leaves no notification.
An email waits until that transaction commits, so a failed action sends no email.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, get_args

from sqlalchemy import event
from sqlalchemy.orm import Session

from src.models.activities import Activity, Registration
from src.models.auth import User
from src.models.notifications import Notification, NotificationPreference
from src.models.organizations import Organization
from src.notifications.live import notification_event, queue_push

NotificationType = Literal[
    "registration_approved",
    "registration_rejected",
    "registration_promoted",
    "activity_cancelled",
    "membership_requested",
    "membership_approved",
    "membership_rejected",
    "member_left",
    "membership_removed",
    "hours_awarded",
    "appeal_approved",
    "appeal_rejected",
    "certificate_issued",
    "certificate_revoked",
]
NOTIFICATION_TYPES: tuple[str, ...] = get_args(NotificationType)

_QUEUED = "queued_emails"
READY = "ready_emails"


@dataclass(frozen=True)
class QueuedEmail:
    to: str
    type: str
    subject_detail: str


@event.listens_for(Session, "after_commit")
def _release_emails(session: Session) -> None:
    queued = session.info.pop(_QUEUED, [])
    session.info.setdefault(READY, []).extend(queued)


@event.listens_for(Session, "after_rollback")
def _drop_emails(session: Session) -> None:
    session.info.pop(_QUEUED, None)


def activity_data(db: Session, activity_id: uuid.UUID) -> dict[str, Any]:
    """What a notification about an activity needs to show and link to."""
    activity = db.get(Activity, activity_id)
    if activity is None:
        return {}
    org = db.get(Organization, activity.org_id)
    return {
        "activity_id": str(activity.id),
        "activity_title": activity.title,
        "organization_name": org.name if org else None,
    }


def organization_data(org: Organization) -> dict[str, Any]:
    return {"organization_slug": org.slug, "organization_name": org.name}


def notify(
    db: Session,
    user_id: uuid.UUID,
    notification_type: NotificationType,
    data: dict[str, Any],
) -> None:
    """Respect the user's choices. By default in-app is on and email is off."""
    preference = db.get(NotificationPreference, user_id)
    channels = preference.channels if preference else {}
    if preference and notification_type in preference.muted_types:
        return
    if channels.get("inapp", True):
        notification = Notification(
            notification_id=uuid.uuid7(),
            user_id=user_id,
            type=notification_type,
            data_json=data,
            created_at=datetime.now(UTC),
        )
        db.add(notification)
        # Leaves after the commit, so the bell rings only for a saved notification.
        queue_push(db, user_id, notification_event(notification))
    if channels.get("email", False):
        user = db.get(User, user_id)
        # An unconfirmed address may belong to someone else.
        if user is not None and user.email_verified_at is not None:
            db.info.setdefault(_QUEUED, []).append(
                QueuedEmail(
                    to=user.email,
                    type=notification_type,
                    subject_detail=str(
                        data.get("activity_title")
                        or data.get("organization_name")
                        or ""
                    ),
                )
            )


def notify_volunteer(
    db: Session,
    registration: Registration,
    notification_type: NotificationType,
    **extra: Any,
) -> None:
    data = activity_data(db, registration.activity_id)
    notify(db, registration.student_id, notification_type, {**data, **extra})
