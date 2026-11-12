"""A post can point at an activity of its organization and shows its summary."""

from tests.activity_helpers import Bearer, published, user
from tests.conftest import ApiContext
from tests.post_helpers import created, join, open_org


def test_post_shows_the_linked_activity(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "paown")
    slug = open_org(api, owner)
    activity = published(api, owner, slug, max_participants=10)

    post = created(api, owner, slug, kind="announcement", activity_id=activity["id"])

    linked = post["activity"]
    assert linked["id"] == activity["id"]
    assert linked["title"] == activity["title"]
    assert linked["status"] == "published"
    assert linked["capacity"] == 10
    assert linked["seats_taken"] == 0
    assert linked["organization_slug"] == slug
    public = api.client.get(f"/posts/{post['id']}").json()
    assert public["activity"]["id"] == activity["id"]


def test_post_without_activity_has_none(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "panone")
    slug = open_org(api, owner)

    assert created(api, owner, slug)["activity"] is None


def test_member_links_then_clears_an_activity(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "paedit")
    member, _ = user(api, bearer, "pamem")
    slug = open_org(api, owner)
    join(api, slug, member)
    activity = published(api, owner, slug)
    post = created(api, member, slug)

    linked = api.client.patch(
        f"/posts/{post['id']}", headers=member, json={"activity_id": activity["id"]}
    )
    renamed = api.client.patch(
        f"/posts/{post['id']}", headers=member, json={"title": "Doi ten"}
    )
    cleared = api.client.patch(
        f"/posts/{post['id']}", headers=member, json={"activity_id": None}
    )

    assert linked.status_code == 200, linked.text
    assert linked.json()["activity"]["id"] == activity["id"]
    assert renamed.json()["activity"]["id"] == activity["id"]
    assert cleared.json()["activity"] is None


def test_seats_taken_follow_registrations(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "paseat")
    volunteer, _ = user(api, bearer, "pavol")
    slug = open_org(api, owner)
    activity = published(api, owner, slug, max_participants=5)
    post = created(api, owner, slug, kind="announcement", activity_id=activity["id"])
    signed = api.client.post(
        f"/activities/{activity['id']}/registrations", headers=volunteer, json={}
    )
    assert signed.status_code == 201, signed.text

    body = api.client.get(f"/posts/{post['id']}").json()

    assert body["activity"]["seats_taken"] == 1
