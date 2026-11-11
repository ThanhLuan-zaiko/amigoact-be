from pathlib import Path

from tests.activity_helpers import Bearer, make_org, user
from tests.conftest import ApiContext
from tests.media_helpers import uploaded


def test_manager_reads_one_template(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    owner, _ = user(api, bearer, "reader")
    slug = make_org(api, owner)
    background = uploaded(api, owner)
    created = api.client.post(
        f"/organizations/{slug}/certificate-templates",
        headers=owner,
        json={"name": "Giay khen", "background_asset_id": background["id"]},
    ).json()

    response = api.client.get(f"/certificate-templates/{created['id']}", headers=owner)

    assert response.status_code == 200, response.text
    assert response.json() == created


def test_read_shows_the_latest_change(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "latest")
    slug = make_org(api, owner)
    created = api.client.post(
        f"/organizations/{slug}/certificate-templates",
        headers=owner,
        json={"name": "Ban dau"},
    ).json()
    api.client.patch(
        f"/certificate-templates/{created['id']}",
        headers=owner,
        json={"name": "Da doi", "is_active": False},
    )

    body = api.client.get(
        f"/certificate-templates/{created['id']}", headers=owner
    ).json()

    assert body["name"] == "Da doi"
    assert body["is_active"] is False
