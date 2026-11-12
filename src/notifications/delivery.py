"""Sending the emails that notify queued, once the request has finished."""

from collections.abc import Iterator

from src.auth.deps import Config, Db, MailerDep
from src.notifications.events import READY, QueuedEmail

SUBJECTS = {
    "registration_approved": "Your registration was approved",
    "registration_rejected": "Your registration was not approved",
    "registration_promoted": "A seat opened up for you",
    "activity_cancelled": "An activity was cancelled",
    "membership_requested": "Someone asked to join your organization",
    "membership_approved": "Your membership request was approved",
    "membership_rejected": "Your membership request was not approved",
    "member_left": "A member left your organization",
    "membership_removed": "You were removed from an organization",
    "hours_awarded": "Your volunteer hours were recorded",
    "appeal_approved": "Your attendance appeal was accepted",
    "appeal_rejected": "Your attendance appeal was rejected",
    "certificate_issued": "You received a certificate",
    "certificate_revoked": "A certificate was revoked",
}


def email_content(email: QueuedEmail, base_url: str) -> tuple[str, str]:
    subject = SUBJECTS.get(email.type, "AmigoACT notification")
    if email.subject_detail:
        subject = f"{subject}: {email.subject_detail}"
    return subject, f"{subject}.\nSee the details: {base_url}/notifications\n"


def deliver_emails(db: Db, mailer: MailerDep, settings: Config) -> Iterator[None]:
    """Attach to a router. It runs after the response, so slow SMTP never delays it."""
    yield
    for email in db.info.pop(READY, []):
        subject, body = email_content(email, settings.frontend_url)
        mailer.send(email.to, subject, body)
