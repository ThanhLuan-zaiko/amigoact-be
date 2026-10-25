"""Integration tests: manager view of a member's volunteer profile (amigoact_test)."""

from __future__ import annotations

from httpx import AsyncClient

PASSWORD = "Aa1!secure"


async def _token(client: AsyncClient, email: str, phone: str) -> str:
    response = await client.post(
        "/auth/register",
        json={"email": email, "phone": phone, "password": PASSWORD, "full_name": "Vol User"},
    )
    assert response.status_code == 201, response.text
    logged = await client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert logged.status_code == 200, logged.text
    return logged.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_owner_reads_member_volunteer_profile(client: AsyncClient) -> None:
    owner_h = _headers(await _token(client, "vv.owner@example.com", "0912347001"))
    created = await client.post(
        "/orgs",
        json={
            "name": "Volunteer View",
            "slug": "vv-club",
            "description": "Desc",
            "kind": "club",
            "join_policy": "invite",
        },
        headers=owner_h,
    )
    assert created.status_code == 201, created.text
    org_id = created.json()["id"]

    member_token = await _token(client, "vv.member@example.com", "0912347002")
    member_h = _headers(member_token)
    invited = await client.post(
        f"/orgs/{org_id}/members", json={"email": "vv.member@example.com"}, headers=owner_h
    )
    assert invited.status_code == 201, invited.text
    member_id = invited.json()["user_id"]

    pending_h = _headers(await _token(client, "vv.pending@example.com", "0912347004"))
    pending = await client.post(
        f"/orgs/{org_id}/members", json={"email": "vv.pending@example.com"}, headers=owner_h
    )
    assert pending.status_code == 201, pending.text
    pending_id = pending.json()["user_id"]

    accepted = await client.post(f"/orgs/{org_id}/members/me/accept", headers=member_h)
    assert accepted.status_code == 200, accepted.text

    profile = await client.put(
        "/profiles/me",
        json={"status": "working", "bio": "Weekend volunteer"},
        headers=member_h,
    )
    assert profile.status_code == 200, profile.text
    catalog = (await client.get("/skills")).json()
    pick = catalog[0]
    skills = await client.put(
        "/profiles/me/skills",
        json={"skills": [{"skill_id": pick["id"], "level": 4}]},
        headers=member_h,
    )
    assert skills.status_code == 200, skills.text
    contacts = await client.put(
        "/profiles/me/contacts",
        json={"contacts": [{"name": "Mom", "relation": "Me", "phone": "0901234567"}]},
        headers=member_h,
    )
    assert contacts.status_code == 200, contacts.text

    view = await client.get(
        f"/orgs/{org_id}/members/{member_id}/volunteer-profile", headers=owner_h
    )
    assert view.status_code == 200, view.text
    body = view.json()
    assert body["user_id"] == member_id
    assert body["bio"] == "Weekend volunteer"
    assert body["status"] == "working"
    assert [(s["id"], s["level"]) for s in body["skills"]] == [(pick["id"], 4)]
    assert [c["name"] for c in body["contacts"]] == ["Mom"]

    # A plain active member cannot read another member's profile.
    plain = await client.get(
        f"/orgs/{org_id}/members/{member_id}/volunteer-profile", headers=member_h
    )
    assert plain.status_code == 403, plain.text
    assert plain.json()["code"] == "FORBIDDEN"

    # A pending invitee is not a member yet, so the profile is not found.
    hidden = await client.get(
        f"/orgs/{org_id}/members/{pending_id}/volunteer-profile", headers=owner_h
    )
    assert hidden.status_code == 404, hidden.text
    assert hidden.json()["code"] == "MEMBER_NOT_FOUND"
