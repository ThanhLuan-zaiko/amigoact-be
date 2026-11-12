"""Filtering by tag must keep every visibility rule and never fall back to all posts."""

from tests.activity_helpers import Bearer, user
from tests.conftest import ApiContext
from tests.post_helpers import created, open_org


def _titles(
    api: ApiContext, path: str, headers: dict[str, str] | None = None
) -> list[str]:
    response = api.client.get(path, headers=headers or {})
    assert response.status_code == 200, response.text
    return [item["title"] for item in response.json()["items"]]


def test_visitors_do_not_get_member_posts_through_a_tag(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "tfsec")
    slug = open_org(api, owner)
    tag = f"noi-bo-{api.tag}"
    created(api, owner, slug, title="Chi thanh vien", tags=[tag])
    created(api, owner, slug, kind="announcement", title="Cong khai", tags=[tag])

    assert _titles(api, f"/organizations/{slug}/posts?tag={tag}") == ["Cong khai"]
    assert _titles(api, f"/feed/public?tag={tag}") == ["Cong khai"]


def test_drafts_and_deleted_posts_stay_out_of_a_tag(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "tfdraft")
    slug = open_org(api, owner)
    created(api, owner, slug, title="Nhap", tags=["loc"], draft=True)
    gone = created(api, owner, slug, title="Da xoa", tags=["loc"])
    created(api, owner, slug, title="Con", tags=["loc"])
    assert api.client.delete(f"/posts/{gone['id']}", headers=owner).status_code == 204

    assert _titles(api, f"/organizations/{slug}/posts?tag=loc", owner) == ["Con"]


def test_tag_without_letters_finds_nothing_instead_of_everything(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "tfsym")
    slug = open_org(api, owner)
    created(api, owner, slug, title="Bai", tags=["loc"])

    assert _titles(api, f"/organizations/{slug}/posts?tag=%25%25", owner) == []


def test_empty_or_long_tag_is_refused(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "tflong")
    slug = open_org(api, owner)

    empty = api.client.get(f"/organizations/{slug}/posts?tag=", headers=owner)
    long = api.client.get(f"/feed/public?tag={'a' * 41}")

    assert empty.status_code == 422
    assert long.status_code == 422
