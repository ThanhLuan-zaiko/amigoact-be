import uuid
from pathlib import Path

from src.models.media import MediaAsset
from src.models.posts import OrgPost
from tests.activity_helpers import Bearer, user
from tests.conftest import ApiContext
from tests.media_helpers import db_row, uploaded
from tests.post_helpers import comment, created, join, open_org, post


def test_manager_announcement_is_public_by_default(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    slug = open_org(api, owner)

    body = created(
        api, owner, slug, kind="announcement", title="Ngay hoi", body="Den nhe"
    )

    assert body["kind"] == "announcement"
    assert body["visibility"] == "public"
    assert body["status"] == "active"
    assert body["org"]["slug"] == slug
    assert body["viewer"] == {
        "can_edit": True,
        "can_delete": True,
        "can_pin": True,
        "can_comment": True,
    }
    assert uuid.UUID(body["id"]).version == 7


def test_member_discussion_is_for_members_by_default(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "own2")
    member, _ = user(api, bearer, "mem")
    slug = open_org(api, owner)
    join(api, slug, member)

    body = created(api, member, slug, title="Chia se", body="Hom nay vui")

    assert body["visibility"] == "members"
    assert body["viewer"]["can_edit"] is True
    assert body["viewer"]["can_pin"] is False
    assert body["viewer"]["can_delete"] is True


def test_member_cannot_announce(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "own3")
    member, _ = user(api, bearer, "mem3")
    slug = open_org(api, owner)
    join(api, slug, member)

    response = post(api, member, slug, kind="announcement")

    assert response.status_code == 403
    assert response.json()["detail"] == "post_forbidden"


def test_timeline_pages_newest_first(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "pager")
    slug = open_org(api, owner)
    first = created(api, owner, slug, kind="announcement", title="1")
    second = created(api, owner, slug, kind="announcement", title="2")
    third = created(api, owner, slug, kind="announcement", title="3")

    page_one = api.client.get(f"/organizations/{slug}/posts?limit=2").json()
    page_two = api.client.get(
        f"/organizations/{slug}/posts?limit=2&before={page_one['next_before']}"
    ).json()

    assert [item["id"] for item in page_one["items"]] == [third["id"], second["id"]]
    assert page_one["next_before"] == second["id"]
    assert [item["id"] for item in page_two["items"]] == [first["id"]]
    assert page_two["next_before"] is None


def test_kind_filter_and_pinned_filter(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "filter")
    slug = open_org(api, owner)
    notice = created(api, owner, slug, kind="announcement", title="Thong bao")
    talk = created(api, owner, slug, kind="discussion", title="Thao luan")
    pin = api.client.post(f"/posts/{notice['id']}/pin", headers=owner)
    assert pin.status_code == 204

    announcements = api.client.get(
        f"/organizations/{slug}/posts?kind=announcement"
    ).json()["items"]
    pinned = api.client.get(
        f"/organizations/{slug}/posts?pinned_only=true", headers=owner
    ).json()["items"]

    assert [item["id"] for item in announcements] == [notice["id"]]
    assert [item["id"] for item in pinned] == [notice["id"]]
    assert pinned[0]["viewer"]["can_pin"] is True
    assert talk["id"] not in [item["id"] for item in pinned]


def test_draft_stays_private_until_published(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "drafter")
    slug = open_org(api, owner)
    draft = created(api, owner, slug, draft=True, title="Nhap")

    assert draft["status"] == "draft"
    assert draft["published_at"] is None
    listed = api.client.get(f"/organizations/{slug}/posts", headers=owner).json()[
        "items"
    ]
    mine = api.client.get(f"/organizations/{slug}/post-drafts", headers=owner).json()
    assert draft["id"] not in [item["id"] for item in listed]
    assert [item["id"] for item in mine["items"]] == [draft["id"]]

    published = api.client.post(f"/posts/{draft['id']}/publish", headers=owner)

    assert published.status_code == 200, published.text
    assert published.json()["status"] == "active"
    assert published.json()["published_at"] is not None
    listed = api.client.get(f"/organizations/{slug}/posts", headers=owner).json()[
        "items"
    ]
    assert draft["id"] in [item["id"] for item in listed]
    again = api.client.post(f"/posts/{draft['id']}/publish", headers=owner)
    assert again.status_code == 409
    assert again.json()["detail"] == "post_not_draft"


def test_author_edits_title_tags_and_visibility(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "editor")
    slug = open_org(api, owner)
    item = created(api, owner, slug, title="Cu", tags=["Hien mau", "Moi truong"])

    response = api.client.patch(
        f"/posts/{item['id']}",
        headers=owner,
        json={"title": "Moi", "tags": ["Tinh nguyen"], "visibility": "public"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == "Moi"
    assert body["tags"] == ["Tinh nguyen"]
    assert body["visibility"] == "public"
    assert body["edited_at"] is not None


def test_author_deletes_post_and_it_disappears(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "deleter")
    slug = open_org(api, owner)
    item = created(api, owner, slug, kind="announcement")

    assert api.client.delete(f"/posts/{item['id']}", headers=owner).status_code == 204

    assert api.client.get(f"/posts/{item['id']}", headers=owner).status_code == 404
    listed = api.client.get(f"/organizations/{slug}/posts").json()["items"]
    assert item["id"] not in [entry["id"] for entry in listed]


def test_manager_removes_a_members_post(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "mod")
    member, _ = user(api, bearer, "rule")
    slug = open_org(api, owner)
    join(api, slug, member)
    item = created(api, member, slug)

    assert api.client.delete(f"/posts/{item['id']}", headers=owner).status_code == 204


def test_comments_list_in_order_with_a_cursor(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "talker")
    member, _ = user(api, bearer, "reply")
    slug = open_org(api, owner)
    join(api, slug, member)
    item = created(api, owner, slug, kind="announcement")
    first = comment(api, member, item["id"], "Mot").json()
    second = comment(api, owner, item["id"], "Hai").json()

    page_one = api.client.get(f"/posts/{item['id']}/comments?limit=1").json()
    page_two = api.client.get(
        f"/posts/{item['id']}/comments?limit=1&after={page_one['next_after']}"
    ).json()

    assert [c["id"] for c in page_one["items"]] == [first["id"]]
    assert [c["id"] for c in page_two["items"]] == [second["id"]]
    assert page_two["next_after"] is None
    refreshed = api.client.get(f"/posts/{item['id']}", headers=owner).json()
    assert refreshed["comment_count"] == 2


def test_author_and_manager_can_delete_comments(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "cleaner")
    member, _ = user(api, bearer, "wrote")
    slug = open_org(api, owner)
    join(api, slug, member)
    item = created(api, owner, slug, kind="announcement")
    mine = comment(api, member, item["id"], "Cua toi").json()
    theirs = comment(api, owner, item["id"], "Cua chu").json()

    assert (
        api.client.delete(f"/comments/{mine['id']}", headers=member).status_code == 204
    )
    assert (
        api.client.delete(f"/comments/{theirs['id']}", headers=owner).status_code == 204
    )
    listed = api.client.get(f"/posts/{item['id']}/comments").json()["items"]
    assert listed == []


def test_member_feed_and_public_feed(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "feeder")
    member, _ = user(api, bearer, "feedmem")
    slug = open_org(api, owner)
    join(api, slug, member)
    public_post = created(api, owner, slug, kind="announcement", title="Cong khai")
    members_post = created(api, owner, slug, kind="discussion", title="Noi bo")

    member_feed = api.client.get("/feed", headers=member).json()["items"]
    anonymous_public = api.client.get("/feed/public").json()["items"]

    assert {item["id"] for item in member_feed} >= {
        public_post["id"],
        members_post["id"],
    }
    assert public_post["id"] in [item["id"] for item in anonymous_public]
    assert members_post["id"] not in [item["id"] for item in anonymous_public]


def test_popular_tags_count_recent_visible_posts(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "trend")
    slug = open_org(api, owner)
    created(api, owner, slug, kind="announcement", tags=["Tinh nguyen ABC"])
    created(api, owner, slug, kind="announcement", tags=["Tinh nguyen ABC"])

    tags = api.client.get("/feed/popular-tags").json()["items"]

    match = [tag for tag in tags if tag["name"] == "Tinh nguyen ABC"]
    assert match and match[0]["count"] >= 2


def test_media_on_a_public_post_becomes_public(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    owner, _ = user(api, bearer, "pic")
    slug = open_org(api, owner)
    picture = uploaded(api, owner)

    item = created(api, owner, slug, kind="announcement", media_ids=[picture["id"]])

    assert item["media"] == [
        {"id": picture["id"], "url": picture["url"], "mime": "image/png"}
    ]
    assert db_row(MediaAsset, uuid.UUID(picture["id"])).visibility == "public"
    assert api.client.get(picture["url"]).status_code == 200


def test_picture_on_a_draft_stays_private_until_publish(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    owner, _ = user(api, bearer, "shy")
    slug = open_org(api, owner)
    picture = uploaded(api, owner)
    draft = created(
        api, owner, slug, kind="announcement", draft=True, media_ids=[picture["id"]]
    )

    assert db_row(MediaAsset, uuid.UUID(picture["id"])).visibility == "private"

    api.client.post(f"/posts/{draft['id']}/publish", headers=owner)

    assert db_row(MediaAsset, uuid.UUID(picture["id"])).visibility == "public"


def test_post_row_is_stored_with_its_kind_and_org(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, owner_id = user(api, bearer, "row")
    slug = open_org(api, owner)
    item = created(api, owner, slug, kind="discussion", title="Luu")

    row = db_row(OrgPost, uuid.UUID(item["id"]))

    assert row.author_id == uuid.UUID(owner_id)
    assert row.kind == "discussion"
    assert row.visibility == "members"
    assert row.title == "Luu"


def test_unpin_takes_the_post_out_of_the_pinned_list(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "unpinner")
    slug = open_org(api, owner)
    notice = created(api, owner, slug, kind="announcement")
    api.client.post(f"/posts/{notice['id']}/pin", headers=owner)

    response = api.client.post(f"/posts/{notice['id']}/unpin", headers=owner)

    assert response.status_code == 204
    pinned = api.client.get(
        f"/organizations/{slug}/posts?pinned_only=true", headers=owner
    ).json()["items"]
    assert pinned == []
