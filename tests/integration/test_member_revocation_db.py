"""Integration tests: invitation revocation over HTTP (amigoact_test)."""

from __future__ import annotations

from httpx import AsyncClient

PASSWORD = "Aa1!secure"


async def _token(client: AsyncClient, email: str, phone: str) -> str:
    response = await client.post(
        "/auth/register",
        json={
            "email": email,
            "phone": phone,
            "password": PASSWORD,
            "full_name": "Member User",
        },
    )
    assert response.status_code == 201, response.text
    logged = await client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert logged.status_code == 200, logged.text
    return logged.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _make_org(
    client: AsyncClient, headers: dict[str, str], slug: str
) -> str:
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


async def test_revoke_invitation_flow(client: AsyncClient) -> None:
    """invited -> revoked via DELETE .../invitation; re-invite still works."""
    owner = await _token(client, "rvown@example.com", "0912346101")
    owner_h = _headers(owner)
    org_id = await _make_org(client, owner_h, "rv-club")

    invitee = await _token(client, "rvinv@example.com", "0912346102")
    invitee_h = _headers(invitee)

    invited = await client.post(
        f"/orgs/{org_id}/members",
        json={"email": "rvinv@example.com"},
        headers=owner_h,
    )
    assert invited.status_code == 201, invited.text
    invitee_id = invited.json()["user_id"]

    revoked = await client.delete(
        f"/orgs/{org_id}/members/{invitee_id}/invitation", headers=owner_h
    )
    assert revoked.status_code == 204, revoked.text

    # The dead invite can no longer be accepted or declined.
    for action in ("accept", "decline"):
        answered = await client.post(
            f"/orgs/{org_id}/members/me/{action}", headers=invitee_h
        )
        assert answered.status_code == 400
        assert answered.json()["code"] == "INVALID_MEMBER_STATE"

    # The invitation inbox drops it; the roster keeps a revoked row.
    inbox = await client.get(
        "/orgs/memberships/mine?status=invited", headers=invitee_h
    )
    assert all(item["org_id"] != org_id for item in inbox.json()["items"])
    roster = await client.get(f"/orgs/{org_id}/members", headers=owner_h)
    row = [
        i for i in roster.json()["items"] if i["user_id"] == invitee_id
    ][0]
    assert row["status"] == "revoked"
    counts = {c["bucket"]: c["count"] for c in roster.json()["counts"]}
    assert counts["revoked"] == 1

    # Re-invite after revocation works, then a normal accept.
    again = await client.post(
        f"/orgs/{org_id}/members",
        json={"email": "rvinv@example.com"},
        headers=owner_h,
    )
    assert again.status_code == 201
    assert again.json()["status"] == "invited"
    accepted = await client.post(
        f"/orgs/{org_id}/members/me/accept", headers=invitee_h
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "active"


async def test_revoke_invitation_permissions_and_states(
    client: AsyncClient,
) -> None:
    """Plain members get 403; non-pending rows get 400 INVALID_MEMBER_STATE."""
    owner = await _token(client, "pvown@example.com", "0912346103")
    owner_h = _headers(owner)
    org_id = await _make_org(client, owner_h, "pv-club")

    member = await _token(client, "pvmem@example.com", "0912346104")
    member_h = _headers(member)
    made = await client.post(
        f"/orgs/{org_id}/members",
        json={"email": "pvmem@example.com"},
        headers=owner_h,
    )
    member_id = made.json()["user_id"]
    await client.post(f"/orgs/{org_id}/members/me/accept", headers=member_h)

    other = await _token(client, "pvoth@example.com", "0912346105")
    invited = await client.post(
        f"/orgs/{org_id}/members",
        json={"email": "pvoth@example.com"},
        headers=owner_h,
    )
    other_id = invited.json()["user_id"]

    denied = await client.delete(
        f"/orgs/{org_id}/members/{other_id}/invitation", headers=member_h
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "FORBIDDEN"

    # Active members and strangers are not pending invitations.
    stale = await client.delete(
        f"/orgs/{org_id}/members/{member_id}/invitation", headers=owner_h
    )
    assert stale.status_code == 400
    assert stale.json()["code"] == "INVALID_MEMBER_STATE"

    import uuid_utils

    ghost = await client.delete(
        f"/orgs/{org_id}/members/{uuid_utils.uuid7()}/invitation",
        headers=owner_h,
    )
    assert ghost.status_code == 400
    assert ghost.json()["code"] == "INVALID_MEMBER_STATE"


async def test_revoked_invite_survives_in_audit_roster(
    client: AsyncClient,
) -> None:
    """A revoked row stays visible to managers, distinct from left."""
    owner = await _token(client, "raown@example.com", "0912346106")
    owner_h = _headers(owner)
    org_id = await _make_org(client, owner_h, "ra-club")

    leaver = await _token(client, "ra-leave@example.com", "0912346107")
    revokee = await _token(client, "ra-rev@example.com", "0912346108")
    for email in ("ra-leave@example.com", "ra-rev@example.com"):
        invited = await client.post(
            f"/orgs/{org_id}/members",
            json={"email": email},
            headers=owner_h,
        )
        assert invited.status_code == 201

    await client.post(
        f"/orgs/{org_id}/members/me/decline", headers=_headers(leaver)
    )

    mine = await client.get("/auth/me", headers=_headers(revokee))
    await client.delete(
        f"/orgs/{org_id}/members/{mine.json()['id']}/invitation",
        headers=owner_h,
    )

    roster = await client.get(f"/orgs/{org_id}/members", headers=owner_h)
    states = {item["status"] for item in roster.json()["items"]}
    assert {"active", "left", "revoked"} <= states
