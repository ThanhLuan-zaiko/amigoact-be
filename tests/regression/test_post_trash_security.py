"""Lock in who may see the trash, restore, purge, and change comments."""

from typing import Any

from tests.activity_helpers import Bearer, Headers, user
from tests.conftest import ApiContext
from tests.post_helpers import comment, created, join, open_org, promote


def _trashed(
    api: ApiContext, bearer: Bearer, name: str
) -> tuple[Headers, str, dict[str, Any]]:
    owner, _ = user(api, bearer, name)
    slug = open_org(api, owner)
    item = created(api, owner, slug, kind="announcement", title="Trong thung rac")
    assert api.client.delete(f"/posts/{item['id']}", headers=owner).status_code == 204
    return owner, slug, item


def test_member_cannot_read_the_trash(api: ApiContext, bearer: Bearer) -> None:
    _owner, slug, _item = _trashed(api, bearer, "t1")
    member, _ = user(api, bearer, "t1m")
    join(api, slug, member)

    response = api.client.get(f"/organizations/{slug}/post-trash", headers=member)

    assert response.status_code == 403
    assert response.json()["detail"] == "post_forbidden"


def test_visitor_cannot_read_the_trash(api: ApiContext, bearer: Bearer) -> None:
    _owner, slug, _item = _trashed(api, bearer, "t2")
    assert api.client.get(f"/organizations/{slug}/post-trash").status_code == 401


def test_outsider_cannot_learn_a_deleted_post_exists(
    api: ApiContext, bearer: Bearer
) -> None:
    _owner, _slug, item = _trashed(api, bearer, "t3")
    stranger, _ = user(api, bearer, "t3s")

    restore = api.client.post(f"/posts/{item['id']}/restore", headers=stranger)
    purge = api.client.delete(f"/posts/{item['id']}/purge", headers=stranger)

    assert restore.status_code == 404
    assert purge.status_code == 404


def test_admin_cannot_purge(api: ApiContext, bearer: Bearer) -> None:
    owner, slug, item = _trashed(api, bearer, "t4")
    admin, admin_id = user(api, bearer, "t4a")
    join(api, slug, admin)
    promote(api, slug, owner, admin_id)

    response = api.client.delete(f"/posts/{item['id']}/purge", headers=admin)
    trash = api.client.get(f"/organizations/{slug}/post-trash", headers=admin).json()

    assert response.status_code == 403
    assert trash["items"][0]["can_purge"] is False


def test_purge_refuses_a_live_post(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "t5")
    slug = open_org(api, owner)
    item = created(api, owner, slug, kind="announcement")

    response = api.client.delete(f"/posts/{item['id']}/purge", headers=owner)

    assert response.status_code == 409
    assert response.json()["detail"] == "post_not_in_trash"
    assert api.client.get(f"/posts/{item['id']}").status_code == 200


def test_restore_refuses_a_live_post(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "t6")
    slug = open_org(api, owner)
    item = created(api, owner, slug, kind="announcement")

    response = api.client.post(f"/posts/{item['id']}/restore", headers=owner)

    assert response.status_code == 409
    assert response.json()["detail"] == "post_not_in_trash"


def test_deleted_post_leaves_every_list(api: ApiContext, bearer: Bearer) -> None:
    owner, slug, item = _trashed(api, bearer, "t7")

    timeline = api.client.get(f"/organizations/{slug}/posts").json()["items"]
    public = api.client.get("/feed/public?limit=50").json()["items"]
    mine = api.client.get("/feed?limit=50", headers=owner).json()["items"]

    for page in (timeline, public, mine):
        assert item["id"] not in {post["id"] for post in page}


def test_deleted_draft_is_gone_for_its_author_too(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "t8")
    slug = open_org(api, owner)
    draft = created(api, owner, slug, title="Nhap rieng", draft=True)

    response = api.client.delete(f"/posts/{draft['id']}", headers=owner)
    again = api.client.delete(f"/posts/{draft['id']}", headers=owner)
    restore = api.client.post(f"/posts/{draft['id']}/restore", headers=owner)

    assert response.status_code == 204
    assert again.status_code == 404
    assert restore.status_code == 404


def test_comment_rules_hold(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "t9")
    member, _ = user(api, bearer, "t9m")
    slug = open_org(api, owner)
    join(api, slug, member)
    item = created(api, owner, slug, kind="announcement")
    note = comment(api, member, item["id"], "Rieng tu").json()
    path = f"/comments/{note['id']}"

    # Even a manager cannot change the words of a member.
    assert api.client.patch(path, headers=owner, json={"body": "X"}).status_code == 403
    # A member cannot restore, and a deleted comment cannot be deleted twice.
    assert api.client.delete(path, headers=member).status_code == 204
    assert api.client.delete(path, headers=member).status_code == 404
    assert api.client.post(f"{path}/restore", headers=member).status_code == 403
    assert api.client.patch(path, headers=member, json={"body": "Y"}).status_code == 404
    # The text of a deleted comment never leaves the server.
    listed = api.client.get(f"/posts/{item['id']}/comments", headers=owner).json()
    assert "Rieng tu" not in str(listed)
    # Restoring a live comment is a conflict.
    assert api.client.post(f"{path}/restore", headers=owner).status_code == 200
    again = api.client.post(f"{path}/restore", headers=owner)
    assert again.status_code == 409
    assert again.json()["detail"] == "comment_not_deleted"


def test_comment_edit_body_is_validated(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "t10")
    slug = open_org(api, owner)
    item = created(api, owner, slug, kind="announcement")
    note = comment(api, owner, item["id"], "Goc").json()
    path = f"/comments/{note['id']}"

    empty = api.client.patch(path, headers=owner, json={"body": "   "})
    extra = api.client.patch(path, headers=owner, json={"body": "Ok", "author": "x"})
    number = api.client.patch(path, headers=owner, json={"body": 5})

    assert empty.json()["detail"][0]["type"] == "string_too_short"
    assert extra.json()["detail"][0]["type"] == "extra_forbidden"
    assert number.json()["detail"][0]["type"] == "string_type"
