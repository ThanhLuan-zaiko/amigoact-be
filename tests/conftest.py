"""Fixtures for tests that call the API. They use the database from .env."""

import random
import re
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, or_, select, update

from src.app import app
from src.auth.mailer import get_mailer
from src.media.storage import get_media_root
from src.models.activities import Activity, Registration
from src.models.attendance import QrScanLog
from src.models.auth import AuthRateLimit, User
from src.models.chat import OrgRoomMessage
from src.models.media import MediaAsset
from src.models.organizations import Organization
from src.models.posts import OrgPost, PostComment

PASSWORD = "Correct-Horse-7-Battery"
# Every field an organization needs besides its name.
ORG_FIELDS: dict[str, Any] = {
    "description": "Test organization",
    "email": "org@example.com",
    "phone": "0912345678",
    "city": "Ha Noi",
}


@dataclass
class FakeMailer:
    sent: list[tuple[str, str, str]] = field(default_factory=list)

    def send(self, to: str, subject: str, body: str) -> None:
        self.sent.append((to, subject, body))

    def last_token(self) -> str:
        match = re.search(r"token=([\w-]+)", self.sent[-1][2])
        assert match is not None
        return match.group(1)


@dataclass
class ApiContext:
    client: TestClient
    mailer: FakeMailer
    tag: str

    def email(self, name: str = "user") -> str:
        return f"{name}-{self.tag}@example.com"

    def register(
        self, name: str = "user", *, verified: bool = True, **extra: object
    ) -> dict[str, dict[str, str]]:
        """Users start verified, because creating an organization requires it."""
        response = self.client.post(
            "/auth/register",
            json={
                "email": self.email(name),
                "password": PASSWORD,
                "full_name": "Test User",
                **extra,
            },
        )
        assert response.status_code == 201, response.text
        if verified:
            with app.state.engine.begin() as connection:
                connection.execute(
                    update(User)
                    .where(User.email == self.email(name))
                    .values(email_verified_at=func.now())
                )
        result: dict[str, dict[str, str]] = response.json()
        return result


@pytest.fixture
def api() -> Iterator[ApiContext]:
    """A client with a unique IP and emails, so rate limit buckets never carry over."""
    tag = uuid.uuid4().hex
    ip = (
        f"10.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}"
    )
    mailer = FakeMailer()
    app.dependency_overrides[get_mailer] = lambda: mailer
    with TestClient(app, client=(ip, 50000)) as client:
        yield ApiContext(client, mailer, tag)
        # Remove only the rows this test created. CASCADE clears tokens and sessions.
        # Organizations go first, because owner_id does not cascade.
        with app.state.engine.begin() as connection:
            user_ids = connection.scalars(
                select(User.id).where(User.email.like(f"%{tag}%"))
            ).all()
            # Registrations go before their shifts, because slot_id is RESTRICT.
            org_ids = select(Organization.id).where(Organization.owner_id.in_(user_ids))
            activity_ids = select(Activity.id).where(Activity.org_id.in_(org_ids))
            connection.execute(
                delete(Registration).where(Registration.activity_id.in_(activity_ids))
            )
            connection.execute(
                delete(Organization).where(Organization.owner_id.in_(user_ids))
            )
            connection.execute(
                delete(AuthRateLimit).where(
                    AuthRateLimit.bucket.in_(
                        f"{prefix}:{user_id}"
                        for prefix in (
                            "org-create",
                            "org-join",
                            "activity-create",
                            "activity-register",
                            "checkin",
                            "media-upload",
                        )
                        for user_id in user_ids
                    )
                )
            )
            connection.execute(
                delete(QrScanLog).where(QrScanLog.student_id.in_(user_ids))
            )
            connection.execute(
                delete(MediaAsset).where(MediaAsset.uploader_id.in_(user_ids))
            )
            # Posts and comments by these users do not cascade from users.
            connection.execute(
                delete(PostComment).where(PostComment.author_id.in_(user_ids))
            )
            connection.execute(delete(OrgPost).where(OrgPost.author_id.in_(user_ids)))
            connection.execute(
                delete(OrgRoomMessage).where(OrgRoomMessage.author_id.in_(user_ids))
            )
            connection.execute(delete(User).where(User.email.like(f"%{tag}%")))
            connection.execute(
                delete(AuthRateLimit).where(
                    or_(
                        AuthRateLimit.bucket.like(f"%{tag}%"),
                        AuthRateLimit.bucket.like(f"%{ip}"),
                    )
                )
            )
    app.dependency_overrides.pop(get_mailer)


@pytest.fixture
def media_root(tmp_path: Path) -> Iterator[Path]:
    """Keep uploads in a temporary folder, never in the repository."""
    app.dependency_overrides[get_media_root] = lambda: tmp_path
    yield tmp_path
    app.dependency_overrides.pop(get_media_root)


@pytest.fixture
def bearer() -> Callable[[str], dict[str, str]]:
    return lambda token: {"Authorization": f"Bearer {token}"}
