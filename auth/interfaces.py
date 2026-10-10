"""Abstract ports for the auth bounded context (DIP wiring)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime
from uuid import UUID

from auth.model import (
    AuthRefreshToken,
    EmailVerification,
    PasswordReset,
    User,
)


class UserRepository(ABC):
    """Persistence port for users plus unique email/phone indexes."""

    @abstractmethod
    def create(
        self,
        user_id: UUID,
        email: str,
        phone: str,
        password_hash: str,
        full_name: str,
        now: datetime,
        account_type: str = "individual",
        tax_code: str | None = None,
        company_name: str | None = None,
        legal_rep_name: str | None = None,
        legal_rep_id: str | None = None,
        legal_rep_position: str | None = None,
        date_of_birth: date | None = None,
        gender: str | None = None,
        address: str | None = None,
    ) -> User:
        """Insert the user row after claiming both unique indexes."""

    @abstractmethod
    def get_by_id(self, user_id: UUID) -> User | None:
        """Load a user by primary key."""

    @abstractmethod
    def update_profile(
        self,
        user_id: UUID,
        full_name: str,
        date_of_birth: date | None,
        gender: str | None,
        address: str | None,
        now: datetime,
    ) -> User | None:
        """Replace the editable profile fields, return the fresh row."""

    @abstractmethod
    def mark_login(self, user_id: UUID, now: datetime) -> None:
        """Stamp last_login_at after a successful credential check."""

    @abstractmethod
    def set_avatar_media(
        self, user_id: UUID, asset_id: UUID | None, now: datetime
    ) -> None:
        """Point avatar_media_id at an uploaded asset (or clear it)."""

    @abstractmethod
    def get_by_email(self, email: str) -> User | None:
        """Load a user through the email index."""

    @abstractmethod
    def get_by_phone(self, phone: str) -> User | None:
        """Load a user through the phone index."""

    @abstractmethod
    def mark_email_verified(self, user_id: UUID, now: datetime) -> None:
        """Stamp the verification time once the code is consumed."""

    @abstractmethod
    def set_password_hash(
        self, user_id: UUID, password_hash: str, now: datetime
    ) -> None:
        """Replace the stored Argon2id hash after reset or change."""


class RefreshTokenStore(ABC):
    """Persistence port for stateful opaque refresh tokens."""

    @abstractmethod
    def create(
        self,
        token_hash: str,
        user_id: UUID,
        family_id: UUID,
        expires_at: datetime,
        rotated_from: str | None,
        now: datetime,
    ) -> AuthRefreshToken:
        """Persist one refresh token digest."""

    @abstractmethod
    def get_by_hash(self, token_hash: str) -> AuthRefreshToken | None:
        """Load a refresh row by its digest."""

    @abstractmethod
    def revoke_one(self, token_hash: str, now: datetime) -> None:
        """Revoke a single refresh token."""

    @abstractmethod
    def revoke_family(
        self, family_id: UUID, now: datetime, except_hash: str | None = None
    ) -> None:
        """Revoke every token of a family, optionally sparing one survivor."""

    @abstractmethod
    def revoke_all_for_user(
        self, user_id: UUID, now: datetime, except_hash: str | None = None
    ) -> None:
        """Revoke every refresh token owned by a user, sparing one optionally."""


class VerificationCodeStore(ABC):
    """Persistence port for single-use email verification codes."""

    @abstractmethod
    def issue(
        self, code_hash: str, user_id: UUID, email: str, expires_at: datetime
    ) -> EmailVerification:
        """Store a fresh code digest."""

    @abstractmethod
    def get_by_hash(self, code_hash: str) -> EmailVerification | None:
        """Load a code row by its digest."""

    @abstractmethod
    def mark_used(self, code_hash: str, now: datetime) -> None:
        """Stamp consumption so a code can never be replayed."""


class PasswordResetStore(ABC):
    """Persistence port for single-use password reset codes."""

    @abstractmethod
    def issue(
        self, code_hash: str, user_id: UUID, expires_at: datetime
    ) -> PasswordReset:
        """Store a fresh reset digest."""

    @abstractmethod
    def get_by_hash(self, code_hash: str) -> PasswordReset | None:
        """Load a reset row by its digest."""

    @abstractmethod
    def mark_used(self, code_hash: str, now: datetime) -> None:
        """Stamp consumption so a reset code can never be replayed."""


class RateLimiter(ABC):
    """Durable fixed-window counter port backed by ScyllaDB, never RAM."""

    @abstractmethod
    def hit(self, bucket: str, window_seconds: int) -> int:
        """Increment the current window bucket, return the new hit count."""


class PasswordHasherPort(ABC):
    """Hashing port so services never depend on Argon2id directly."""

    @abstractmethod
    def hash(self, plain: str) -> str:
        """Hash a plaintext password."""

    @abstractmethod
    def verify(self, stored_hash: str, candidate: str) -> bool:
        """Check a candidate without leaking the reason."""

    @abstractmethod
    def needs_rehash(self, stored_hash: str) -> bool:
        """Report whether a stored hash uses outdated parameters."""
