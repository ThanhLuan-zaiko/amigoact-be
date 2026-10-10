"""Integration tests: hours ledger + certificates over HTTP."""

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


async def _setup_attended(
    client: AsyncClient, slug: str
) -> tuple[dict, dict, str, str, str]:
    """Org+published activity, student approved and checked in/out."""
    owner = _headers(await _token(client, f"h.{slug}@example.com", "0903300010"))
    student = _headers(await _token(client, f"s.{slug}@example.com", "0903300011"))
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
            "title": "Cleanup",
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
    record_id = checkin.json()["record_id"]
    await client.post(
        f"/activities/{aid}/attendance/{record_id}/checkout",
        json={"actual_hours": 3.0},
        headers=owner,
    )
    me = await client.get("/auth/me", headers=student)
    return owner, student, org_id, aid, me.json()["id"]


async def test_checkout_queues_and_approval_rolls_up(
    client: AsyncClient,
) -> None:
    owner, student, org_id, aid, student_id = await _setup_attended(
        client, "hr1"
    )
    queue = await client.get(
        f"/orgs/{org_id}/hours/pending", headers=owner
    )
    assert queue.status_code == 200, queue.text
    rows = queue.json()
    assert len(rows) == 1
    entry_id = rows[0]["entry_id"]
    assert rows[0]["hours"] == 3.0

    approved = await client.post(
        f"/hours/{entry_id}/review",
        json={"status": "approved"},
        headers=owner,
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"

    empty = await client.get(
        f"/orgs/{org_id}/hours/pending", headers=owner
    )
    assert empty.json() == []

    mine = await client.get("/hours/mine", headers=student)
    assert mine.status_code == 200
    body = mine.json()
    assert len(body["entries"]) == 1
    assert body["entries"][0]["status"] == "approved"
    total = sum(s["total_hours"] for s in body["summaries"])
    assert total == 3.0


async def test_manual_hours_and_reject(client: AsyncClient) -> None:
    owner, student, org_id, aid, student_id = await _setup_attended(
        client, "hr2"
    )
    outsider = _headers(
        await _token(client, "x.hr2@example.com", "0903300099")
    )
    denied = await client.post(
        f"/orgs/{org_id}/hours",
        json={
            "student_id": student_id,
            "activity_id": aid,
            "hours": 1.0,
        },
        headers=outsider,
    )
    assert denied.status_code == 403

    manual = await client.post(
        f"/orgs/{org_id}/hours",
        json={
            "student_id": student_id,
            "activity_id": aid,
            "hours": 1.5,
            "note": "extra help",
        },
        headers=owner,
    )
    assert manual.status_code == 201, manual.text
    entry_id = manual.json()["entry_id"]

    rejected = await client.post(
        f"/hours/{entry_id}/review",
        json={"status": "rejected", "note": "not verified"},
        headers=owner,
    )
    assert rejected.status_code == 200

    again = await client.post(
        f"/hours/{entry_id}/review",
        json={"status": "approved"},
        headers=owner,
    )
    assert again.status_code == 400
    assert again.json()["code"] == "INVALID_HOURS_STATE"

    mine = await client.get("/hours/mine", headers=student)
    assert mine.json()["summaries"] == []


async def test_certificates_flow(client: AsyncClient) -> None:
    owner, student, org_id, aid, student_id = await _setup_attended(
        client, "hr3"
    )
    issued = await client.post(
        f"/activities/{aid}/certificates/{student_id}",
        headers=owner,
    )
    assert issued.status_code == 201, issued.text
    cert = issued.json()
    assert cert["serial_no"].startswith("AMG-")
    assert cert["status"] == "issued"

    dup = await client.post(
        f"/activities/{aid}/certificates/{student_id}",
        headers=owner,
    )
    assert dup.status_code == 409
    assert dup.json()["code"] == "CERTIFICATE_EXISTS"

    verified = await client.get(
        f"/certificates/verify/{cert['serial_no']}"
    )
    assert verified.status_code == 200
    assert verified.json()["status"] == "issued"
    assert verified.json()["activity_title"] == "Cleanup"

    wall = await client.get("/certificates/mine", headers=student)
    assert wall.status_code == 200
    assert wall.json()[0]["serial_no"] == cert["serial_no"]

    revoked = await client.post(
        f"/activities/{aid}/certificates/{student_id}/revoke",
        json={"reason": "mistake"},
        headers=owner,
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"

    after = await client.get(f"/certificates/verify/{cert['serial_no']}")
    assert after.json()["status"] == "revoked"

    missing = await client.get("/certificates/verify/AMG-2026-ZZZZ")
    assert missing.status_code == 404
