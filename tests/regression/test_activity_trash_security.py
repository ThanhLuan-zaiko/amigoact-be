"""Drafts and the activity trash stay with managers, and purging stays with the owner."""

import uuid

from src.models.activities import Activity
from tests.activity_helpers import Bearer, draft, published, user
from tests.conftest import ApiContext
from tests.post_helpers import backdate, join, open_org, promote


def _trashed(api: ApiContext, owner: dict[str, str], slug: str) -> str:
    item = draft(api, owner, slug)
    assert (
        api.client.delete(f"/activities/{item['id']}", headers=owner).status_code == 204
    )
    activity_id: str = item["id"]
    return activity_id


def test_only_managers_see_the_drafts_list(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "atsdraft")
    member, _ = user(api, bearer, "atsmem")
    slug = open_org(api, owner)
    join(api, slug, member)
    draft(api, owner, slug)
    path = f"/organizations/{slug}/activities"

    as_member = api.client.get(path, headers=member, params={"status": "draft"})
    as_visitor = api.client.get(path, params={"status": "draft"})

    assert as_member.status_code == 403
    assert as_visitor.status_code == 403
    assert api.client.get(path, headers=member).json()["items"] == []


def test_unknown_tab_is_refused(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "atstab")
    slug = open_org(api, owner)

    response = api.client.get(
        f"/organizations/{slug}/activities", params={"status": "deleted"}
    )

    assert response.status_code == 422


def test_members_cannot_see_or_restore_the_trash(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "atsmtr")
    member, _ = user(api, bearer, "atsmtm")
    stranger, _ = user(api, bearer, "atsout")
    slug = open_org(api, owner)
    join(api, slug, member)
    activity_id = _trashed(api, owner, slug)

    trash = api.client.get(f"/organizations/{slug}/activity-trash", headers=member)
    by_member = api.client.post(f"/activities/{activity_id}/restore", headers=member)
    by_stranger = api.client.post(
        f"/activities/{activity_id}/restore", headers=stranger
    )

    assert trash.status_code == 403
    assert by_member.status_code == 403
    # An outsider cannot even learn that the deleted draft exists.
    assert by_stranger.status_code == 404


def test_admin_restores_but_cannot_purge(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "atsadm")
    admin, admin_id = user(api, bearer, "atsadmin")
    slug = open_org(api, owner)
    join(api, slug, admin)
    promote(api, slug, owner, admin_id)
    activity_id = _trashed(api, owner, slug)

    trash = api.client.get(f"/organizations/{slug}/activity-trash", headers=admin)
    purge = api.client.delete(f"/activities/{activity_id}/purge", headers=admin)
    restore = api.client.post(f"/activities/{activity_id}/restore", headers=admin)

    assert trash.json()["items"][0]["can_purge"] is False
    assert purge.status_code == 403
    assert restore.status_code == 200, restore.text


def test_live_activity_cannot_be_restored_or_purged(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "atslive")
    slug = open_org(api, owner)
    live = published(api, owner, slug)

    restore = api.client.post(f"/activities/{live['id']}/restore", headers=owner)
    purge = api.client.delete(f"/activities/{live['id']}/purge", headers=owner)

    assert restore.status_code == 409
    assert restore.json()["detail"] == "activity_not_in_trash"
    assert purge.status_code == 409
    assert api.client.get(f"/activities/{live['id']}").status_code == 200


def test_expired_trash_is_purged_when_read(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "atsold")
    slug = open_org(api, owner)
    old_id = _trashed(api, owner, slug)
    backdate(Activity, uuid.UUID(old_id), "deleted_at", 31)

    restore = api.client.post(f"/activities/{old_id}/restore", headers=owner)
    trash = api.client.get(f"/organizations/{slug}/activity-trash", headers=owner)
    after = api.client.post(f"/activities/{old_id}/restore", headers=owner)

    assert restore.status_code == 404
    assert trash.json()["items"] == []
    assert after.status_code == 404
