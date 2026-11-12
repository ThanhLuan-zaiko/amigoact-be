"""The organization activity list has tabs, a drafts list, and a trash."""

import uuid

from src.models.activities import Activity
from tests.activity_helpers import Bearer, at, draft, published, user
from tests.conftest import ApiContext
from tests.post_helpers import backdate, open_org


def _ids(
    api: ApiContext, slug: str, headers: dict[str, str], **params: str
) -> list[str]:
    response = api.client.get(
        f"/organizations/{slug}/activities", headers=headers, params=params
    )
    assert response.status_code == 200, response.text
    return [item["id"] for item in response.json()["items"]]


def test_tabs_split_activities_by_status(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "altabs")
    slug = open_org(api, owner)
    later = published(api, owner, slug, start_at=at(20), end_at=at(21))
    sooner = published(api, owner, slug)
    done = published(api, owner, slug)
    backdate(Activity, uuid.UUID(done["id"]), "start_at", 1)
    finish = api.client.post(f"/activities/{done['id']}/complete", headers=owner)
    assert finish.status_code == 200, finish.text
    dropped = published(api, owner, slug)
    cancel = api.client.post(f"/activities/{dropped['id']}/cancel", headers=owner)
    assert cancel.status_code == 200, cancel.text
    hidden = draft(api, owner, slug)

    everything = _ids(api, slug, owner)

    assert set(everything) == {later["id"], sooner["id"], done["id"], dropped["id"]}
    assert _ids(api, slug, owner, status="upcoming") == [sooner["id"], later["id"]]
    assert _ids(api, slug, owner, status="completed") == [done["id"]]
    assert _ids(api, slug, owner, status="cancelled") == [dropped["id"]]
    assert _ids(api, slug, owner, status="draft") == [hidden["id"]]


def test_deleted_draft_goes_to_trash_and_comes_back(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "altrash")
    slug = open_org(api, owner)
    item = draft(api, owner, slug)
    assert (
        api.client.delete(f"/activities/{item['id']}", headers=owner).status_code == 204
    )

    trash = api.client.get(f"/organizations/{slug}/activity-trash", headers=owner)
    assert trash.status_code == 200, trash.text
    [entry] = trash.json()["items"]
    assert entry["id"] == item["id"]
    assert entry["title"] == item["title"]
    assert entry["can_purge"] is True
    assert _ids(api, slug, owner, status="draft") == []

    restored = api.client.post(f"/activities/{item['id']}/restore", headers=owner)

    assert restored.status_code == 200, restored.text
    assert restored.json()["status"] == "draft"
    assert _ids(api, slug, owner, status="draft") == [item["id"]]
    again = api.client.get(f"/organizations/{slug}/activity-trash", headers=owner)
    assert again.json()["items"] == []


def test_owner_purges_a_trashed_draft(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "alpurge")
    slug = open_org(api, owner)
    item = draft(api, owner, slug)
    api.client.delete(f"/activities/{item['id']}", headers=owner)

    purged = api.client.delete(f"/activities/{item['id']}/purge", headers=owner)

    assert purged.status_code == 204
    trash = api.client.get(f"/organizations/{slug}/activity-trash", headers=owner)
    assert trash.json()["items"] == []
    gone = api.client.post(f"/activities/{item['id']}/restore", headers=owner)
    assert gone.status_code == 404
