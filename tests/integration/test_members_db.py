"""Integration tests: member endpoints over HTTP (amigoact_test)."""

from __future__ import annotations

from httpx import AsyncClient

PASSWORD = "Aa1!secure"


async def _token(client: AsyncClient, email: str, phone: str) -> str:
    response = await client.post(
        "/auth/register",
        json={"email": email, "phone": phone, "password": PASSWORD, "full_name": "Member User"},
    )
    assert response.status_code == 201, response.text
    logged = await client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert logged.status_code == 200, logged.text
    return logged.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _make_org(
    client: AsyncClient, headers: dict[str, str], slug: str, policy: str = "invite"
) -> str:
    created = await client.post(
        "/orgs",
        json={
            "name": f"Name {slug}",
            "slug": slug,
            "description": "Desc",
            "kind": "club",
            "join_policy": policy,
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def test_invite_accept_and_roster_flow(client: AsyncClient) -> None:
    owner = await _token(client, "mown@example.com", "0912346001")
    owner_h = _headers(owner)
    org_id = await _make_org(client, owner_h, "m-club")

    invitee = await _token(client, "minv@example.com", "0912346002")
    invitee_h = _headers(invitee)

    invited = await client.post(
        f"/orgs/{org_id}/members", json={"email": "minv@example.com"}, headers=owner_h
    )
    assert invited.status_code == 201, invited.text
    assert invited.json()["status"] == "invited"
    invitee_id = invited.json()["user_id"]

    # The invitee sees the invitation in their inbox.
    inbox = await client.get(
        "/orgs/memberships/mine?status=invited", headers=invitee_h
    )
    assert inbox.status_code == 200
    assert [m["org_id"] for m in inbox.json()["items"]] == [org_id]
    assert inbox.json()["items"][0]["org_slug"] == "m-club"

    # Invitee cannot see the roster until they accept.
    blocked = await client.get(f"/orgs/{org_id}/members", headers=invitee_h)
    assert blocked.status_code == 403

    accepted = await client.post(
        f"/orgs/{org_id}/members/me/accept", headers=invitee_h
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "active"

    roster = await client.get(f"/orgs/{org_id}/members", headers=owner_h)
    assert roster.status_code == 200
    body = roster.json()
    assert body["viewer_role"] == "owner"
    assert body["total"] == 2
    by_status = {item["user_id"]: item for item in body["items"]}
    assert by_status[invitee_id]["status"] == "active"
    assert all(item["email"] for item in body["items"])


async def test_invitation_records_inviter(client: AsyncClient) -> None:
    owner = await _token(client, "vown@example.com", "0912346014")
    owner_h = _headers(owner)
    org_id = await _make_org(client, owner_h, "v-club")
    owner_me = await client.get("/auth/me", headers=owner_h)

    invitee = await _token(client, "vinv@example.com", "0912346015")
    invitee_h = _headers(invitee)

    invited = await client.post(
        f"/orgs/{org_id}/members",
        json={"email": "vinv@example.com"},
        headers=owner_h,
    )
    assert invited.status_code == 201, invited.text
    assert invited.json()["invited_by"] == owner_me.json()["id"]
    assert invited.json()["invited_by_name"] == "Member User"

    inbox = await client.get(
        "/orgs/memberships/mine?status=invited", headers=invitee_h
    )
    assert inbox.status_code == 200
    assert inbox.json()["items"][0]["invited_by_name"] == "Member User"

    # Accepting keeps the inviter recorded on the roster row.
    await client.post(
        f"/orgs/{org_id}/members/me/accept", headers=invitee_h
    )
    roster = await client.get(f"/orgs/{org_id}/members", headers=owner_h)
    row = [
        item
        for item in roster.json()["items"]
        if item["user_id"] == invited.json()["user_id"]
    ][0]
    assert row["invited_by"] == owner_me.json()["id"]


async def test_invite_decline_and_member_privacy(client: AsyncClient) -> None:
    owner = await _token(client, "dwn@example.com", "0912346003")
    owner_h = _headers(owner)
    org_id = await _make_org(client, owner_h, "d-club")

    guest = await _token(client, "dinv@example.com", "0912346004")
    guest_h = _headers(guest)
    member = await _token(client, "dmem@example.com", "0912346005")
    member_h = _headers(member)

    for email in ("dinv@example.com", "dmem@example.com"):
        made = await client.post(
            f"/orgs/{org_id}/members", json={"email": email}, headers=owner_h
        )
        assert made.status_code == 201, made.text

    declined = await client.post(
        f"/orgs/{org_id}/members/me/decline", headers=guest_h
    )
    assert declined.status_code == 200
    assert declined.json()["status"] == "left"

    # Declined membership stays as a left audit row, not a delete.
    roster = await client.get(f"/orgs/{org_id}/members", headers=owner_h)
    states = {item["status"] for item in roster.json()["items"]}
    assert states == {"active", "invited", "left"}

    accepted = await client.post(
        f"/orgs/{org_id}/members/me/accept", headers=member_h
    )
    assert accepted.status_code == 200

    # A regular member sees the active roster but no emails and no left rows.
    view = await client.get(f"/orgs/{org_id}/members", headers=member_h)
    assert view.status_code == 200
    body = view.json()
    assert body["viewer_role"] == "member"
    assert all(item["email"] is None for item in body["items"])
    assert {item["status"] for item in body["items"]} == {"active"}

    # A regular member cannot invite.
    denied = await client.post(
        f"/orgs/{org_id}/members",
        json={"email": "dinv@example.com"},
        headers=member_h,
    )
    assert denied.status_code == 403


async def test_suspend_reactivate_remove_and_leave(client: AsyncClient) -> None:
    owner = await _token(client, "sown@example.com", "0912346006")
    owner_h = _headers(owner)
    org_id = await _make_org(client, owner_h, "s-club")

    member = await _token(client, "smem@example.com", "0912346007")
    member_h = _headers(member)
    await client.post(
        f"/orgs/{org_id}/members", json={"email": "smem@example.com"}, headers=owner_h
    )
    accepted = await client.post(
        f"/orgs/{org_id}/members/me/accept", headers=member_h
    )
    member_id = accepted.json()["user_id"]

    suspended = await client.patch(
        f"/orgs/{org_id}/members/{member_id}",
        json={"status": "suspended"},
        headers=owner_h,
    )
    assert suspended.status_code == 200, suspended.text
    assert suspended.json()["status"] == "suspended"

    # Suspended members lose roster access until reactivated.
    blocked = await client.get(f"/orgs/{org_id}/members", headers=member_h)
    assert blocked.status_code == 403

    reactivated = await client.patch(
        f"/orgs/{org_id}/members/{member_id}",
        json={"status": "active"},
        headers=owner_h,
    )
    assert reactivated.status_code == 200

    # Member leaves themself -> left audit row.
    left = await client.delete(
        f"/orgs/{org_id}/members/{member_id}", headers=member_h
    )
    assert left.status_code == 204
    roster = await client.get(f"/orgs/{org_id}/members", headers=owner_h)
    mine = [i for i in roster.json()["items"] if i["user_id"] == member_id]
    assert mine[0]["status"] == "left"

    # Re-invite after left works.
    again = await client.post(
        f"/orgs/{org_id}/members", json={"email": "smem@example.com"}, headers=owner_h
    )
    assert again.status_code == 201
    assert again.json()["status"] == "invited"


async def test_open_join_and_invite_only(client: AsyncClient) -> None:
    owner = await _token(client, "jown@example.com", "0912346008")
    owner_h = _headers(owner)
    open_org = await _make_org(client, owner_h, "j-open", policy="open")
    invite_org = await _make_org(client, owner_h, "j-invite", policy="invite")

    stranger = await _token(client, "jstr@example.com", "0912346009")
    stranger_h = _headers(stranger)

    denied = await client.post(
        f"/orgs/{invite_org}/members/join", headers=stranger_h
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "INVITE_ONLY"

    joined = await client.post(
        f"/orgs/{open_org}/members/join", headers=stranger_h
    )
    assert joined.status_code == 201, joined.text
    assert joined.json()["status"] == "active"

    twice = await client.post(
        f"/orgs/{open_org}/members/join", headers=stranger_h
    )
    assert twice.status_code == 409
    assert twice.json()["code"] == "ALREADY_MEMBER"


async def test_join_policy_update_and_admin_assignment(client: AsyncClient) -> None:
    owner = await _token(client, "pown@example.com", "0912346010")
    owner_h = _headers(owner)
    org_id = await _make_org(client, owner_h, "p-club")

    member = await _token(client, "pmem@example.com", "0912346011")
    member_h = _headers(member)
    await client.post(
        f"/orgs/{org_id}/members", json={"email": "pmem@example.com"}, headers=owner_h
    )
    accepted = await client.post(
        f"/orgs/{org_id}/members/me/accept", headers=member_h
    )
    member_id = accepted.json()["user_id"]

    # Only the owner can flip join_policy.
    forbidden = await client.patch(
        f"/orgs/{org_id}",
        json={"name": "Name p-club", "description": "", "join_policy": "open"},
        headers=member_h,
    )
    assert forbidden.status_code == 403

    updated = await client.patch(
        f"/orgs/{org_id}",
        json={"name": "Name p-club", "description": "", "join_policy": "open"},
        headers=owner_h,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["join_policy"] == "open"

    # Owner promotes the member to admin; the new admin can invite.
    promoted = await client.patch(
        f"/orgs/{org_id}/members/{member_id}",
        json={"role": "admin"},
        headers=owner_h,
    )
    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["role"] == "admin"

    third = await _token(client, "p3@example.com", "0912346012")
    invited = await client.post(
        f"/orgs/{org_id}/members", json={"email": "p3@example.com"}, headers=member_h
    )
    assert invited.status_code == 201

    # Admins cannot assign roles or manage other admins.
    denied = await client.patch(
        f"/orgs/{org_id}/members/{invited.json()['user_id']}",
        json={"role": "admin"},
        headers=member_h,
    )
    assert denied.status_code == 403

    demoted = await client.patch(
        f"/orgs/{org_id}/members/{member_id}",
        json={"role": "member"},
        headers=owner_h,
    )
    assert demoted.status_code == 200
    assert demoted.json()["role"] == "member"


async def test_owner_immutable_and_member_not_found(client: AsyncClient) -> None:
    owner = await _token(client, "iown@example.com", "0912346013")
    owner_h = _headers(owner)
    org_id = await _make_org(client, owner_h, "i-club")

    me = await client.get("/auth/me", headers=owner_h)
    owner_id = me.json()["id"]

    blocked = await client.delete(
        f"/orgs/{org_id}/members/{owner_id}", headers=owner_h
    )
    assert blocked.status_code == 400
    assert blocked.json()["code"] == "OWNER_IMMUTABLE"

    # A random uuid that was never a member.
    import uuid_utils

    ghost = await client.delete(
        f"/orgs/{org_id}/members/{uuid_utils.uuid7()}", headers=owner_h
    )
    assert ghost.status_code == 404
    assert ghost.json()["code"] == "MEMBER_NOT_FOUND"

    suspended = await client.patch(
        f"/orgs/{org_id}/members/{owner_id}",
        json={"status": "suspended"},
        headers=owner_h,
    )
    assert suspended.status_code == 400
    assert suspended.json()["code"] == "OWNER_IMMUTABLE"
