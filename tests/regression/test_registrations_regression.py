"""Regression: freeze registration/attendance response contracts."""

from __future__ import annotations

from httpx import AsyncClient

PASSWORD = "Aa1!secure"

_REG_KEYS = {
    "registration_id",
    "activity_id",
    "student_id",
    "status",
    "note",
    "review_note",
    "registered_at",
    "reviewed_at",
    "cancelled_at",
    "slot_id",
}
_ROSTER_KEYS = {
    "registration_id",
    "student_id",
    "student_name",
    "student_email",
    "status",
    "note",
    "review_note",
    "registered_at",
    "form_data",
    "slot_id",
}
_TICKET_KEYS = {"registration_id", "checkin_token", "activity_id", "status"}
_ATT_KEYS = {
    "record_id",
    "activity_id",
    "student_id",
    "session_id",
    "method",
    "scanned_at",
    "checked_out_at",
    "check_out_method",
    "actual_hours",
}


async def _token(client: AsyncClient, email: str, phone: str) -> str:
    response = await client.post(
        "/auth/register",
        json={
            "email": email,
            "phone": phone,
            "password": PASSWORD,
            "full_name": "Reg User",
        },
    )
    assert response.status_code == 201, response.text
    logged = await client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    return logged.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _activity(client: AsyncClient, owner: dict, slug: str) -> str:
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
            "title": "Park Day",
            "start_at": "2030-06-01T08:00:00Z",
        },
        headers=owner,
    )
    aid = created.json()["id"]
    await client.post(
        f"/orgs/{org_id}/activities/{aid}/status",
        json={"status": "published"},
        headers=owner,
    )
    return aid


async def test_registration_response_shapes(client: AsyncClient) -> None:
    """Apply/roster/ticket/attendance payloads keep their exact keys."""
    owner = _headers(await _token(client, "g.own@example.com", "0903200010"))
    student = _headers(
        await _token(client, "g.stu@example.com", "0903200011")
    )
    aid = await _activity(client, owner, "reg-shape")

    applied = await client.post(
        f"/activities/{aid}/registrations",
        json={"note": "hi"},
        headers=student,
    )
    assert applied.status_code == 201, applied.text
    assert set(applied.json()) == _REG_KEYS
    rid = applied.json()["registration_id"]

    roster = await client.get(
        f"/activities/{aid}/registrations", headers=owner
    )
    assert set(roster.json()[0]) == _ROSTER_KEYS

    await client.post(
        f"/activities/{aid}/registrations/{rid}/review",
        json={"status": "approved"},
        headers=owner,
    )
    ticket = await client.get(
        f"/activities/{aid}/registrations/{rid}/ticket",
        headers=student,
    )
    assert set(ticket.json()) == _TICKET_KEYS

    checkin = await client.post(
        f"/activities/{aid}/checkin",
        json={"checkin_token": ticket.json()["checkin_token"]},
        headers=owner,
    )
    assert checkin.status_code == 201, checkin.text
    assert set(checkin.json()) == _ATT_KEYS


async def test_error_codes_locked(client: AsyncClient) -> None:
    """Domain error codes stay stable for FE copy tables."""
    owner = _headers(await _token(client, "h.own@example.com", "0903200020"))
    student = _headers(
        await _token(client, "h.stu@example.com", "0903200021")
    )
    aid = await _activity(client, owner, "reg-codes")

    applied = await client.post(
        f"/activities/{aid}/registrations", json={}, headers=student
    )
    rid = applied.json()["registration_id"]

    dup = await client.post(
        f"/activities/{aid}/registrations", json={}, headers=student
    )
    assert dup.status_code == 409
    assert dup.json()["code"] == "ALREADY_REGISTERED"

    bad_review = await client.post(
        f"/activities/{aid}/registrations/{rid}/review",
        json={"status": "bogus"},
        headers=owner,
    )
    assert bad_review.status_code in (400, 422)
