"""cqlengine persistence for auth. LWT claims plus one raw counter query."""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID

from cassandra.cqlengine.connection import get_session

from auth.interfaces import (
    PasswordHasherPort,
    PasswordResetStore,
    RateLimiter,
    RefreshTokenStore,
    UserRepository,
    VerificationCodeStore,
)
from auth.model import (
    AuthRefreshToken,
    EmailVerification,
    PasswordReset,
    RefreshTokenByFamily,
    RefreshTokenByUser,
    User,
    UsersByEmail,
    UsersByPhone,
)
from core.exceptions import EmailTakenError, PhoneTakenError
from core.ids import uuid7


class CqlUserRepository(UserRepository):
    """Users plus email/phone uniqueness enforced by LWT index claims."""

    def __init__(self, keyspace: str) -> None:
        self._keyspace = keyspace

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
        # Raw CQL here because the flow needs was_applied from
        # INSERT ... IF NOT EXISTS, which cqlengine does not surface.
        # Covered by tests/integration/test_auth_db.py.
        session = get_session()
        email_claim = session.execute(
            f"INSERT INTO {self._keyspace}.users_by_email (email, user_id)"
            " VALUES (%s, %s) IF NOT EXISTS",
            [email, user_id],
        )
        if not email_claim.was_applied:
            raise EmailTakenError("Email is already registered.")
        phone_claim = session.execute(
            f"INSERT INTO {self._keyspace}.users_by_phone (phone, user_id)"
            " VALUES (%s, %s) IF NOT EXISTS",
            [phone, user_id],
        )
        if not phone_claim.was_applied:
            session.execute(
                f"DELETE FROM {self._keyspace}.users_by_email WHERE email = %s"
                " IF EXISTS",
                [email],
            )
            raise PhoneTakenError("Phone number is already registered.")
        return User.create(
            id=user_id,
            email=email,
            phone=phone,
            password_hash=password_hash,
            full_name=full_name,
            account_type=account_type,
            tax_code=tax_code,
            company_name=company_name,
            legal_rep_name=legal_rep_name,
            legal_rep_id=legal_rep_id,
            legal_rep_position=legal_rep_position,
            date_of_birth=date_of_birth,
            gender=gender,
            address=address,
            status="active",
            created_at=now,
            updated_at=now,
        )

    def get_by_id(self, user_id: UUID) -> User | None:
        return User.objects(id=user_id).first()

    def update_profile(
        self,
        user_id: UUID,
        full_name: str,
        date_of_birth: date | None,
        gender: str | None,
        address: str | None,
        now: datetime,
    ) -> User | None:
        if self.get_by_id(user_id) is None:
            return None
        User.objects(id=user_id).update(
            full_name=full_name,
            date_of_birth=date_of_birth,
            gender=gender,
            address=address,
            updated_at=now,
        )
        return self.get_by_id(user_id)

    def mark_login(self, user_id: UUID, now: datetime) -> None:
        User.objects(id=user_id).update(last_login_at=now)

    def set_last_seen(self, user_id: UUID, now: datetime) -> None:
        User.objects(id=user_id).update(last_seen_at=now)

    def set_avatar_media(
        self, user_id: UUID, asset_id: UUID | None, now: datetime
    ) -> None:
        User.objects(id=user_id).update(
            avatar_media_id=asset_id, updated_at=now
        )

    def get_by_email(self, email: str) -> User | None:
        index = UsersByEmail.objects(email=email).first()
        return self.get_by_id(index.user_id) if index else None

    def get_by_phone(self, phone: str) -> User | None:
        index = UsersByPhone.objects(phone=phone).first()
        return self.get_by_id(index.user_id) if index else None

    def mark_email_verified(self, user_id: UUID, now: datetime) -> None:
        User.objects(id=user_id).update(email_verified_at=now, updated_at=now)

    def set_password_hash(
        self, user_id: UUID, password_hash: str, now: datetime
    ) -> None:
        User.objects(id=user_id).update(password_hash=password_hash, updated_at=now)


