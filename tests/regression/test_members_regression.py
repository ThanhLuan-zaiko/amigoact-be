"""Regression tests: lock member API contracts (envelope, codes, privacy)."""

from __future__ import annotations

from httpx import AsyncClient

PASSWORD = "Aa1!secure"


async def _token(client: AsyncClient, email: str, phone: str) -> str:
    response = await client.post(
        "/auth/register",
        json={"email": email, "phone": phone, "password": PASSWORD, "full_name": "Reg User"},
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
        json={"name": f"Name {slug}", "slug": slug, "description": "", "kind": "club"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def test_member_page_envelope_and_viewer_role(client: AsyncClient) -> None:
    """GET /members must keep {items,total,counts,viewer_role} stable."""
    owner = await _token(client, "rown@example.com", "0912347001")
    headers = _headers(owner)
    org_id = await _make_org(client, headers, "r-club")

    roster = await client.get(f"/orgs/{org_id}/members", headers=headers)
    assert roster.status_code == 200
    body = roster.json()
    assert set(body.keys()) == {
        "items",
        "total",
        "counts",
        "viewer_role",
        "viewer_permissions",
    }
    assert body["viewer_role"] == "owner"
    assert "member:role-assign" in body["viewer_permissions"]
    assert body["total"] == 1
    item = body["items"][0]
    assert {
        "user_id", "org_id", "full_name", "email", "roles", "status",
        "joined_at",
    } <= set(item.keys())
    assert item["roles"] == ["owner"]
    assert item["status"] == "active"


async def test_error_codes_stay_stable(client: AsyncClient) -> None:
    """Every new member error code maps to its documented status."""
    owner = await _token(client, "eown@example.com", "0912347002")
    headers = _headers(owner)
    org_id = await _make_org(client, headers, "e-club")

    unknown = await client.post(
        f"/orgs/{org_id}/members", json={"email": "none@example.com"}, headers=headers
    )
    assert (unknown.status_code, unknown.json()["code"]) == (404, "USER_NOT_FOUND")

    stranger = await _token(client, "estr@example.com", "0912347003")
    stranger_h = _headers(stranger)
    denied = await client.post(
        f"/orgs/{org_id}/members/join", headers=stranger_h
    )
    assert (denied.status_code, denied.json()["code"]) == (403, "INVITE_ONLY")

    invited = await client.post(
        f"/orgs/{org_id}/members", json={"email": "estr@example.com"}, headers=headers
    )
    assert invited.status_code == 201
    dup = await client.post(
        f"/orgs/{org_id}/members", json={"email": "estr@example.com"}, headers=headers
    )
    assert (dup.status_code, dup.json()["code"]) == (409, "ALREADY_INVITED")

    # The stranger was invited above, so accept now succeeds.
    accepted = await client.post(
        f"/orgs/{org_id}/members/me/accept", headers=stranger_h
    )
    assert accepted.status_code == 200

    stranger2 = await _token(client, "estr2@example.com", "0912347004")
    none_pending = await client.post(
        f"/orgs/{org_id}/members/me/accept", headers=_headers(stranger2)
    )
    assert none_pending.status_code == 400
    assert none_pending.json()["code"] == "INVALID_MEMBER_STATE"


async def test_left_audit_rows_survive(client: AsyncClient) -> None:
    """Removal keeps a left row; the roster total keeps counting history."""
    owner = await _token(client, "lown@example.com", "0912347005")
    headers = _headers(owner)
    org_id = await _make_org(client, headers, "l-club")

    member = await _token(client, "lmem@example.com", "0912347006")
    await client.post(
        f"/orgs/{org_id}/members", json={"email": "lmem@example.com"}, headers=headers
    )
    accepted = await client.post(
        f"/orgs/{org_id}/members/me/accept", headers=_headers(member)
    )
    member_id = accepted.json()["user_id"]

    removed = await client.delete(
        f"/orgs/{org_id}/members/{member_id}", headers=headers
    )
    assert removed.status_code == 204

    roster = await client.get(f"/orgs/{org_id}/members", headers=headers)
    left = [i for i in roster.json()["items"] if i["user_id"] == member_id]
    assert len(left) == 1
    assert left[0]["status"] == "left"
    counts = {c["bucket"]: c["count"] for c in roster.json()["counts"]}
    assert counts["left"] == 1


async def test_revoked_invitation_contract(client: AsyncClient) -> None:
    """DELETE .../invitation lands on 'revoked', distinct from 'left'."""
    owner = await _token(client, "vown@example.com", "0912347007")
    headers = _headers(owner)
    org_id = await _make_org(client, headers, "v-club")

    await _token(client, "vmem@example.com", "0912347008")
    invited = await client.post(
        f"/orgs/{org_id}/members", json={"email": "vmem@example.com"}, headers=headers
    )
    assert invited.status_code == 201
    member_id = invited.json()["user_id"]

    revoked = await client.delete(
        f"/orgs/{org_id}/members/{member_id}/invitation", headers=headers
    )
    assert revoked.status_code == 204

    roster = await client.get(f"/orgs/{org_id}/members", headers=headers)
    row = [i for i in roster.json()["items"] if i["user_id"] == member_id]
    assert len(row) == 1
    assert row[0]["status"] == "revoked"
    counts = {c["bucket"]: c["count"] for c in roster.json()["counts"]}
    assert counts["revoked"] == 1

    # A revoked link is no longer a member for remove/update purposes.
    gone = await client.delete(
        f"/orgs/{org_id}/members/{member_id}", headers=headers
    )
    assert gone.status_code == 404
    assert gone.json()["code"] == "MEMBER_NOT_FOUND"
