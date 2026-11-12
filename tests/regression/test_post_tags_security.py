"""Tag suggestions must not leak tags of posts the members cannot see, or to outsiders."""

from tests.activity_helpers import Bearer, user
from tests.conftest import ApiContext
from tests.post_helpers import created, open_org


def _slugs(api: ApiContext, headers: dict[str, str], slug: str) -> list[str]:
    response = api.client.get(f"/organizations/{slug}/post-tags", headers=headers)
    assert response.status_code == 200, response.text
    return [item["slug"] for item in response.json()["items"]]


def test_outsiders_and_visitors_get_no_suggestions(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "tagsec")
    stranger, _ = user(api, bearer, "tagout")
    slug = open_org(api, owner)
    created(api, owner, slug, tags=["Bi mat"])

    outsider = api.client.get(f"/organizations/{slug}/post-tags", headers=stranger)
    visitor = api.client.get(f"/organizations/{slug}/post-tags")

    assert outsider.status_code == 403
    assert outsider.json()["detail"] == "post_forbidden"
    assert visitor.status_code == 401


def test_tags_on_drafts_deleted_or_hidden_posts_are_not_suggested(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "taghid")
    slug = open_org(api, owner)
    created(api, owner, slug, tags=["Ban nhap"], draft=True)
    gone = created(api, owner, slug, tags=["Da xoa"])
    hidden = created(api, owner, slug, tags=["Bi an"])
    created(api, owner, slug, tags=["Con song"])
    assert api.client.delete(f"/posts/{gone['id']}", headers=owner).status_code == 204
    hide = api.client.post(f"/posts/{hidden['id']}/hide", headers=owner)
    assert hide.status_code == 204

    assert _slugs(api, owner, slug) == ["con-song"]


def test_tags_of_another_organization_are_not_suggested(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "tagtwo")
    first = open_org(api, owner)
    second = open_org(api, owner)
    created(api, owner, first, tags=["Chi o day"])

    assert _slugs(api, owner, second) == []


def test_query_longer_than_a_tag_is_refused(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "taglong")
    slug = open_org(api, owner)

    response = api.client.get(
        f"/organizations/{slug}/post-tags", headers=owner, params={"q": "a" * 41}
    )

    assert response.status_code == 422
