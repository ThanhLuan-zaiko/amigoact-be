"""Registration, login, profile changes, and account deletion."""

import uuid

from fastapi import status
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.auth.deps import ClientInfo
from src.auth.errors import api_error, conflict_from_integrity_error, unauthorized
from src.auth.passwords import hash_password, needs_rehash, verify_password
from src.auth.rate_limit import enforce_rate_limit
from src.auth.schemas import ProfileUpdateRequest, RegisterRequest, TokenResponse
from src.auth.sessions import revoke_user_sessions, start_session
from src.config import AuthSettings
from src.models.auth import EmailVerification, PasswordReset, User

MINUTE = 60
HOUR = 60 * MINUTE

LOGIN_EMAIL_LIMIT = 10
LOGIN_IP_LIMIT = 50
LOGIN_WINDOW = 15 * MINUTE
REGISTER_IP_LIMIT = 20
REGISTER_WINDOW = HOUR
PASSWORD_CHECK_LIMIT = 10
PASSWORD_CHECK_WINDOW = 15 * MINUTE

# Personal fields erased when an account is deleted, besides the ones replaced.
ERASED_FIELDS = (
    "phone",
    "tax_code",
    "company_name",
    "legal_rep_name",
    "legal_rep_id",
    "legal_rep_position",
    "date_of_birth",
    "gender",
    "address",
    "avatar_media_id",
    "password_hash",
    "email_verified_at",
)


def create_user(db: Session, payload: RegisterRequest, client: ClientInfo) -> User:
    """Insert the user. The caller commits."""
    enforce_rate_limit(db, f"register:{client.ip}", REGISTER_IP_LIMIT, REGISTER_WINDOW)
    user = User(
        id=uuid.uuid7(),
        email=payload.email,
        phone=payload.phone,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        account_type=payload.account_type,
        tax_code=payload.tax_code,
        company_name=payload.company_name,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise conflict_from_integrity_error(exc) from exc
    return user


def authenticate(
    db: Session,
    email: str,
    password: str,
    settings: AuthSettings,
    client: ClientInfo,
) -> tuple[User, TokenResponse]:
    enforce_rate_limit(db, f"login:{email.lower()}", LOGIN_EMAIL_LIMIT, LOGIN_WINDOW)
    enforce_rate_limit(db, f"login-ip:{client.ip}", LOGIN_IP_LIMIT, LOGIN_WINDOW)

    user = db.scalar(select(User).where(User.email == email))
    password_hash = user.password_hash if user else None
    if user is None or password_hash is None:
        verify_password(None, password)
        raise unauthorized("invalid_credentials")
    if not verify_password(password_hash, password):
        raise unauthorized("invalid_credentials")
    if user.status != "active":
        raise api_error(status.HTTP_403_FORBIDDEN, "account_disabled")

    if needs_rehash(password_hash):
        user.password_hash = hash_password(password)
    tokens = start_session(db, user, settings, client)
    db.commit()
    return user, tokens


def require_password(db: Session, user: User, password: str) -> None:
    """Confirm the password before a sensitive change, with a limit on guesses."""
    enforce_rate_limit(
        db, f"password:{user.id}", PASSWORD_CHECK_LIMIT, PASSWORD_CHECK_WINDOW
    )
    if not verify_password(user.password_hash, password):
        raise api_error(status.HTTP_400_BAD_REQUEST, "invalid_current_password")


def update_profile(db: Session, user: User, payload: ProfileUpdateRequest) -> User:
    for field in payload.model_fields_set:
        setattr(user, field, getattr(payload, field))
    if user.account_type == "business" and not (user.tax_code and user.company_name):
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "business_fields_required"
        )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise conflict_from_integrity_error(exc) from exc
    return user


def delete_account(db: Session, user: User) -> None:
    """Soft delete: keep the row for foreign keys, but erase personal data."""
    owns_organization = db.execute(
        text("SELECT 1 FROM organizations WHERE owner_id = :user_id LIMIT 1"),
        {"user_id": user.id},
    ).first()
    if owns_organization:
        raise api_error(status.HTTP_409_CONFLICT, "owns_organizations")

    revoke_user_sessions(db, user.id)
    db.execute(delete(PasswordReset).where(PasswordReset.user_id == user.id))
    db.execute(delete(EmailVerification).where(EmailVerification.user_id == user.id))
    user.status = "deleted"
    # The .invalid domain can never receive mail, and the id keeps the email unique.
    user.email = f"deleted-{user.id}@deleted.invalid"
    user.full_name = "Deleted user"
    for field in ERASED_FIELDS:
        setattr(user, field, None)
    db.commit()