class CqlRefreshTokenStore(RefreshTokenStore):
    """Refresh digests mirrored into user and family query tables."""

    def create(
        self,
        token_hash: str,
        user_id: UUID,
        family_id: UUID,
        expires_at: datetime,
        rotated_from: str | None,
        now: datetime,
    ) -> AuthRefreshToken:
        row = AuthRefreshToken.create(
            token_hash=token_hash,
            user_id=user_id,
            family_id=family_id,
            expires_at=expires_at,
            rotated_from=rotated_from,
            created_at=now,
        )
        RefreshTokenByUser.create(
            user_id=user_id,
            token_hash=token_hash,
            family_id=family_id,
            expires_at=expires_at,
        )
        RefreshTokenByFamily.create(
            family_id=family_id,
            token_hash=token_hash,
            user_id=user_id,
            expires_at=expires_at,
        )
        return row

    def get_by_hash(self, token_hash: str) -> AuthRefreshToken | None:
        return AuthRefreshToken.objects(token_hash=token_hash).first()

    def _touch(
        self, token_hash: str, user_id: UUID, family_id: UUID, now: datetime
    ) -> None:
        AuthRefreshToken.objects(token_hash=token_hash).update(revoked_at=now)
        RefreshTokenByUser.objects(user_id=user_id, token_hash=token_hash).update(
            revoked_at=now
        )
        RefreshTokenByFamily.objects(
            family_id=family_id, token_hash=token_hash
        ).update(revoked_at=now)

    def revoke_one(self, token_hash: str, now: datetime) -> None:
        row = self.get_by_hash(token_hash)
        if row is not None:
            self._touch(token_hash, row.user_id, row.family_id, now)

    def revoke_family(
        self, family_id: UUID, now: datetime, except_hash: str | None = None
    ) -> None:
        for member in RefreshTokenByFamily.objects(family_id=family_id).all():
            if except_hash is not None and member.token_hash == except_hash:
                continue
            self._touch(member.token_hash, member.user_id, family_id, now)

    def revoke_all_for_user(
        self, user_id: UUID, now: datetime, except_hash: str | None = None
    ) -> None:
        for member in RefreshTokenByUser.objects(user_id=user_id).all():
            if except_hash is not None and member.token_hash == except_hash:
                continue
            self._touch(member.token_hash, user_id, member.family_id, now)


class CqlVerificationCodeStore(VerificationCodeStore):
    """Email verification digests keyed by hash (ticket pattern)."""

    def issue(
        self, code_hash: str, user_id: UUID, email: str, expires_at: datetime
    ) -> EmailVerification:
        return EmailVerification.create(
            token_hash=code_hash,
            user_id=user_id,
            email=email,
            expires_at=expires_at,
        )

    def get_by_hash(self, code_hash: str) -> EmailVerification | None:
        return EmailVerification.objects(token_hash=code_hash).first()

    def mark_used(self, code_hash: str, now: datetime) -> None:
        EmailVerification.objects(token_hash=code_hash).update(verified_at=now)


class CqlPasswordResetStore(PasswordResetStore):
    """Password reset digests keyed by hash (ticket pattern)."""

    def issue(
        self, code_hash: str, user_id: UUID, expires_at: datetime
    ) -> PasswordReset:
        return PasswordReset.create(
            token_hash=code_hash, user_id=user_id, expires_at=expires_at
        )

    def get_by_hash(self, code_hash: str) -> PasswordReset | None:
        return PasswordReset.objects(token_hash=code_hash).first()

    def mark_used(self, code_hash: str, now: datetime) -> None:
        PasswordReset.objects(token_hash=code_hash).update(used_at=now)


class CqlRateLimiter(RateLimiter):
    """Fixed-window counters in ScyllaDB (durable, shared across workers)."""

    def __init__(self, keyspace: str) -> None:
        self._keyspace = keyspace

    def hit(self, bucket: str, window_seconds: int) -> int:
        # Raw CQL here because auth_rate_limits.hits is a counter column
        # and cqlengine exposes no typed counter-increment API.
        # Covered by tests/integration/test_auth_db.py.
        now = datetime.now(timezone.utc)
        epoch = int(now.timestamp())
        start = datetime.fromtimestamp(
            epoch - (epoch % window_seconds), tz=timezone.utc
        )
        session = get_session()
        session.execute(
            f"UPDATE {self._keyspace}.auth_rate_limits SET hits = hits + 1"
            " WHERE bucket = %s AND window_start = %s",
            [bucket, start],
        )
        row = session.execute(
            f"SELECT hits FROM {self._keyspace}.auth_rate_limits"
            " WHERE bucket = %s AND window_start = %s",
            [bucket, start],
        ).one()
        if row is None:
            return 1
        return int(row["hits"])


def generate_user_id() -> UUID:
    """Application-side UUIDv7 primary key for new users."""
    return uuid7()


class Argon2PasswordHasher(PasswordHasherPort):
    """Production hasher adapter delegating to the core Argon2id wrapper."""

    def hash(self, plain: str) -> str:
        from core import hashing

        return hashing.hash_password(plain)

    def verify(self, stored_hash: str, candidate: str) -> bool:
        from core import hashing

        return hashing.verify_password(stored_hash, candidate)

    def needs_rehash(self, stored_hash: str) -> bool:
        from core import hashing

        return hashing.needs_rehash(stored_hash)
