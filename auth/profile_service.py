"""Session profile reads/writes for the auth context (business rules)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from auth.interfaces import UserRepository
from auth.model import User
from core.exceptions import InvalidBusinessProfileError, NotFoundError
from core.security import utcnow
from orgs.interfaces import MediaRepository


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
    date_of_birth: date | None
    gender: str | None
    address: str | None
    last_login_at: datetime | None
    email_verified: bool
    created_at: datetime
    avatar_url: str | None


class ProfileService:
    """Profile snapshot reads plus the editable-fields replace flow."""

    def __init__(self, users: UserRepository, media: MediaRepository) -> None:
        self._users = users
        self._media = media

    def _avatar_url(self, user: User) -> str | None:
        """Resolve avatar_media_id to its public /media path."""
        asset_id = getattr(user, "avatar_media_id", None)
        if asset_id is None:
            return None
        row = self._media.get_asset(asset_id)
        return f"/media/{row.file_url}" if row else None

    def of(self, user_id: UUID) -> SessionProfile:
        """Build the public snapshot; cqlengine Date -> datetime.date."""
        user = self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User not found.")
        dob = getattr(user, "date_of_birth", None)
        if dob is not None and not isinstance(dob, date):
            dob = dob.date()
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
            date_of_birth=dob,
            gender=getattr(user, "gender", None),
            address=getattr(user, "address", None),
            last_login_at=getattr(user, "last_login_at", None),
            email_verified=user.email_verified_at is not None,
            created_at=user.created_at,
            avatar_url=self._avatar_url(user),
        )

    def update(
        self,
        user_id: UUID,
        full_name: str,
        date_of_birth: date | None = None,
        gender: str | None = None,
        address: str | None = None,
    ) -> SessionProfile:
        """Replace the editable profile fields; None clears optional ones."""
        clean_name = full_name.strip()
        if not (2 <= len(clean_name) <= 100):
            raise InvalidBusinessProfileError("Full name is invalid.")
        if gender is not None and gender not in (
            "male", "female", "other", "unspecified"
        ):
            raise InvalidBusinessProfileError("Gender is invalid.")
        if date_of_birth is not None and (
            date_of_birth > date.today() or date_of_birth.year < 1900
        ):
            raise InvalidBusinessProfileError("Date of birth is invalid.")
        clean_address = (address or "").strip() or None
        if clean_address is not None and len(clean_address) > 255:
            raise InvalidBusinessProfileError("Address is invalid.")
        user = self._users.update_profile(
            user_id, clean_name, date_of_birth, gender, clean_address, utcnow()
        )
        if user is None:
            raise NotFoundError("User not found.")
        return self.of(user_id)
