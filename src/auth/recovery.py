"""Password changes and resets, and email verification."""

from datetime import UTC, datetime, timedelta

from fastapi import BackgroundTasks, HTTPException, status
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.auth.accounts import HOUR, require_password
from src.auth.deps import ClientInfo, Principal
from src.auth.errors import api_error, conflict_from_integrity_error
from src.auth.mailer import Mailer
from src.auth.passwords import hash_password, verify_password
from src.auth.rate_limit import enforce_rate_limit
from src.auth.sessions import revoke_user_sessions
from src.auth.tokens import hash_opaque_token, new_opaque_token
from src.auth.validators import password_is_personal
from src.config import AuthSettings
from src.models.auth import EmailVerification, PasswordReset, User

FORGOT_EMAIL_LIMIT = 3
FORGOT_IP_LIMIT = 20
VERIFICATION_SEND_LIMIT = 5


def _invalid_token() -> HTTPException:
    return api_error(status.HTTP_400_BAD_REQUEST, "invalid_or_expired_token")


def _require_impersonal_password(user: User, password: str) -> None:
    if password_is_personal(password, user.email, user.full_name):
        raise api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "password_personal")


def require_new_password(password_hash: str | None, new_password: str) -> None:
    """Refuse a new password that equals the stored one. Only the hash is known here."""
    if verify_password(password_hash, new_password):
        raise api_error(status.HTTP_400_BAD_REQUEST, "same_password")


def request_password_reset(
    db: Session,
    email: str,
    settings: AuthSettings,
    client: ClientInfo,
    mailer: Mailer,
    background: BackgroundTasks,
) -> None:
    """Email a reset link. The response never reveals whether the account exists."""
    enforce_rate_limit(db, f"forgot:{email.lower()}", FORGOT_EMAIL_LIMIT, HOUR)
    enforce_rate_limit(db, f"forgot-ip:{client.ip}", FORGOT_IP_LIMIT, HOUR)

    user = db.scalar(select(User).where(User.email == email))
    if user is None or user.status != "active":
        return

    now = datetime.now(UTC)
    # Only the newest link stays valid.
    db.execute(
        update(PasswordReset)
        .where(PasswordReset.user_id == user.id, PasswordReset.used_at.is_(None))
        .values(used_at=now)
    )
    raw_token = new_opaque_token()
    db.add(
        PasswordReset(
            token_hash=hash_opaque_token(raw_token),
            user_id=user.id,
            expires_at=now + timedelta(minutes=settings.password_reset_minutes),
        )
    )
    recipient = user.email
    db.commit()
    link = f"{settings.frontend_url}/reset-password?token={raw_token}"
    background.add_task(
        mailer.send,
        recipient,
        "Reset your AmigoACT password",
        f"Open this link to set a new password: {link}\n"
        f"The link expires in {settings.password_reset_minutes} minutes.\n"
        "If you did not ask for this, you can ignore this email.",
    )


def reset_password(db: Session, raw_token: str, new_password: str) -> None:
    now = datetime.now(UTC)
    reset = db.scalar(
        select(PasswordReset)
        .where(PasswordReset.token_hash == hash_opaque_token(raw_token))
        .with_for_update()
    )
    if reset is None or reset.used_at is not None or reset.expires_at <= now:
        raise _invalid_token()
    user = db.get(User, reset.user_id)
    if user is None or user.status != "active":
        raise _invalid_token()

    _require_impersonal_password(user, new_password)
    require_new_password(user.password_hash, new_password)
    reset.used_at = now
    user.password_hash = hash_password(new_password)
    # Whoever knew the old password must not stay logged in.
    revoke_user_sessions(db, user.id)
    db.commit()


def change_password(
    db: Session, principal: Principal, current_password: str, new_password: str
) -> None:
    user = principal.user
    require_password(db, user, current_password)
    if current_password == new_password:
        raise api_error(status.HTTP_400_BAD_REQUEST, "same_password")
    _require_impersonal_password(user, new_password)
    user.password_hash = hash_password(new_password)
    revoke_user_sessions(db, user.id, keep_session_id=principal.session.session_id)
    db.commit()


def queue_email_verification(
    db: Session,
    user: User,
    email: str,
    settings: AuthSettings,
    mailer: Mailer,
    background: BackgroundTasks,
) -> None:
    """Add a verification token and queue its email. Commits."""
    # Only the newest link stays valid.
    db.execute(
        delete(EmailVerification).where(
            EmailVerification.user_id == user.id,
            EmailVerification.verified_at.is_(None),
        )
    )
    raw_token = new_opaque_token()
    db.add(
        EmailVerification(
            token_hash=hash_opaque_token(raw_token),
            user_id=user.id,
            email=email,
            expires_at=datetime.now(UTC)
            + timedelta(hours=settings.email_verification_hours),
        )
    )
    db.commit()
    link = f"{settings.frontend_url}/verify-email?token={raw_token}"
    background.add_task(
        mailer.send,
        email,
        "Confirm your AmigoACT email",
        f"Open this link to confirm your email: {link}\n"
        f"The link expires in {settings.email_verification_hours} hours.",
    )


def resend_verification(
    db: Session,
    user: User,
    settings: AuthSettings,
    mailer: Mailer,
    background: BackgroundTasks,
) -> None:
    enforce_rate_limit(db, f"verify-send:{user.id}", VERIFICATION_SEND_LIMIT, HOUR)
    if user.email_verified_at is not None:
        raise api_error(status.HTTP_409_CONFLICT, "email_already_verified")
    queue_email_verification(db, user, user.email, settings, mailer, background)


def verify_email(db: Session, raw_token: str) -> None:
    now = datetime.now(UTC)
    verification = db.scalar(
        select(EmailVerification)
        .where(EmailVerification.token_hash == hash_opaque_token(raw_token))
        .with_for_update()
    )
    if (
        verification is None
        or verification.verified_at is not None
        or verification.expires_at <= now
    ):
        raise _invalid_token()
    user = db.get(User, verification.user_id)
    if user is None or user.status != "active":
        raise _invalid_token()

    verification.verified_at = now
    user.email = verification.email
    user.email_verified_at = now
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise conflict_from_integrity_error(exc) from exc
