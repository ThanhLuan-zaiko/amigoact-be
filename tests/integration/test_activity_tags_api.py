"""Activities carry tags from the organization catalog shared with posts."""

from typing import Any

from tests.activity_helpers import Bearer, draft, published, user
from tests.conftest import ApiContext
from tests.post_helpers import created, open_org


def _titles(api: ApiContext, path: str, **params: Any) -> list[str]:
    response = api.client.get(path, params=params)
    assert response.status_code == 200, response.text
    return [item["title"] for item in response.json()["items"]]


def test_created_activity_shows_its_tags(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "atown")
    slug = open_org(api, owner)

    item = published(
        api, owner, slug, tags=["Tr\u1ed3ng c\u00e2y", "M\u00f4i tr\u01b0\u1eddng"]
    )

    assert item["tags"] == ["M\u00f4i tr\u01b0\u1eddng", "Tr\u1ed3ng c\u00e2y"]
    listed = api.client.get(f"/organizations/{slug}/activities").json()["items"]
    assert listed[0]["tags"] == ["M\u00f4i tr\u01b0\u1eddng", "Tr\u1ed3ng c\u00e2y"]


def test_update_replaces_or_keeps_tags(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "atedit")
    slug = open_org(api, owner)
    item = draft(api, owner, slug, tags=["Cu"])
    path = f"/activities/{item['id']}"

    renamed = api.client.patch(path, headers=owner, json={"title": "Ten moi"})
    replaced = api.client.patch(path, headers=owner, json={"tags": ["Moi", "Hai"]})
    cleared = api.client.patch(path, headers=owner, json={"tags": []})

    assert renamed.json()["tags"] == ["Cu"]
    assert replaced.json()["tags"] == ["Hai", "Moi"]
    assert cleared.json()["tags"] == []


def test_lists_filter_by_tag(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "atfilter")
    slug = open_org(api, owner)
    tag = f"xanh-{api.tag}"
    published(api, owner, slug, title=f"Co the {api.tag}", tags=[tag])
    published(api, owner, slug, title=f"Khong the {api.tag}")

    org_list = _titles(api, f"/organizations/{slug}/activities", tag=tag)
    public = _titles(api, "/activities", q=api.tag, tag=tag)

    assert org_list == [f"Co the {api.tag}"]
    assert public == [f"Co the {api.tag}"]


def test_tags_are_shared_with_posts_and_suggested(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "atsug")
    slug = open_org(api, owner)
    created(api, owner, slug, tags=["M\u00f4i tr\u01b0\u1eddng"])
    published(api, owner, slug, tags=["moi truong"])
    published(api, owner, slug, tags=["Moi Truong", "Hien mau"])

    response = api.client.get(
        f"/organizations/{slug}/activity-tags", headers=owner, params={"q": "tru"}
    )

    assert response.status_code == 200, response.text
    # One catalog: the name first used, by the post, is the name everyone sees.
    assert response.json()["items"] == [
        {"name": "M\u00f4i tr\u01b0\u1eddng", "slug": "moi-truong", "count": 2}
    ]
