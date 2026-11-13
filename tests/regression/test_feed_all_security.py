"""GET /feed/all must never show members-only posts to people outside their organization."""

from tests.activity_helpers import Bearer, user
from tests.conftest import ApiContext
from tests.post_helpers import created, join, open_org


def _ids(api: ApiContext, headers: dict[str, str] | None = None) -> list[str]:
    response = api.client.get("/feed/all", headers=headers or {})
    assert response.status_code == 200, response.text
    return [item["id"] for item in response.json()["items"]]


def test_members_only_posts_stay_out_of_other_visitors_home_feed(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "feedsec")
    member, _ = user(api, bearer, "feedsecmem")
    outsider, _ = user(api, bearer, "feedsecout")
    slug = open_org(api, owner)
    join(api, slug, member)
    secret = created(api, member, slug, title="Chi thanh vien", body="Bi mat")

    assert secret["id"] not in _ids(api, outsider)
    assert secret["id"] not in _ids(api)
    assert secret["id"] in _ids(api, member)


def test_drafts_stay_out_of_the_home_feed(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "feeddraft")
    slug = open_org(api, owner)
    draft = created(api, owner, slug, kind="announcement", draft=True)

    assert draft["id"] not in _ids(api, owner)
    assert draft["id"] not in _ids(api)
