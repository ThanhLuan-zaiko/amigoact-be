"""Regression: freeze the bulk mark-read contract (issue: read-all)."""

from __future__ import annotations

from httpx import AsyncClient

PASSWORD = "Aa1!secure"


async def _token(client: AsyncClient, email: str, phone: str) -> str:
    await client.post(
        "/auth/register",
        json={
            "email": email,
            "phone": phone,
            "password": PASSWORD,
            "full_name": "Test User",
        },
    )
    logged = await client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    return logged.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_read_all_response_shape_is_frozen(client: AsyncClient) -> None:
    """Contract lock: POST /notifications/read-all answers {"marked": int}
    and only ever sweeps the caller's own inbox."""
    owner = _headers(await _token(client, "fx.owner@example.com", "0900000030"))
    invitee = _headers(
        await _token(client, "fx.invitee@example.com", "0900000031")
    )
    bystander = _headers(
        await _token(client, "fx.other@example.com", "0900000032")
    )

    created = await client.post(
        "/orgs",
        json={
            "name": "Freeze Club",
            "slug": "freeze-club",
            "description": "",
            "kind": "club",
        },
        headers=owner,
    )
    await client.post(
        f"/orgs/{created.json()['id']}/members",
        json={"email": "fx.invitee@example.com"},
        headers=owner,
    )

    swept = await client.post("/notifications/read-all", headers=invitee)
    assert swept.status_code == 200, swept.text
    assert set(swept.json()) == {"marked"}
    assert swept.json()["marked"] == 1

    # A bystander's sweep must never leak into or drain another inbox.
    other = await client.post("/notifications/read-all", headers=bystander)
    assert other.json() == {"marked": 0}


async def test_notification_data_payload_is_frozen(
    client: AsyncClient,
) -> None:
    """Contract lock: emitted notifications carry deep-link identifiers so
    the client can jump straight to the related page."""
    owner = _headers(await _token(client, "dl.owner@example.com", "0900000040"))
    invitee = _headers(
        await _token(client, "dl.invitee@example.com", "0900000041")
    )
    created = await client.post(
        "/orgs",
        json={
            "name": "Link Club",
            "slug": "link-club",
            "description": "",
            "kind": "club",
        },
        headers=owner,
    )
    await client.post(
        f"/orgs/{created.json()['id']}/members",
        json={"email": "dl.invitee@example.com"},
        headers=owner,
    )
    inbox = await client.get("/notifications", headers=invitee)
    data = inbox.json()["items"][0]["data"]
    assert data == {
        "org_id": created.json()["id"],
        "org_slug": "link-club",
    }


async def test_read_all_requires_auth(client: AsyncClient) -> None:
    response = await client.post("/notifications/read-all")
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"
