import uuid
from pathlib import Path

from sqlalchemy import update

from src.app import app
from src.models.media import MediaAsset
from src.models.organizations import Organization
from src.models.posts import OrgPost
from tests.activity_helpers import Bearer, user
from tests.conftest import ApiContext
from tests.media_helpers import db_row, uploaded
from tests.post_helpers import comment, created, join, open_org, post


def test_anonymous_visitors_cannot_write_or_read_drafts(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "anon")
    slug = open_org(api, owner)
    item = created(api, owner, slug, kind="announcement")

    assert (
        api.client.post(
            f"/organizations/{slug}/posts",
            json={"kind": "discussion", "title": "x", "body": "y"},
        ).status_code
        == 401
    )
    assert (
        api.client.post(
            f"/posts/{item['id']}/comments", json={"body": "hi"}
        ).status_code
        == 401
    )
    assert api.client.get(f"/organizations/{slug}/post-drafts").status_code == 401
    assert api.client.get("/feed").status_code == 401


def test_outsiders_cannot_post(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "own")
    outsider, _ = user(api, bearer, "outside")
    slug = open_org(api, owner)

    response = post(api, outsider, slug)

    assert response.status_code == 403
    assert response.json()["detail"] == "post_forbidden"


def test_only_managers_pin_and_only_the_author_edits(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "manager")
    member, _ = user(api, bearer, "member")
    slug = open_org(api, owner)
    join(api, slug, member)
    members_post = created(api, member, slug)
    announcement = created(api, owner, slug, kind="announcement")

    pin_by_member = api.client.post(f"/posts/{announcement['id']}/pin", headers=member)
    edit_by_manager = api.client.patch(
        f"/posts/{members_post['id']}", headers=owner, json={"title": "Sua"}
    )

    assert pin_by_member.status_code == 403
    assert pin_by_member.json()["detail"] == "post_forbidden"
    assert edit_by_manager.status_code == 403
    assert db_row(OrgPost, uuid.UUID(members_post["id"])).title == "Hello"


def test_members_posts_are_hidden_from_outsiders(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "host")
    member, _ = user(api, bearer, "guest")
    outsider, _ = user(api, bearer, "stranger")
    slug = open_org(api, owner)
    join(api, slug, member)
    secret = created(api, member, slug, title="Chi thanh vien", body="Bi mat")
    comment(api, member, secret["id"], "Binh luan")

    assert api.client.get(f"/posts/{secret['id']}", headers=outsider).status_code == 404
    assert api.client.get(f"/posts/{secret['id']}").status_code == 404
    assert api.client.get(f"/posts/{secret['id']}/comments").status_code == 404
    timeline = api.client.get(f"/organizations/{slug}/posts", headers=outsider).json()
    assert secret["id"] not in [item["id"] for item in timeline["items"]]
    outsider_feed = api.client.get("/feed", headers=outsider).json()["items"]
    assert secret["id"] not in [item["id"] for item in outsider_feed]
    public_feed = api.client.get("/feed/public").json()["items"]
    assert secret["id"] not in [item["id"] for item in public_feed]


def test_drafts_belong_to_their_author(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "writer")
    other, _ = user(api, bearer, "reader")
    slug = open_org(api, owner)
    join(api, slug, other)
    draft = created(api, owner, slug, draft=True, title="Ban nhap")

    assert api.client.get(f"/posts/{draft['id']}", headers=other).status_code == 404
    assert (
        api.client.post(f"/posts/{draft['id']}/publish", headers=other).status_code
        == 404
    )
    other_drafts = api.client.get(
        f"/organizations/{slug}/post-drafts", headers=other
    ).json()
    assert other_drafts["items"] == []
    assert (
        api.client.post(
            f"/posts/{draft['id']}/comments", headers=owner, json={"body": "x"}
        ).status_code
        == 409
    )


def test_deleted_posts_vanish_with_their_comments(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "gone")
    slug = open_org(api, owner)
    item = created(api, owner, slug, kind="announcement")
    comment(api, owner, item["id"], "Se mat")

    assert api.client.delete(f"/posts/{item['id']}", headers=owner).status_code == 204

    assert api.client.get(f"/posts/{item['id']}/comments").status_code == 404
    assert api.client.post(f"/posts/{item['id']}/pin", headers=owner).status_code == 404


