"""Regression: freeze hours/certificates response contracts."""

from __future__ import annotations

from httpx import AsyncClient

PASSWORD = "Aa1!secure"

_ENTRY_KEYS = {
    "entry_id",
    "student_id",
    "activity_id",
    "source",
    "hours",
    "term",
    "status",
    "note",
    "recorded_at",
    "approved_at",
}
_PENDING_KEYS = {
    "entry_id",
    "student_id",
    "activity_id",
    "hours",
    "recorded_at",
}
_MY_KEYS = {"entries", "summaries"}
_CERT_KEYS = {
    "certificate_id",
    "activity_id",
    "student_id",
    "serial_no",
    "status",
    "issued_at",
}
_VERIFY_KEYS = {
    "serial_no",
    "status",
    "activity_title",
    "student_name",
    "issued_at",
}


async def _token(client: AsyncClient, email: str, phone: str) -> str:
    response = await client.post(
        "/auth/register",
        json={
            "email": email,
            "phone": phone,
            "password": PASSWORD,
            "full_name": "Shape User",
        },
    )
    assert response.status_code == 201, response.text
    logged = await client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    return logged.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _attended(
    client: AsyncClient, slug: str
) -> tuple[dict, dict, str, str, str]:
    owner = _headers(await _token(client, f"o.{slug}@example.com", "0903400010"))
    student = _headers(await _token(client, f"u.{slug}@example.com", "0903400011"))
    org = await client.post(
        "/orgs",
        json={
            "name": f"Club {slug}",
            "slug": slug,
            "description": "",
            "kind": "club",
        },
        headers=owner,
    )
    org_id = org.json()["id"]
    created = await client.post(
        f"/orgs/{org_id}/activities",
        json={
            "title": "Shape Event",
            "start_at": "2030-06-01T08:00:00Z",
            "hours_awarded": 4.0,
        },
        headers=owner,
    )
    aid = created.json()["id"]
    await client.post(
        f"/orgs/{org_id}/activities/{aid}/status",
        json={"status": "published"},
        headers=owner,
    )
    applied = await client.post(
        f"/activities/{aid}/registrations", json={}, headers=student
    )
    rid = applied.json()["registration_id"]
    await client.post(
        f"/activities/{aid}/registrations/{rid}/review",
        json={"status": "approved"},
        headers=owner,
    )
    ticket = await client.get(
        f"/activities/{aid}/registrations/{rid}/ticket",
        headers=student,
    )
    checkin = await client.post(
        f"/activities/{aid}/checkin",
        json={"checkin_token": ticket.json()["checkin_token"]},
        headers=owner,
    )
    await client.post(
        f"/activities/{aid}/attendance/{checkin.json()['record_id']}/checkout",
        json={"actual_hours": 2.0},
        headers=owner,
    )
    me = await client.get("/auth/me", headers=student)
    return owner, student, org_id, aid, me.json()["id"]


async def test_hours_response_shapes(client: AsyncClient) -> None:
    owner, student, org_id, aid, student_id = await _attended(
        client, "shape"
    )
    queue = await client.get(
        f"/orgs/{org_id}/hours/pending", headers=owner
    )
    assert set(queue.json()[0]) == _PENDING_KEYS

    entry_id = queue.json()[0]["entry_id"]
    reviewed = await client.post(
        f"/hours/{entry_id}/review",
        json={"status": "approved"},
        headers=owner,
    )
    assert set(reviewed.json()) == _ENTRY_KEYS

    mine = await client.get("/hours/mine", headers=student)
    assert set(mine.json()) == _MY_KEYS
    assert set(mine.json()["summaries"][0]) == {
        "term",
        "total_hours",
        "activities_count",
    }


async def test_certificate_response_shapes(client: AsyncClient) -> None:
    owner, student, org_id, aid, student_id = await _attended(
        client, "shape2"
    )
    issued = await client.post(
        f"/activities/{aid}/certificates/{student_id}",
        headers=owner,
    )
    assert issued.status_code == 201, issued.text
    assert set(issued.json()) == _CERT_KEYS

    verified = await client.get(
        f"/certificates/verify/{issued.json()['serial_no']}"
    )
    assert set(verified.json()) == _VERIFY_KEYS


async def test_unauthenticated_hours_access_401(
    client: AsyncClient,
) -> None:
    response = await client.get("/hours/mine")
    assert response.status_code == 401
