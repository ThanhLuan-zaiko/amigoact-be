"""Authentication business rules. No FastAPI, no CQL strings here."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from auth.interfaces import (
    PasswordHasherPort,
    PasswordResetStore,
    RateLimiter,
    RefreshTokenStore,
    UserRepository,
    VerificationCodeStore,
)
from auth.repository import generate_user_id
from core.config import Settings
from core.email import EmailSender
from core.exceptions import (
    AccountSuspendedError,
    EmailTakenError,
    ExpiredCodeError,
    InvalidBusinessProfileError,
    InvalidCodeError,
    InvalidCredentialsError,
    NotFoundError,
    PhoneTakenError,
    SamePasswordError,
    TooManyRequestsError,
)
from core.ids import uuid7
from core.security import (
    create_access_token,
    hash_token,
    new_numeric_code,
    new_opaque_token,
    utcnow,
)


@dataclass(frozen=True)
class TokenPair:
    """Fresh credential set: short JWT plus stateful refresh digest."""

    access_token: str
    refresh_token: str
    expires_in: int


@dataclass(frozen=True)
class SessionProfile:
    """Signed-in user snapshot for GET /auth/me and cards."""

    id: UUID
    email: str
    phone: str
    full_name: str
    account_type: str
    tax_code: str | None
    company_name: str | None
    legal_rep_name: str | None
    legal_rep_id: str | None
    legal_rep_position: str | None
    email_verified: bool
    created_at: datetime


class AuthService:
    """Registration, verification, login, rotation, reset, change."""

    def __init__(
        self,
        users: UserRepository,
        refresh_tokens: RefreshTokenStore,
        verifications: VerificationCodeStore,
        resets: PasswordResetStore,
        limiter: RateLimiter,
        hasher: PasswordHasherPort,
        mailer: EmailSender,
        settings: Settings,
    ) -> None:
        self._users = users
        self._refresh_tokens = refresh_tokens
        self._verifications = verifications
        self._resets = resets
        self._limiter = limiter
        self._hasher = hasher
        self._mailer = mailer
        self._settings = settings

    def _check_rate(self, bucket: str, limit: int, window: int) -> None:
        if self._limiter.hit(bucket, window) > limit:
            raise TooManyRequestsError("Too many attempts. Try again later.")

    def _profile_of(self, user_id: UUID) -> SessionProfile:
        user = self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User not found.")
        return SessionProfile(
            id=user.id,
            email=user.email,
            phone=user.phone,
            full_name=user.full_name,
            account_type=getattr(user, "account_type", "individual") or "individual",
            tax_code=getattr(user, "tax_code", None),
            company_name=getattr(user, "company_name", None),
            legal_rep_name=getattr(user, "legal_rep_name", None),
            legal_rep_id=getattr(user, "legal_rep_id", None),
            legal_rep_position=getattr(user, "legal_rep_position", None),
            email_verified=user.email_verified_at is not None,
            created_at=user.created_at,
        )

    def _mint_pair(self, user_id: UUID) -> TokenPair:
        ttl = self._settings.jwt_access_ttl_seconds
        access = create_access_token(
            str(user_id), self._settings.jwt_secret, ttl_seconds=ttl
        )
        refresh = new_opaque_token()
        self._refresh_tokens.create(
            token_hash=hash_token(refresh),
            user_id=user_id,
            family_id=uuid7(),
            expires_at=utcnow() + timedelta(days=self._settings.refresh_token_ttl_days),
            rotated_from=None,
            now=utcnow(),
        )
        return TokenPair(access_token=access, refresh_token=refresh, expires_in=ttl)

    def register(
        self,
        email: str,
        phone: str,
        password: str,
        full_name: str,
        account_type: str = "individual",
        tax_code: str | None = None,
        company_name: str | None = None,
        legal_rep_name: str | None = None,
        legal_rep_id: str | None = None,
        legal_rep_position: str | None = None,
    ) -> SessionProfile:
        """Create an account. Business tier requires legal identity."""
        if self._users.get_by_email(email) is not None:
            raise EmailTakenError("Email is already registered.")
        if self._users.get_by_phone(phone) is not None:
            raise PhoneTakenError("Phone number is already registered.")
        if account_type not in ("individual", "business"):
            raise InvalidBusinessProfileError("account_type is invalid.")
        if account_type == "business" and not (
            tax_code and company_name and legal_rep_name and legal_rep_id
        ):
            raise InvalidBusinessProfileError("Business accounts require tax and legal identity.")
        now = utcnow()
        user = self._users.create(
            generate_user_id(),
            email,
            phone,
            self._hasher.hash(password),
            full_name,
            now,
            account_type,
            tax_code,
            company_name,
            legal_rep_name,
            legal_rep_id,
            legal_rep_position,
        )
        return self._profile_of(user.id)

    def _issue_verification_code(self, user_id: UUID, email: str) -> str:
        code = new_numeric_code()
        self._verifications.issue(
            code_hash=hash_token(code),
            user_id=user_id,
            email=email,
            expires_at=utcnow()
            + timedelta(minutes=self._settings.verification_code_ttl_minutes),
        )
        self._mailer.send_code(email, "AmigoACT verification code", code)
        return code

    def verify_email(self, email: str, code: str, ip: str) -> SessionProfile:
        """Consume a code. Failures stay generic to block enumeration."""
        self._check_rate(
            f"code:{ip}",
            self._settings.code_max_attempts,
            self._settings.code_window_seconds,
        )
        user = self._users.get_by_email(email)
        row = self._verifications.get_by_hash(hash_token(code))
        if user is None or row is None or row.user_id != user.id:
            raise InvalidCodeError("Verification code is invalid.")
        if row.verified_at is not None:
            raise InvalidCodeError("Verification code is invalid.")
        if _expired(row.expires_at):
            raise ExpiredCodeError("Verification code has expired.")
        now = utcnow()
        self._verifications.mark_used(row.token_hash, now)
        self._users.mark_email_verified(user.id, now)
        return self._profile_of(user.id)

    def resend_verification(self, email: str, ip: str) -> None:
        """Reissue a code. Always silent about account existence."""
        self._check_rate(
            f"code:{ip}",
            self._settings.code_max_attempts,
            self._settings.code_window_seconds,
        )
        user = self._users.get_by_email(email)
        if user is None or user.email_verified_at is not None:
            return
        self._issue_verification_code(user.id, email)

    def login(self, email: str, password: str, ip: str) -> TokenPair:
        """Check credentials, then mint a pair (verification gate deferred)."""
        self._check_rate(
            f"login:{ip}",
            self._settings.login_max_attempts,
            self._settings.login_window_seconds,
        )
        user = self._users.get_by_email(email)
        if user is None or not self._hasher.verify(user.password_hash, password):
            raise InvalidCredentialsError("Email or password is incorrect.")
        if user.status != "active":
            raise AccountSuspendedError("Account is suspended.")
        if self._hasher.needs_rehash(user.password_hash):
            self._users.set_password_hash(
                user.id, self._hasher.hash(password), utcnow()
            )
        return self._mint_pair(user.id)

    def refresh(self, refresh_token: str) -> TokenPair:
        """Rotate one token. Reuse of a revoked token burns the family."""
        row = self._refresh_tokens.get_by_hash(hash_token(refresh_token))
        now = utcnow()
        if row is None or _expired(row.expires_at):
            raise InvalidCredentialsError("Session has expired.")
        if row.revoked_at is not None:
            self._refresh_tokens.revoke_family(row.family_id, now)
            raise InvalidCredentialsError("Session has expired.")
        ttl = self._settings.jwt_access_ttl_seconds
        access = create_access_token(
            str(row.user_id), self._settings.jwt_secret, ttl_seconds=ttl
        )
        successor = new_opaque_token()
        self._refresh_tokens.revoke_one(row.token_hash, now)
        self._refresh_tokens.create(
            token_hash=hash_token(successor),
            user_id=row.user_id,
            family_id=row.family_id,
            expires_at=utcnow() + timedelta(days=self._settings.refresh_token_ttl_days),
            rotated_from=row.token_hash,
            now=now,
        )
        return TokenPair(access_token=access, refresh_token=successor, expires_in=ttl)

    def logout(self, refresh_token: str | None) -> None:
        """Revoke one token. Unknown tokens still answer success."""
        if refresh_token:
            self._refresh_tokens.revoke_one(hash_token(refresh_token), utcnow())

    def logout_all(self, user_id: UUID) -> None:
        """Revoke every refresh token of a user."""
        self._refresh_tokens.revoke_all_for_user(user_id, utcnow())

    def forgot_password(self, email: str, ip: str) -> None:
        """Issue a reset code. Always silent about account existence."""
        self._check_rate(
            f"code:{ip}",
            self._settings.code_max_attempts,
            self._settings.code_window_seconds,
        )
        user = self._users.get_by_email(email)
        if user is None:
            return
        code = new_numeric_code()
        self._resets.issue(
            code_hash=hash_token(code),
            user_id=user.id,
            expires_at=utcnow()
            + timedelta(minutes=self._settings.reset_code_ttl_minutes),
        )
        self._mailer.send_code(email, "AmigoACT password reset code", code)

    def reset_password(self, email: str, code: str, new_password: str) -> None:
        """Consume a reset code, set the password, burn all sessions."""
        user = self._users.get_by_email(email)
        row = self._resets.get_by_hash(hash_token(code))
        if user is None or row is None or row.user_id != user.id:
            raise InvalidCodeError("Reset code is invalid.")
        if row.used_at is not None:
            raise InvalidCodeError("Reset code is invalid.")
        if _expired(row.expires_at):
            raise ExpiredCodeError("Reset code has expired.")
        now = utcnow()
        self._resets.mark_used(row.token_hash, now)
        self._users.set_password_hash(user.id, self._hasher.hash(new_password), now)
        self._refresh_tokens.revoke_all_for_user(user.id, now)

    def change_password(
        self, user_id: UUID, current_password: str, new_password: str,
        current_token_hash: str | None,
    ) -> None:
        """Rotate the password after proving the current one survives."""
        user = self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User not found.")
        if not self._hasher.verify(user.password_hash, current_password):
            raise InvalidCredentialsError("Current password is incorrect.")
        if self._hasher.verify(user.password_hash, new_password):
            raise SamePasswordError(
                "New password must differ from the current password."
            )
        now = utcnow()
        self._users.set_password_hash(user.id, self._hasher.hash(new_password), now)
        self._refresh_tokens.revoke_all_for_user(
            user.id, now, except_hash=current_token_hash
        )

    def get_profile(self, user_id: UUID) -> SessionProfile:
        """Public session snapshot for GET /auth/me and cards."""
        return self._profile_of(user_id)

    def dev_challenge_code(self, email: str, kind: str) -> tuple[str, int]:
        """Dev-only plaintext code issuance (router guards ENV=dev)."""
        user = self._users.get_by_email(email)
        if user is None:
            raise NotFoundError("User not found.")
        code = new_numeric_code()
        if kind == "reset":
            ttl = self._settings.reset_code_ttl_minutes
            self._resets.issue(
                hash_token(code), user.id, utcnow() + timedelta(minutes=ttl)
            )
        else:
            ttl = self._settings.verification_code_ttl_minutes
            self._verifications.issue(
                hash_token(code), user.id, email, utcnow() + timedelta(minutes=ttl)
            )
        return code, ttl * 60


def _expired(moment: datetime | None) -> bool:
    """Treat missing timestamps as expired for fail-closed checks."""
    if moment is None:
        return True
    current = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    return current <= utcnow()
