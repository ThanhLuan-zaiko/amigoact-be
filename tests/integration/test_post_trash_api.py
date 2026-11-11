import uuid

from src.models.posts import OrgPost, PostComment
from tests.activity_helpers import Bearer, user
from tests.conftest import ApiContext
from tests.media_helpers import db_row
from tests.post_helpers import backdate, comment, created, join, open_org, promote


def test_deleting_a_draft_removes_it_for_good(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "drafter")
    slug = open_org(api, owner)
    draft = created(api, owner, slug, title="Nhap", draft=True)

    response = api.client.delete(f"/posts/{draft['id']}", headers=owner)

    assert response.status_code == 204
    assert db_row(OrgPost, uuid.UUID(draft["id"])) is None
    trash = api.client.get(f"/organizations/{slug}/post-trash", headers=owner)
    assert trash.json()["items"] == []


def test_deleting_a_post_moves_it_to_the_trash(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "trasher")
    slug = open_org(api, owner)
    item = created(api, owner, slug, kind="announcement", title="Bai cu")
    api.client.post(f"/posts/{item['id']}/pin", headers=owner)

    assert api.client.delete(f"/posts/{item['id']}", headers=owner).status_code == 204

    row = db_row(OrgPost, uuid.UUID(item["id"]))
    assert row.deleted_at is not None
    assert row.pinned_at is None
    assert api.client.get(f"/posts/{item['id']}").status_code == 404
    page = api.client.get(f"/organizations/{slug}/post-trash", headers=owner).json()
    assert [entry["id"] for entry in page["items"]] == [item["id"]]
    entry = page["items"][0]
    assert entry["title"] == "Bai cu"
    assert entry["deleted_by_name"] == "Test User"
    assert entry["can_purge"] is True
    assert entry["purge_at"] > entry["deleted_at"]
    assert page["next_before"] is None


def test_admin_restores_a_post(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "rest-own")
    admin, admin_id = user(api, bearer, "rest-adm")
    slug = open_org(api, owner)
    join(api, slug, admin)
    promote(api, slug, owner, admin_id)
    item = created(api, owner, slug, kind="announcement", title="Quay lai")
    api.client.delete(f"/posts/{item['id']}", headers=owner)

    response = api.client.post(f"/posts/{item['id']}/restore", headers=admin)

    assert response.status_code == 200
    assert response.json()["id"] == item["id"]
    assert db_row(OrgPost, uuid.UUID(item["id"])).deleted_by is None
    timeline = api.client.get(f"/organizations/{slug}/posts").json()["items"]
    assert [post["id"] for post in timeline] == [item["id"]]


def test_owner_purges_a_post_with_its_comments(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "purger")
    slug = open_org(api, owner)
    item = created(api, owner, slug, kind="announcement", title="Xoa han")
    note = comment(api, owner, item["id"], "Binh luan").json()
    api.client.delete(f"/posts/{item['id']}", headers=owner)

    response = api.client.delete(f"/posts/{item['id']}/purge", headers=owner)

    assert response.status_code == 204
    assert db_row(OrgPost, uuid.UUID(item["id"])) is None
    assert db_row(PostComment, uuid.UUID(note["id"])) is None


def test_trash_removes_posts_past_the_keep_period(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "expiry")
    slug = open_org(api, owner)
    old = created(api, owner, slug, kind="announcement", title="Qua han")
    fresh = created(api, owner, slug, kind="announcement", title="Con han")
    api.client.delete(f"/posts/{old['id']}", headers=owner)
    api.client.delete(f"/posts/{fresh['id']}", headers=owner)
    backdate(OrgPost, uuid.UUID(old["id"]), "deleted_at", 31)

    page = api.client.get(f"/organizations/{slug}/post-trash", headers=owner).json()

    assert [entry["id"] for entry in page["items"]] == [fresh["id"]]
    assert db_row(OrgPost, uuid.UUID(old["id"])) is None


def test_author_edits_a_comment_shortly_after(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "editor")
    slug = open_org(api, owner)
    item = created(api, owner, slug, kind="announcement")
    note = comment(api, owner, item["id"], "Ban dau").json()
    assert note["can_edit"] is True

    response = api.client.patch(
        f"/comments/{note['id']}", headers=owner, json={"body": "Da sua"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["body"] == "Da sua"
    assert body["edited_at"] is not None


def test_comment_edit_window_closes(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "late")
    slug = open_org(api, owner)
    item = created(api, owner, slug, kind="announcement")
    note = comment(api, owner, item["id"], "Cu").json()
    backdate(PostComment, uuid.UUID(note["id"]), "created_at", 1)

    response = api.client.patch(
        f"/comments/{note['id']}", headers=owner, json={"body": "Moi"}
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "comment_edit_expired"
    listed = api.client.get(f"/posts/{item['id']}/comments", headers=owner).json()
    assert listed["items"][0]["can_edit"] is False


def test_manager_restores_a_deleted_comment(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "c-own")
    member, _ = user(api, bearer, "c-mem")
    slug = open_org(api, owner)
    join(api, slug, member)
    item = created(api, owner, slug, kind="announcement")
    note = comment(api, member, item["id"], "Xin chao").json()
    api.client.delete(f"/comments/{note['id']}", headers=member)
    listed = api.client.get(f"/posts/{item['id']}/comments", headers=owner).json()
    assert listed["items"][0]["can_restore"] is True

    response = api.client.post(f"/comments/{note['id']}/restore", headers=owner)

    assert response.status_code == 200
    body = response.json()
    assert (body["body"], body["deleted"], body["author_name"]) == (
        "Xin chao",
        False,
        "Test User",
    )
