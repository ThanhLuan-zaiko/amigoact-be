"""The post lists take ?tag= to show only posts with that tag."""

from tests.activity_helpers import Bearer, user
from tests.conftest import ApiContext
from tests.post_helpers import created, join, open_org


def _titles(
    api: ApiContext, path: str, headers: dict[str, str] | None = None
) -> list[str]:
    response = api.client.get(path, headers=headers or {})
    assert response.status_code == 200, response.text
    return [item["title"] for item in response.json()["items"]]


def test_org_posts_filter_by_slug_or_typed_name(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "tfown")
    slug = open_org(api, owner)
    created(api, owner, slug, title="Trong cay", tags=["M\u00f4i tr\u01b0\u1eddng"])
    created(api, owner, slug, title="Hien mau", tags=["Hi\u1ebfn m\u00e1u"])
    created(api, owner, slug, title="Khong the")

    by_slug = _titles(api, f"/organizations/{slug}/posts?tag=moi-truong", owner)
    by_name = _titles(
        api, f"/organizations/{slug}/posts?tag=M\u00f4i tr\u01b0\u1eddng", owner
    )

    assert by_slug == ["Trong cay"]
    assert by_name == ["Trong cay"]


def test_tag_filter_combines_with_kind(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "tfkind")
    slug = open_org(api, owner)
    created(api, owner, slug, kind="announcement", title="Thong bao", tags=["sk"])
    created(api, owner, slug, title="Thao luan", tags=["sk"])

    titles = _titles(
        api, f"/organizations/{slug}/posts?tag=sk&kind=announcement", owner
    )

    assert titles == ["Thong bao"]


def test_public_feed_by_tag_spans_organizations(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "tfpub")
    first = open_org(api, owner)
    second = open_org(api, owner)
    tag = f"chung-{api.tag}"
    created(api, owner, first, kind="announcement", title="Mot", tags=[tag])
    created(api, owner, second, kind="announcement", title="Hai", tags=[tag])
    created(api, owner, second, kind="announcement", title="Khac")

    assert _titles(api, f"/feed/public?tag={tag}") == ["Hai", "Mot"]


def test_member_feed_by_tag(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "tfmine")
    member, _ = user(api, bearer, "tfmem")
    slug = open_org(api, owner)
    join(api, slug, member)
    tag = f"rieng-{api.tag}"
    created(api, owner, slug, title="Co the", tags=[tag])
    created(api, owner, slug, title="Khong the")

    assert _titles(api, f"/feed?tag={tag}", member) == ["Co the"]
