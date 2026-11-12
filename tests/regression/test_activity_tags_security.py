"""Activity tags keep the activity rules: drafts stay hidden, managers write."""

from tests.activity_helpers import Bearer, draft, published, user
from tests.conftest import ApiContext
from tests.post_helpers import join, open_org


def test_tag_filter_never_shows_drafts(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "atsdraft")
    slug = open_org(api, owner)
    tag = f"an-{api.tag}"
    draft(api, owner, slug, tags=[tag])

    org_list = api.client.get(
        f"/organizations/{slug}/activities", headers=owner, params={"tag": tag}
    )
    public = api.client.get("/activities", params={"tag": tag})

    assert org_list.json()["items"] == []
    assert public.json()["items"] == []


def test_only_managers_get_activity_tag_suggestions(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "atsmgr")
    member, _ = user(api, bearer, "atsmember")
    slug = open_org(api, owner)
    join(api, slug, member)
    published(api, owner, slug, tags=["Noi bo"])
    path = f"/organizations/{slug}/activity-tags"

    as_member = api.client.get(path, headers=member)
    as_visitor = api.client.get(path)

    assert as_member.status_code == 403
    assert as_visitor.status_code == 401


def test_bad_tags_are_refused(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "atsbad")
    slug = open_org(api, owner)
    path = f"/organizations/{slug}/activities"
    base = {
        "title": "Hoat dong",
        "description": "Mo ta",
        "city": "Ha Noi",
        "hours_awarded": "2",
        "location": "San",
        "start_at": "2030-01-01T08:00:00+07:00",
        "end_at": "2030-01-01T10:00:00+07:00",
    }

    symbols = api.client.post(path, headers=owner, json={**base, "tags": ["!!!"]})
    too_many = api.client.post(
        path, headers=owner, json={**base, "tags": ["a", "b", "c", "d", "e", "f"]}
    )
    not_list = api.client.post(path, headers=owner, json={**base, "tags": "a,b"})

    assert symbols.status_code == 422
    assert "tag_invalid" in symbols.text
    assert too_many.status_code == 422
    assert not_list.status_code == 422


def test_empty_or_long_tag_filter_is_refused(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "atslong")
    slug = open_org(api, owner)

    empty = api.client.get(f"/organizations/{slug}/activities", params={"tag": ""})
    long = api.client.get("/activities", params={"tag": "a" * 41})
    symbols = api.client.get(f"/organizations/{slug}/activities", params={"tag": "%%"})

    assert empty.status_code == 422
    assert long.status_code == 422
    assert symbols.json()["items"] == []
