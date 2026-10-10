"""Integration tests: registration + attendance over HTTP."""

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
            "full_name": "Test User",
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


async def _published_activity(
    client: AsyncClient, owner: dict, slug: str
) -> str:
    created = await client.post(
        "/orgs",
        json={
            "name": f"Club {slug}",
            "slug": slug,
            "description": "",
            "kind": "club",
        },
        headers=owner,
    )
    assert created.status_code == 201, created.text
    org_id = created.json()["id"]
    activity = await client.post(
        f"/orgs/{org_id}/activities",
        json={
            "title": "River Cleanup",
            "location": "Hanoi",
            "start_at": "2030-06-01T08:00:00Z",
            "hours_awarded": 3.0,
        },
        headers=owner,
    )
    assert activity.status_code == 201, activity.text
    aid = activity.json()["id"]
    published = await client.post(
        f"/orgs/{org_id}/activities/{aid}/status",
        json={"status": "published"},
        headers=owner,
    )
    assert published.status_code == 200, published.text
    return aid


async def test_apply_review_checkin_checkout_flow(
    client: AsyncClient,
) -> None:
    owner = _headers(
        await _token(client, "r.own@example.com", "0903100010")
    )
    student = _headers(
        await _token(client, "r.stu@example.com", "0903100011")
    )
    outsider = _headers(
        await _token(client, "r.out@example.com", "0903100012")
    )
    aid = await _published_activity(client, owner, "reg-club")

    applied = await client.post(
        f"/activities/{aid}/registrations",
        json={"note": "excited"},
        headers=student,
    )
    assert applied.status_code == 201, applied.text
    reg = applied.json()
    assert reg["status"] == "pending"
    rid = reg["registration_id"]

    dup = await client.post(
        f"/activities/{aid}/registrations", json={}, headers=student
    )
    assert dup.status_code == 409
    assert dup.json()["code"] == "ALREADY_REGISTERED"

    roster_denied = await client.get(
        f"/activities/{aid}/registrations", headers=outsider
    )
    assert roster_denied.status_code == 403

    roster = await client.get(
        f"/activities/{aid}/registrations", headers=owner
    )
    assert roster.status_code == 200
    assert roster.json()[0]["student_email"] == "r.stu@example.com"

    waitlisted = await client.post(
        f"/activities/{aid}/registrations/{rid}/review",
        json={"status": "waitlisted"},
        headers=owner,
    )
    assert waitlisted.status_code == 200, waitlisted.text
    assert waitlisted.json()["status"] == "waitlisted"

    approved = await client.post(
        f"/activities/{aid}/registrations/{rid}/review",
        json={"status": "approved", "review_note": "ok"},
        headers=owner,
    )
    assert approved.status_code == 200, approved.text

    mine = await client.get("/registrations/mine", headers=student)
    assert mine.status_code == 200
    assert mine.json()[0]["status"] == "approved"

    ticket_denied = await client.get(
        f"/activities/{aid}/registrations/{rid}/ticket",
        headers=outsider,
    )
    assert ticket_denied.status_code == 403

    ticket = await client.get(
        f"/activities/{aid}/registrations/{rid}/ticket",
        headers=student,
    )
    assert ticket.status_code == 200
    token = ticket.json()["checkin_token"]

    checkin = await client.post(
        f"/activities/{aid}/checkin",
        json={"checkin_token": token},
        headers=owner,
    )
    assert checkin.status_code == 201, checkin.text
    record = checkin.json()
    assert record["method"] == "qr"

    double = await client.post(
        f"/activities/{aid}/checkin",
        json={"checkin_token": token},
        headers=owner,
    )
    assert double.status_code == 409
    assert double.json()["code"] == "ALREADY_CHECKED_IN"

    feed = await client.get(
        f"/activities/{aid}/attendance", headers=owner
    )
    assert feed.status_code == 200
    assert len(feed.json()) == 1

    checkout = await client.post(
        f"/activities/{aid}/attendance/{record['record_id']}/checkout",
        json={"actual_hours": 2.5},
        headers=owner,
    )
    assert checkout.status_code == 200, checkout.text
    assert checkout.json()["actual_hours"] == 2.5

    mine_att = await client.get("/attendance/mine", headers=student)
    assert mine_att.status_code == 200
    assert mine_att.json()[0]["record_id"] == record["record_id"]


async def test_cancel_reject_and_reapply(client: AsyncClient) -> None:
    owner = _headers(
        await _token(client, "r2.own@example.com", "0903100020")
    )
    student = _headers(
        await _token(client, "r2.stu@example.com", "0903100021")
    )
    aid = await _published_activity(client, owner, "reg-club2")

    first = await client.post(
        f"/activities/{aid}/registrations", json={}, headers=student
    )
    rid = first.json()["registration_id"]
    cancelled = await client.post(
        f"/activities/{aid}/registrations/{rid}/cancel",
        headers=student,
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"

    again = await client.post(
        f"/activities/{aid}/registrations", json={}, headers=student
    )
    assert again.status_code == 201, again.text
    assert again.json()["status"] == "pending"
    rid2 = again.json()["registration_id"]
    assert rid2 != rid

    rejected = await client.post(
        f"/activities/{aid}/registrations/{rid2}/review",
        json={"status": "rejected", "review_note": "full"},
        headers=owner,
    )
    assert rejected.status_code == 200

    cancel_rejected = await client.post(
        f"/activities/{aid}/registrations/{rid2}/cancel",
        headers=student,
    )
    assert cancel_rejected.status_code == 400

    third = await client.post(
        f"/activities/{aid}/registrations", json={}, headers=student
    )
    assert third.status_code == 201


async def test_apply_to_draft_fails(client: AsyncClient) -> None:
    owner = _headers(
        await _token(client, "r3.own@example.com", "0903100030")
    )
    student = _headers(
        await _token(client, "r3.stu@example.com", "0903100031")
    )
    created = await client.post(
        "/orgs",
        json={
            "name": "Draft Club",
            "slug": "reg-club3",
            "description": "",
            "kind": "club",
        },
        headers=owner,
    )
    org_id = created.json()["id"]
    activity = await client.post(
        f"/orgs/{org_id}/activities",
        json={
            "title": "Hidden Event",
            "start_at": "2030-06-01T08:00:00Z",
        },
        headers=owner,
    )
    aid = activity.json()["id"]
    closed = await client.post(
        f"/activities/{aid}/registrations", json={}, headers=student
    )
    assert closed.status_code == 400
    assert closed.json()["code"] == "REGISTRATION_CLOSED"
