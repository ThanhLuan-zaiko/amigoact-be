"""Integration tests: notification inbox over HTTP (amigoact_test)."""

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


async def test_invite_emits_notification_and_read_flow(
    client: AsyncClient,
) -> None:
    owner = _headers(await _token(client, "n.owner@example.com", "0900000010"))
    invitee = _headers(
        await _token(client, "n.invitee@example.com", "0900000011")
    )
    stranger = _headers(
        await _token(client, "n.stranger@example.com", "0900000012")
    )

    created = await client.post(
        "/orgs",
        json={
            "name": "Notify Club",
            "slug": "notify-club",
            "description": "",
            "kind": "club",
        },
        headers=owner,
    )
    assert created.status_code == 201, created.text
    org_id = created.json()["id"]

    invited = await client.post(
        f"/orgs/{org_id}/members",
        json={"email": "n.invitee@example.com"},
        headers=owner,
    )
    assert invited.status_code == 201, invited.text

    inbox = await client.get("/notifications", headers=invitee)
    assert inbox.status_code == 200
    body = inbox.json()
    assert body["unread"] == 1
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["type"] == "membership"
    assert item["status"] == "unread"
    assert "Notify Club" in item["title"]

    foreign = await client.post(
        f"/notifications/{item['id']}/read", headers=stranger
    )
    assert foreign.status_code == 403

    read = await client.post(
        f"/notifications/{item['id']}/read", headers=invitee
    )
    assert read.status_code == 200
    assert read.json()["status"] == "read"
    assert read.json()["read_at"] is not None

    after = await client.get("/notifications", headers=invitee)
    assert after.json()["unread"] == 0


async def test_notifications_require_auth(client: AsyncClient) -> None:
    response = await client.get("/notifications")
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"
