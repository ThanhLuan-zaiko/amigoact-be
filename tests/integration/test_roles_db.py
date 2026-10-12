"""Integration tests: org custom role endpoints over HTTP (amigoact_test)."""

from __future__ import annotations

from httpx import AsyncClient

PASSWORD = "Aa1!secure"


async def _token(client: AsyncClient, email: str, phone: str) -> str:
    response = await client.post(
        "/auth/register",
        json={"email": email, "phone": phone, "password": PASSWORD, "full_name": "Role User"},
    )
    assert response.status_code == 201, response.text
    logged = await client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert logged.status_code == 200, logged.text
    return logged.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _make_org(client: AsyncClient, headers: dict[str, str], slug: str) -> str:
    created = await client.post(
        "/orgs",
        json={
            "name": f"Name {slug}",
            "slug": slug,
            "description": "Desc",
            "kind": "club",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def test_role_crud_lifecycle(client: AsyncClient) -> None:
    owner = await _token(client, "rown@example.com", "0912348001")
    headers = _headers(owner)
    org_id = await _make_org(client, headers, "role-club")

    # Owner sees the seeded admin role plus the assignable catalog.
    listed = await client.get(f"/orgs/{org_id}/roles", headers=headers)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert [row["name"] for row in body["items"]] == ["admin"]
    assert body["items"][0]["is_system"] is True
    assert "member:role-assign" in body["assignable_permissions"]
    assert "media:upload" not in body["assignable_permissions"]

    created = await client.post(
        f"/orgs/{org_id}/roles",
        json={
            "name": "Event Manager",
            "description": "Runs events",
            "permissions": ["activity:manage", "activity:create"],
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    role = created.json()
    assert role["permissions"] == ["activity:create", "activity:manage"]
    assert role["member_count"] == 0

    dup = await client.post(
        f"/orgs/{org_id}/roles",
        json={"name": "event manager", "permissions": ["activity:view"]},
        headers=headers,
    )
    assert (dup.status_code, dup.json()["code"]) == (409, "ROLE_NAME_TAKEN")

    updated = await client.patch(
        f"/orgs/{org_id}/roles/{role['id']}",
        json={"name": "Event Ops", "permissions": ["activity:manage"]},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Event Ops"
    assert updated.json()["permissions"] == ["activity:manage"]

    removed = await client.delete(
        f"/orgs/{org_id}/roles/{role['id']}", headers=headers
    )
    assert removed.status_code == 204
    gone = await client.delete(
        f"/orgs/{org_id}/roles/{role['id']}", headers=headers
    )
    assert (gone.status_code, gone.json()["code"]) == (404, "ROLE_NOT_FOUND")


async def test_role_assign_via_member_patch_and_delete_clears(
    client: AsyncClient,
) -> None:
    owner = await _token(client, "aown@example.com", "0912348002")
    owner_h = _headers(owner)
    org_id = await _make_org(client, owner_h, "assign-club")

    member = await _token(client, "amem@example.com", "0912348003")
    member_h = _headers(member)
    await client.post(
        f"/orgs/{org_id}/members",
        json={"email": "amem@example.com"},
        headers=owner_h,
    )
    accepted = await client.post(
        f"/orgs/{org_id}/members/me/accept", headers=member_h
    )
    member_id = accepted.json()["user_id"]

    created = await client.post(
        f"/orgs/{org_id}/roles",
        json={"name": "Checker", "permissions": ["activity:manage"]},
        headers=owner_h,
    )
    role_id = created.json()["id"]

    patched = await client.patch(
        f"/orgs/{org_id}/members/{member_id}",
        json={"roles": ["Checker"]},
        headers=owner_h,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["roles"] == ["Checker"]

    roster = await client.get(f"/orgs/{org_id}/roles", headers=owner_h)
    custom = [r for r in roster.json()["items"] if r["name"] == "Checker"][0]
    assert custom["member_count"] == 1

    # Deleting the role strips the badge off the member row.
    await client.delete(f"/orgs/{org_id}/roles/{role_id}", headers=owner_h)
    members = await client.get(f"/orgs/{org_id}/members", headers=owner_h)
    row = [i for i in members.json()["items"] if i["user_id"] == member_id][0]
    assert row["roles"] == []


async def test_role_write_requires_membership_and_manager(
    client: AsyncClient,
) -> None:
    owner = await _token(client, "bown@example.com", "0912348004")
    owner_h = _headers(owner)
    org_id = await _make_org(client, owner_h, "guard-club")

    outsider = await _token(client, "bout@example.com", "0912348005")
    outsider_h = _headers(outsider)
    denied = await client.get(f"/orgs/{org_id}/roles", headers=outsider_h)
    assert denied.status_code == 403

    member = await _token(client, "bmem@example.com", "0912348006")
    member_h = _headers(member)
    await client.post(
        f"/orgs/{org_id}/members",
        json={"email": "bmem@example.com"},
        headers=owner_h,
    )
    await client.post(f"/orgs/{org_id}/members/me/accept", headers=member_h)

    listed = await client.get(f"/orgs/{org_id}/roles", headers=member_h)
    assert listed.status_code == 200

    # A plain member cannot create, edit or delete roles.
    created = await client.post(
        f"/orgs/{org_id}/roles",
        json={"name": "Nope", "permissions": ["activity:view"]},
        headers=member_h,
    )
    assert created.status_code == 403


async def test_invite_and_patch_with_custom_role_end_to_end(
    client: AsyncClient,
) -> None:
    owner = await _token(client, "cown@example.com", "0912348007")
    owner_h = _headers(owner)
    org_id = await _make_org(client, owner_h, "invite-club")

    await client.post(
        f"/orgs/{org_id}/roles",
        json={
            "name": "Coordinator",
            "permissions": ["activity:manage", "activity:create"],
        },
        headers=owner_h,
    )
    await _token(client, "cvip@example.com", "0912348008")

    invited = await client.post(
        f"/orgs/{org_id}/members",
        json={"email": "cvip@example.com", "role": "Coordinator"},
        headers=owner_h,
    )
    assert invited.status_code == 201, invited.text
    assert invited.json()["roles"] == ["Coordinator"]

    await _token(client, "cghost@example.com", "0912348009")
    bad = await client.post(
        f"/orgs/{org_id}/members",
        json={"email": "cghost@example.com", "role": "Ghost"},
        headers=owner_h,
    )
    assert (bad.status_code, bad.json()["code"]) == (400, "INVALID_ROLE")
