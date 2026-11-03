import uuid
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.conftest import ORG_FIELDS, ApiContext

Bearer = Callable[[str], dict[str, str]]
PNG = b"\x89PNG\r\n\x1a\n"
MP4 = b"\x00\x00\x00\x18ftypmp42"


@pytest.fixture
def owner(api: ApiContext, bearer: Bearer, media_root: Path) -> dict[str, str]:
    return bearer(api.register("owner")["tokens"]["access_token"])


def upload(api: ApiContext, headers: dict[str, str], head: bytes) -> str:
    body = head + uuid.uuid4().bytes
    response = api.client.post("/media", headers=headers, files={"file": ("f", body)})
    assert response.status_code == 201, response.text
    asset_id: str = response.json()["id"]
    return asset_id


def test_create_puts_pictures_and_videos_in_the_gallery(
    api: ApiContext, owner: dict[str, str]
) -> None:
    ids = [upload(api, owner, PNG), upload(api, owner, MP4)]

    created = api.client.post(
        "/organizations",
        headers=owner,
        json={**ORG_FIELDS, "name": f"CLB {api.tag}", "gallery_asset_ids": ids},
    )
    assert created.status_code == 201, created.text
    path = f"/organizations/{created.json()['slug']}/gallery"
    items = api.client.get(path).json()

    assert {item["id"] for item in items} == set(ids)
    assert {item["mime"] for item in items} == {"image/png", "video/mp4"}
    assert api.client.get(items[0]["url"]).status_code == 200


def test_create_with_logo_cover_and_gallery_keeps_all_three(
    api: ApiContext, owner: dict[str, str]
) -> None:
    logo = upload(api, owner, PNG)
    cover = upload(api, owner, PNG)
    gallery = [upload(api, owner, MP4), upload(api, owner, PNG)]

    created = api.client.post(
        "/organizations",
        headers=owner,
        json={
            **ORG_FIELDS,
            "name": f"CLB {api.tag}",
            "logo_asset_id": logo,
            "cover_asset_id": cover,
            "gallery_asset_ids": gallery,
        },
    )

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["logo_url"] is not None
    assert body["cover_url"] is not None
    items = api.client.get(f"/organizations/{body['slug']}/gallery").json()
    assert {item["id"] for item in items} == set(gallery)


def test_create_rejects_more_than_ten_gallery_files(
    api: ApiContext, owner: dict[str, str]
) -> None:
    ids = [str(uuid.uuid7()) for _ in range(11)]

    response = api.client.post(
        "/organizations",
        headers=owner,
        json={**ORG_FIELDS, "name": f"CLB {api.tag}", "gallery_asset_ids": ids},
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "too_long"
