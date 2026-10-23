"""Regression: an activity tag is a personal-book attachment."""

from __future__ import annotations

from httpx import AsyncClient

from tests.integration.test_activity_tags_db import _BODY, _headers, _org


async def test_activity_tag_response_shape(client: AsyncClient) -> None:
    owner = await _headers(client, "rg.acttag@example.com", "0903000092")
    org_id = await _org(client, owner, "rg-act-tag")
    created = await client.post(
        f"/orgs/{org_id}/activities",
        json={**_BODY, "tags": ["Bien xanh"]},
        headers=owner,
    )
    assert created.status_code == 201, created.text
    listed = await client.get("/me/tags", headers=owner)
    assert listed.status_code == 200, listed.text
    tag = next(item for item in listed.json() if item["slug"] == "bien-xanh")
    assert set(tag.keys()) >= {
        "name",
        "slug",
        "post_count",
        "activity_count",
        "created_at",
        "posts",
        "activities",
    }
    assert set(tag["activities"][0].keys()) == {
        "activity_id",
        "org_id",
        "title",
        "draft",
    }
    assert tag["activities"][0]["activity_id"] == created.json()["id"]


async def _seat(
    client: AsyncClient,
    org_id: str,
    owner_h: dict,
    email: str,
    phone: str,
    permissions: list[str],
) -> dict:
    member_h = await _headers(client, email, phone)
    invited = await client.post(
        f"/orgs/{org_id}/members",
        json={"email": email},
        headers=owner_h,
    )
    assert invited.status_code == 201, invited.text
    accepted = await client.post(
        f"/orgs/{org_id}/members/me/accept", headers=member_h
    )
    assert accepted.status_code == 200, accepted.text
    role = await client.post(
        f"/orgs/{org_id}/roles",
        json={"name": f"Events {phone[-2:]}", "permissions": permissions},
        headers=owner_h,
    )
    assert role.status_code == 201, role.text
    patched = await client.patch(
        f"/orgs/{org_id}/members/{accepted.json()['user_id']}",
        json={"roles": [role.json()["name"]]},
        headers=owner_h,
    )
    assert patched.status_code == 200, patched.text
    return member_h


async def test_personal_delete_does_not_strip_someone_elses_activity(
    client: AsyncClient,
) -> None:
    owner = await _headers(client, "rg.own@example.com", "0903000096")
    org_id = await _org(client, owner, "rg-shared-tag")
    member = await _seat(
        client,
        org_id,
        owner,
        "rg.mem@example.com",
        "0903000097",
        ["activity:create", "activity:manage"],
    )
    first = await client.post(
        f"/orgs/{org_id}/activities",
        json={**_BODY, "title": "Mine", "tags": ["Chung"]},
        headers=owner,
    )
    second = await client.post(
        f"/orgs/{org_id}/activities",
        json={**_BODY, "title": "Theirs", "tags": ["Chung"]},
        headers=member,
    )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    removed = await client.delete("/me/tags/chung", headers=owner)
    assert removed.status_code == 204, removed.text
    own = await client.get(f"/activities/{first.json()['id']}", headers=owner)
    other = await client.get(
        f"/activities/{second.json()['id']}", headers=member
    )
    assert own.json()["tags"] == []
    assert other.json()["tags"] == [{"name": "Chung", "slug": "chung"}]
    listed = await client.get("/me/tags", headers=member)
    tag = next(item for item in listed.json() if item["slug"] == "chung")
    assert tag["activities"][0]["activity_id"] == second.json()["id"]


async def test_co_manager_edit_claims_the_author_not_the_editor(
    client: AsyncClient,
) -> None:
    owner = await _headers(client, "rg.author@example.com", "0903000098")
    org_id = await _org(client, owner, "rg-author-book")
    editor = await _seat(
        client,
        org_id,
        owner,
        "rg.editor@example.com",
        "0903000099",
        ["activity:manage"],
    )
    created = await client.post(
        f"/orgs/{org_id}/activities",
        json={**_BODY, "tags": ["Mua he"]},
        headers=owner,
    )
    assert created.status_code == 201, created.text
    updated = await client.patch(
        f"/orgs/{org_id}/activities/{created.json()['id']}",
        json={**_BODY, "tags": ["Mua he", "Sach moi"]},
        headers=editor,
    )
    assert updated.status_code == 200, updated.text
    author = await client.get("/me/tags", headers=owner)
    slugs = {item["slug"] for item in author.json()}
    assert {"mua-he", "sach-moi"} <= slugs
    stranger = await client.get("/me/tags", headers=editor)
    assert all(item["slug"] != "sach-moi" for item in stranger.json())
