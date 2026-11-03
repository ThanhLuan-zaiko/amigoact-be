import uuid
from collections.abc import Callable
from pathlib import Path

from src.media.sniff import MAX_VIDEO_BYTES
from tests.conftest import ORG_FIELDS, ApiContext

Bearer = Callable[[str], dict[str, str]]
MP4 = b"\x00\x00\x00\x18ftypmp42"
PNG = b"\x89PNG\r\n\x1a\n"


def make_org(api: ApiContext, headers: dict[str, str]) -> str:
    response = api.client.post(
        "/organizations", headers=headers, json={**ORG_FIELDS, "name": f"CLB {api.tag}"}
    )
    assert response.status_code == 201, response.text
    slug: str = response.json()["slug"]
    return slug


def upload(api: ApiContext, headers: dict[str, str], head: bytes) -> str:
    response = api.client.post(
        "/media", headers=headers, files={"file": ("f", head + uuid.uuid4().bytes)}
    )
    assert response.status_code == 201, response.text
    asset_id: str = response.json()["id"]
    return asset_id


def test_video_cannot_become_a_logo(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    owner = bearer(api.register()["tokens"]["access_token"])
    slug = make_org(api, owner)

    response = api.client.patch(
        f"/organizations/{slug}",
        headers=owner,
        json={"logo_asset_id": upload(api, owner, MP4)},
    )

    assert response.status_code == 415


def test_outsider_cannot_change_the_gallery(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    owner = bearer(api.register("owner")["tokens"]["access_token"])
    outsider = bearer(api.register("outsider")["tokens"]["access_token"])
    slug = make_org(api, owner)
    path = f"/organizations/{slug}/gallery"

    added = api.client.post(
        path, headers=outsider, json={"asset_id": upload(api, outsider, PNG)}
    )

    assert added.status_code == 403
    assert api.client.get(path).json() == []


def test_manager_cannot_attach_someone_elses_file(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    owner = bearer(api.register("owner")["tokens"]["access_token"])
    other = bearer(api.register("other")["tokens"]["access_token"])
    slug = make_org(api, owner)

    response = api.client.post(
        f"/organizations/{slug}/gallery",
        headers=owner,
        json={"asset_id": upload(api, other, PNG)},
    )

    assert response.status_code == 404


def test_video_over_the_limit_is_rejected(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    owner = bearer(api.register()["tokens"]["access_token"])
    body = MP4 + b"\0" * MAX_VIDEO_BYTES

    response = api.client.post("/media", headers=owner, files={"file": ("f", body)})

    assert response.status_code == 413
    assert response.json()["detail"] == "video_too_large"
