"""A post must never point at an activity people cannot see or join."""

import uuid

from src.models.activities import Activity
from tests.activity_helpers import Bearer, draft, published, user
from tests.conftest import ApiContext
from tests.post_helpers import backdate, created, open_org, post


def test_draft_activity_cannot_be_linked(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "pasdraft")
    slug = open_org(api, owner)
    hidden = draft(api, owner, slug)

    response = post(api, owner, slug, activity_id=hidden["id"])

    assert response.status_code == 422
    assert "activity_not_linkable" in response.text


def test_activity_of_another_organization_cannot_be_linked(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "pasother")
    mine = open_org(api, owner)
    other = open_org(api, owner)
    foreign = published(api, owner, other)

    response = post(api, owner, mine, activity_id=foreign["id"])

    assert response.status_code == 422
    assert "activity_not_linkable" in response.text


def test_missing_or_cancelled_activity_cannot_be_linked(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "pascancel")
    slug = open_org(api, owner)
    activity = published(api, owner, slug)
    cancel = api.client.post(f"/activities/{activity['id']}/cancel", headers=owner)
    assert cancel.status_code == 200, cancel.text

    cancelled = post(api, owner, slug, activity_id=activity["id"])
    missing = post(api, owner, slug, activity_id=str(uuid.uuid7()))

    assert cancelled.status_code == 422
    assert missing.status_code == 422


def test_cancelled_later_stays_linked_and_deleted_disappears(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "paslater")
    slug = open_org(api, owner)
    first = published(api, owner, slug)
    second = published(api, owner, slug)
    about_first = created(
        api, owner, slug, kind="announcement", activity_id=first["id"]
    )
    about_second = created(
        api, owner, slug, kind="announcement", activity_id=second["id"]
    )
    cancel = api.client.post(f"/activities/{first['id']}/cancel", headers=owner)
    assert cancel.status_code == 200, cancel.text
    backdate(Activity, uuid.UUID(second["id"]), "deleted_at", 0)

    first_body = api.client.get(f"/posts/{about_first['id']}").json()
    second_body = api.client.get(f"/posts/{about_second['id']}").json()

    assert first_body["activity"]["status"] == "cancelled"
    assert second_body["activity"] is None


def test_post_about_a_cancelled_activity_can_still_be_edited(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "paskeep")
    slug = open_org(api, owner)
    activity = published(api, owner, slug)
    item = created(api, owner, slug, kind="announcement", activity_id=activity["id"])
    cancel = api.client.post(f"/activities/{activity['id']}/cancel", headers=owner)
    assert cancel.status_code == 200, cancel.text

    # The edit form sends the activity it already has along with the new title.
    response = api.client.patch(
        f"/posts/{item['id']}",
        headers=owner,
        json={"title": "Da huy", "activity_id": activity["id"]},
    )

    assert response.status_code == 200, response.text
    assert response.json()["activity"]["status"] == "cancelled"


def test_activity_id_must_be_a_uuid7_and_body_stays_strict(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "passtrict")
    slug = open_org(api, owner)

    old_style = post(api, owner, slug, activity_id=str(uuid.uuid4()))
    forged = post(api, owner, slug, activity={"id": str(uuid.uuid7())})

    assert old_style.status_code == 422
    assert forged.status_code == 422
