"""Regression tests: lock org role API contracts (envelope, codes)."""

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


async def test_role_envelope_and_error_codes(client: AsyncClient) -> None:
    """Role list keeps {items,assignable_permissions}; codes stay stable."""
    owner = await _token(client, "xown@example.com", "0912349001")
    headers = _headers(owner)
    org_id = await _make_org(client, headers, "x-club")

    listed = await client.get(f"/orgs/{org_id}/roles", headers=headers)
    assert listed.status_code == 200
    body = listed.json()
    assert set(body.keys()) == {"items", "assignable_permissions"}
    item = body["items"][0]
    assert {
        "id", "name", "description", "permissions", "member_count", "is_system"
    } <= set(item.keys())

    # Reserved names and unknown permissions keep their codes.
    for payload, code in (
        (
            {"name": "admin", "permissions": ["activity:view"]},
            "INVALID_ROLE",
        ),
        (
            {"name": "Ops", "permissions": ["sudo:all"]},
            "INVALID_ROLE",
        ),
    ):
        response = await client.post(
            f"/orgs/{org_id}/roles", json=payload, headers=headers
        )
        assert (response.status_code, response.json()["code"]) == (400, code)

    missing = await client.patch(
        f"/orgs/{org_id}/roles/0197f6a0-9c3b-7f2e-8d4a-b1c2d3e4f599",
        json={"name": "Ghost"},
        headers=headers,
    )
    assert (missing.status_code, missing.json()["code"]) == (
        404,
        "ROLE_NOT_FOUND",
    )
