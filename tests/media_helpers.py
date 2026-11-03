"""Shared steps for the media API tests."""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from src.app import app
from src.media.cleanup import Plan, run
from src.models.media import MediaAsset
from src.models.organizations import Organization
from tests.conftest import ApiContext

Headers = dict[str, str]
GRACE_DAYS = 30

# Only the first bytes matter for detection, so these are enough for every test.
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 100
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 50


def upload(
    api: ApiContext,
    headers: Headers,
    data: bytes = PNG,
    name: str = "photo.png",
) -> Any:
    return api.client.post(
        "/media", headers=headers, files={"file": (name, data, "image/png")}
    )


def uploaded(api: ApiContext, headers: Headers, data: bytes = PNG) -> dict[str, Any]:
    response = upload(api, headers, data)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def set_avatar(api: ApiContext, headers: Headers, asset_id: str | None) -> Any:
    return api.client.put(
        "/account/me/avatar", headers=headers, json={"asset_id": asset_id}
    )


MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 100


def stored(media_root: Path, asset_id: str) -> list[Path]:
    """The stored file or files of one asset. Files sit flat in the media root."""
    return list(media_root.glob(f"{asset_id}.*"))


def upload_video(api: ApiContext, headers: Headers) -> str:
    response = api.client.post(
        "/media", headers=headers, files={"file": ("clip.mp4", MP4)}
    )
    assert response.status_code == 201, response.text
    asset_id: str = response.json()["id"]
    return asset_id


def db_row(model: type, key: Any) -> Any:
    """Read one row straight from the database, bypassing the API."""
    with Session(app.state.engine) as session:
        row = session.get(model, key)
        session.expunge_all()
        return row


def org_id_for(slug: str) -> uuid.UUID:
    with Session(app.state.engine) as session:
        org_id = session.scalar(
            select(Organization.id).where(Organization.slug == slug)
        )
    assert org_id is not None
    return org_id


def unique_picture() -> bytes:
    """A picture whose bytes differ each time, so no two uploads share one stored file."""
    return PNG + uuid.uuid4().bytes


def age(asset_id: str, days: int) -> None:
    """Pretend an upload happened that many days ago."""
    with app.state.engine.begin() as connection:
        connection.execute(
            update(MediaAsset)
            .where(MediaAsset.asset_id == uuid.UUID(asset_id))
            .values(created_at=datetime.now(UTC) - timedelta(days=days))
        )


def clean(media_root: Path, user_id: str, *, apply: bool) -> Plan:
    """Run the cleanup for one uploader, so the shared test database is left alone."""
    with Session(app.state.engine) as db:
        return run(
            db,
            media_root,
            now=datetime.now(UTC),
            min_age_days=GRACE_DAYS,
            uploader_id=uuid.UUID(user_id),
            apply=apply,
        )