def test_suspended_organization_hides_its_posts(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "suspended")
    slug = open_org(api, owner)
    item = created(api, owner, slug, kind="announcement")
    assert api.client.get("/feed/public").json()["items"]

    with app.state.engine.begin() as connection:
        connection.execute(
            update(Organization)
            .where(Organization.slug == slug)
            .values(status="suspended")
        )

    assert api.client.get(f"/posts/{item['id']}").status_code == 404
    assert api.client.get(f"/organizations/{slug}/posts").status_code == 404
    public_ids = [row["id"] for row in api.client.get("/feed/public").json()["items"]]
    assert item["id"] not in public_ids


def test_comments_need_membership(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "talker")
    outsider, _ = user(api, bearer, "visitor")
    slug = open_org(api, owner)
    announcement = created(api, owner, slug, kind="announcement")

    response = comment(api, outsider, announcement["id"], "Xin chao")

    assert response.status_code == 403
    assert response.json()["detail"] == "comment_forbidden"


def test_only_the_author_or_a_manager_deletes_a_comment(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "moderator")
    member, _ = user(api, bearer, "poster")
    other, _ = user(api, bearer, "bystander")
    slug = open_org(api, owner)
    join(api, slug, member)
    join(api, slug, other)
    announcement = created(api, owner, slug, kind="announcement")
    owners_comment = comment(api, owner, announcement["id"], "Cua chu").json()

    by_member = api.client.delete(f"/comments/{owners_comment['id']}", headers=member)
    by_other = api.client.delete(f"/comments/{owners_comment['id']}", headers=other)

    assert by_member.status_code == 403
    assert by_member.json()["detail"] == "comment_forbidden"
    assert by_other.status_code == 403


def test_someone_elses_picture_cannot_be_attached(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    owner, _ = user(api, bearer, "owner2")
    thief, _ = user(api, bearer, "thief")
    private = uploaded(api, owner)

    response = post(
        api, thief, open_org(api, thief), kind="announcement", media_ids=[private["id"]]
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "media_not_found"
    assert db_row(MediaAsset, uuid.UUID(private["id"])).visibility == "private"


def test_members_post_cannot_carry_pictures(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    owner, _ = user(api, bearer, "photog")
    slug = open_org(api, owner)
    picture = uploaded(api, owner)

    response = post(api, owner, slug, media_ids=[picture["id"]])

    assert response.status_code == 422
    assert "members_post_has_no_media" in response.text


def test_public_post_with_pictures_cannot_become_members_only(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    owner, _ = user(api, bearer, "shifter")
    slug = open_org(api, owner)
    picture = uploaded(api, owner)
    item = created(api, owner, slug, kind="announcement", media_ids=[picture["id"]])

    response = api.client.patch(
        f"/posts/{item['id']}", headers=owner, json={"visibility": "members"}
    )

    assert response.status_code == 422
    assert "members_post_has_no_media" in response.text


def test_tags_must_have_letters_and_stay_within_three(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "tagger")
    slug = open_org(api, owner)

    symbols = post(api, owner, slug, tags=["!!!"])
    too_many = post(api, owner, slug, tags=["a1", "b2", "c3", "d4"])

    assert symbols.status_code == 422
    assert "tag_invalid" in symbols.text
    assert too_many.status_code == 422


def test_post_bodies_refuse_unknown_fields_and_path_ids_must_be_uuid7(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, owner_id = user(api, bearer, "strict")
    slug = open_org(api, owner)

    forged = post(api, owner, slug, author_id=owner_id)
    unknown_path = api.client.get(f"/posts/{uuid.uuid4()}")

    assert forged.status_code == 422
    assert unknown_path.status_code == 422


def test_a_draft_cannot_be_pinned(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "pinner")
    slug = open_org(api, owner)
    draft = created(api, owner, slug, kind="announcement", draft=True)

    response = api.client.post(f"/posts/{draft['id']}/pin", headers=owner)

    assert response.status_code == 409
    assert response.json()["detail"] == "post_not_published"


def test_member_feed_only_shows_organizations_they_belong_to(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "first_org")
    other_owner, _ = user(api, bearer, "second_org")
    member, _ = user(api, bearer, "belonger")
    slug = open_org(api, owner)
    other_slug = open_org(api, other_owner)
    join(api, slug, member)
    inside = created(api, owner, slug, title="Trong")
    outside = created(api, other_owner, other_slug, title="Ngoai")

    ids = [
        item["id"] for item in api.client.get("/feed", headers=member).json()["items"]
    ]

    assert inside["id"] in ids
    assert outside["id"] not in ids
