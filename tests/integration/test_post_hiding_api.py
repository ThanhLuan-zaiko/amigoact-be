import uuid

from src.models.posts import OrgPost
from tests.activity_helpers import Bearer, user
from tests.conftest import ApiContext
from tests.media_helpers import db_row
from tests.post_helpers import created, join, open_org


def _ids(api: ApiContext, url: str, headers: dict[str, str] | None = None) -> list:
    response = api.client.get(url, headers=headers or {})
    assert response.status_code == 200, response.text
    return [item["id"] for item in response.json()["items"]]


def test_hide_removes_post_for_everyone_but_managers(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "hideown")
    member, _ = user(api, bearer, "hidemem")
    slug = open_org(api, owner)
    join(api, slug, member)
    notice = created(api, owner, slug, kind="announcement", title="An bai")
    api.client.post(f"/posts/{notice['id']}/pin", headers=owner)

    response = api.client.post(f"/posts/{notice['id']}/hide", headers=owner)

    assert response.status_code == 204
    row = db_row(OrgPost, uuid.UUID(notice["id"]))
    assert row.hidden_at is not None
    assert row.pinned_at is None
    assert notice["id"] not in _ids(api, f"/organizations/{slug}/posts", member)
    assert notice["id"] not in _ids(api, f"/organizations/{slug}/posts")
    assert notice["id"] not in _ids(api, "/feed/public")
    assert api.client.get(f"/posts/{notice['id']}", headers=member).status_code == 404

    manager_view = api.client.get(f"/organizations/{slug}/posts", headers=owner)
    item = next(p for p in manager_view.json()["items"] if p["id"] == notice["id"])
    assert item["hidden"] is True
    assert item["viewer"]["can_hide"] is True
    assert api.client.get(f"/posts/{notice['id']}", headers=owner).status_code == 200


def test_unhide_brings_the_post_back(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "unhown")
    slug = open_org(api, owner)
    notice = created(api, owner, slug, kind="announcement", title="Hien lai")
    api.client.post(f"/posts/{notice['id']}/hide", headers=owner)

    response = api.client.post(f"/posts/{notice['id']}/unhide", headers=owner)

    assert response.status_code == 204
    assert db_row(OrgPost, uuid.UUID(notice["id"])).hidden_at is None
    assert notice["id"] in _ids(api, f"/organizations/{slug}/posts")
    body = api.client.get(f"/posts/{notice['id']}").json()
    assert body["hidden"] is False
