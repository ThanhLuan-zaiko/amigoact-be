import uuid
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.conftest import ORG_FIELDS, ApiContext

Bearer = Callable[[str], dict[str, str]]
PNG = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def owner(api: ApiContext, bearer: Bearer, media_root: Path) -> dict[str, str]:
    return bearer(api.register("owner")["tokens"]["access_token"])


def upload(api: ApiContext, headers: dict[str, str], head: bytes) -> str:
    body = head + uuid.uuid4().bytes
    response = api.client.post("/media", headers=headers, files={"file": ("f", body)})
    assert response.status_code == 201, response.text
    asset_id: str = response.json()["id"]
    return asset_id


def test_create_refuses_someone_elses_gallery_file_and_creates_nothing(
    api: ApiContext, owner: dict[str, str], bearer: Bearer
) -> None:
    other = bearer(api.register("other")["tokens"]["access_token"])
    foreign = upload(api, other, PNG)
    name = f"CLB {api.tag}"

    response = api.client.post(
        "/organizations",
        headers=owner,
        json={**ORG_FIELDS, "name": name, "gallery_asset_ids": [foreign]},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "media_not_found"
    listed = api.client.get("/organizations", params={"q": name}).json()
    assert listed["total"] == 0


def test_repeated_gallery_file_becomes_one_item(
    api: ApiContext, owner: dict[str, str]
) -> None:
    asset = upload(api, owner, PNG)

    created = api.client.post(
        "/organizations",
        headers=owner,
        json={
            **ORG_FIELDS,
            "name": f"CLB {api.tag}",
            "gallery_asset_ids": [asset, asset],
        },
    )

    assert created.status_code == 201, created.text
    items = api.client.get(f"/organizations/{created.json()['slug']}/gallery").json()
    assert [item["id"] for item in items] == [asset]
