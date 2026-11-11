from pathlib import Path
from typing import Any

from tests.activity_helpers import Bearer, Headers, make_org, user
from tests.attendance_helpers import attended_activity
from tests.conftest import ApiContext
from tests.media_helpers import uploaded

LAYOUT = {
    "name": {"x": 20.5, "y": 40, "size": 36},
    "activity": {"x": 50, "y": 55, "size": 18},
    "hours": {"x": 50, "y": 62, "size": 14},
    "date": {"x": 50, "y": 70, "size": 12},
    "serial": {"x": 80, "y": 95, "size": 9},
}


def issue(
    api: ApiContext, owner: Headers, activity_id: str, **body: Any
) -> dict[str, Any]:
    path = f"/activities/{activity_id}/certificates"
    response = api.client.post(path, headers=owner, json=body)
    assert response.status_code == 200, response.text
    item: dict[str, Any] = api.client.get(path, headers=owner).json()["items"][0]
    return item


def test_verify_and_mine_show_the_template_design(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    owner, _ = user(api, bearer, "designer")
    volunteer, _ = user(api, bearer, "designvol")
    slug = make_org(api, owner)
    background = uploaded(api, owner)
    template = api.client.post(
        f"/organizations/{slug}/certificate-templates",
        headers=owner,
        json={
            "name": "Giay khen",
            "background_asset_id": background["id"],
            "layout": LAYOUT,
        },
    ).json()
    activity = attended_activity(api, owner, volunteer, slug=slug)
    item = issue(api, owner, activity["id"], template_id=template["id"])

    public = api.client.get(f"/certificates/verify/{item['serial_no']}")
    mine = api.client.get("/certificates/mine", headers=volunteer)

    assert public.status_code == 200, public.text
    expected = {"background_url": background["url"], "layout": LAYOUT}
    assert public.json()["design"] == expected
    assert mine.status_code == 200
    assert mine.json()[0]["design"] == expected
    # The printed page needs the picture without a login.
    assert api.client.get(background["url"]).status_code == 200


def test_certificate_without_template_has_no_design(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "nodesign")
    volunteer, _ = user(api, bearer, "nodesignvol")
    activity = attended_activity(api, owner, volunteer)
    item = issue(api, owner, activity["id"])

    public = api.client.get(f"/certificates/verify/{item['serial_no']}").json()
    mine = api.client.get("/certificates/mine", headers=volunteer).json()

    assert public["design"] is None
    assert mine[0]["design"] is None
