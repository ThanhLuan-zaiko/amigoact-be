import uuid
from collections.abc import Callable
from pathlib import Path

import pytest

from src.organizations.gallery import MAX_GALLERY_ITEMS
from tests.conftest import ORG_FIELDS, ApiContext

Bearer = Callable[[str], dict[str, str]]
PNG = b"\x89PNG\r\n\x1a\n"
MP4 = b"\x00\x00\x00\x18ftypmp42"


@pytest.fixture
def owner(api: ApiContext, bearer: Bearer, media_root: Path) -> dict[str, str]:
    return bearer(api.register("owner")["tokens"]["access_token"])


def make_org(api: ApiContext, headers: dict[str, str]) -> str:
    response = api.client.post(
        "/organizations", headers=headers, json={**ORG_FIELDS, "name": f"CLB {api.tag}"}
    )
    assert response.status_code == 201, response.text
    slug: str = response.json()["slug"]
    return slug


def upload(api: ApiContext, headers: dict[str, str], head: bytes) -> str:
    body = head + uuid.uuid4().bytes
    response = api.client.post("/media", headers=headers, files={"file": ("f", body)})
    assert response.status_code == 201, response.text
    asset_id: str = response.json()["id"]
    return asset_id


def test_manager_adds_pictures_and_videos_and_anyone_reads(
    api: ApiContext, owner: dict[str, str]
) -> None:
    slug = make_org(api, owner)
    for head in (PNG, MP4):
        added = api.client.post(
            f"/organizations/{slug}/gallery",
            headers=owner,
            json={"asset_id": upload(api, owner, head)},
        )
        assert added.status_code == 201, added.text

    items = api.client.get(f"/organizations/{slug}/gallery").json()

    assert {item["mime"] for item in items} == {"image/png", "video/mp4"}
    # Attached files become public, so a visitor can open them.
    assert api.client.get(items[1]["url"]).status_code == 200


def test_remove_takes_an_item_out(api: ApiContext, owner: dict[str, str]) -> None:
    slug = make_org(api, owner)
    asset_id = upload(api, owner, PNG)
    path = f"/organizations/{slug}/gallery"
    api.client.post(path, headers=owner, json={"asset_id": asset_id})

    assert api.client.delete(f"{path}/{asset_id}", headers=owner).status_code == 204
    assert api.client.get(path).json() == []
    missing = api.client.delete(f"{path}/{asset_id}", headers=owner)
    assert missing.status_code == 404


def test_gallery_stops_at_the_limit(api: ApiContext, owner: dict[str, str]) -> None:
    slug = make_org(api, owner)
    path = f"/organizations/{slug}/gallery"
    for _ in range(MAX_GALLERY_ITEMS):
        added = api.client.post(
            path, headers=owner, json={"asset_id": upload(api, owner, PNG)}
        )
        assert added.status_code == 201, added.text

    response = api.client.post(
        path, headers=owner, json={"asset_id": upload(api, owner, PNG)}
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "gallery_full"


def test_list_reports_the_total_across_pages(
    api: ApiContext, owner: dict[str, str]
) -> None:
    make_org(api, owner)
    make_org(api, owner)

    body = api.client.get("/organizations", params={"q": api.tag, "limit": 1}).json()

    assert body["total"] == 2
    assert len(body["items"]) == 1
