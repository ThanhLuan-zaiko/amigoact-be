"""Shared steps for the media API tests."""

import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.app import app
from src.models.organizations import Organization
from tests.conftest import ApiContext

Headers = dict[str, str]

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


def placed(media_root: Path, user_id: str, *folders: str) -> set[str]:
    """Names of the links shown in one folder of the account tree."""
    folder = media_root.joinpath("users", user_id, *folders)
    return {entry.name for entry in folder.iterdir()} if folder.is_dir() else set()


def stored(media_root: Path, user_id: str, asset_id: str) -> list[Path]:
    """The stored file, found under the by-date folder of its uploader."""
    return list(media_root.joinpath("users", user_id, "by-date").rglob(f"{asset_id}.*"))


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
