"""GET /feed/all: the home feed mixes public posts with the viewer's own organizations."""

from tests.activity_helpers import Bearer, user
from tests.conftest import ApiContext
from tests.post_helpers import created, join, open_org


def _titles(
    api: ApiContext, path: str, headers: dict[str, str] | None = None
) -> list[str]:
    response = api.client.get(path, headers=headers or {})
    assert response.status_code == 200, response.text
    return [item["title"] for item in response.json()["items"]]


def test_home_feed_mixes_public_posts_with_own_member_posts(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "allown")
    other_owner, _ = user(api, bearer, "allother")
    member, _ = user(api, bearer, "allmem")
    own_org = open_org(api, owner)
    other_org = open_org(api, other_owner)
    join(api, own_org, member)
    created(api, owner, own_org, kind="announcement", title="Cong khai nha minh")
    created(api, owner, own_org, kind="discussion", title="Noi bo nha minh")
    created(api, other_owner, other_org, kind="announcement", title="Cong khai la")
    created(api, other_owner, other_org, kind="discussion", title="Noi bo la")

    titles = _titles(api, "/feed/all", member)

    assert "Cong khai nha minh" in titles
    assert "Noi bo nha minh" in titles
    assert "Cong khai la" in titles
    assert "Noi bo la" not in titles


def test_visitors_see_only_public_posts_in_home_feed(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "allguest")
    slug = open_org(api, owner)
    created(api, owner, slug, kind="announcement", title="Guest cong khai")
    created(api, owner, slug, kind="discussion", title="Guest noi bo")

    titles = _titles(api, "/feed/all")

    assert "Guest cong khai" in titles
    assert "Guest noi bo" not in titles


def test_home_feed_filters_by_tag(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "alltag")
    member, _ = user(api, bearer, "alltagmem")
    slug = open_org(api, owner)
    join(api, slug, member)
    tag = f"tat-ca-{api.tag}"
    created(api, owner, slug, kind="discussion", title="Co the", tags=[tag])
    created(api, owner, slug, kind="discussion", title="Khong the")

    assert _titles(api, f"/feed/all?tag={tag}", member) == ["Co the"]
