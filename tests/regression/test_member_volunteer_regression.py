"""Regression: freeze the manager volunteer-profile contract."""

from __future__ import annotations

from httpx import AsyncClient

PASSWORD = "Aa1!secure"


async def _token(client: AsyncClient, email: str, phone: str) -> str:
    response = await client.post(
        "/auth/register",
        json={"email": email, "phone": phone, "password": PASSWORD, "full_name": "Contract User"},
    )
    assert response.status_code == 201, response.text
    logged = await client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert logged.status_code == 200, logged.text
    return logged.json()["access_token"]


async def test_member_volunteer_profile_contract(client: AsyncClient) -> None:
    """Keys and empty defaults stay stable for a member with no profile yet."""
    owner_h = {"Authorization": "Bearer " + await _token(client, "rv.owner@example.com", "0912348001")}
    created = await client.post(
        "/orgs",
        json={
            "name": "Contract Club",
            "slug": "rv-club",
            "description": "Desc",
            "kind": "club",
            "join_policy": "invite",
        },
        headers=owner_h,
    )
    assert created.status_code == 201, created.text
    org_id = created.json()["id"]

    member_h = {"Authorization": "Bearer " + await _token(client, "rv.member@example.com", "0912348002")}
    invited = await client.post(
        f"/orgs/{org_id}/members", json={"email": "rv.member@example.com"}, headers=owner_h
    )
    member_id = invited.json()["user_id"]
    await client.post(f"/orgs/{org_id}/members/me/accept", headers=member_h)

    view = await client.get(
        f"/orgs/{org_id}/members/{member_id}/volunteer-profile", headers=owner_h
    )
    assert view.status_code == 200, view.text
    body = view.json()
    assert set(body) == {
        "user_id",
        "student_code",
        "class_name",
        "enrollment_year",
        "school_name",
        "bio",
        "interests",
        "status",
        "total_hours",
        "skills",
        "contacts",
    }
    assert body["skills"] == []
    assert body["contacts"] == []
    assert body["total_hours"] == 0.0
