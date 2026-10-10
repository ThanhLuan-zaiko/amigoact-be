"""Regression: freeze the profiles/skills HTTP contract (Phase 2)."""

from __future__ import annotations

from httpx import AsyncClient

PASSWORD = "Aa1!secure"


async def _token(client: AsyncClient, email: str, phone: str) -> str:
    created = await client.post(
        "/auth/register",
        json={
            "email": email,
            "phone": phone,
            "password": PASSWORD,
            "full_name": "Reg Volunteer",
        },
    )
    assert created.status_code == 201, created.text
    logged = await client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert logged.status_code == 200, logged.text
    return logged.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_profile_response_shape_locked(client: AsyncClient) -> None:
    """Profiles/me payload keys stay stable for the dashboard card."""
    headers = _headers(await _token(client, "r.prof@example.com", "0902000010"))
    response = await client.get("/profiles/me", headers=headers)
    assert response.status_code == 200
    assert set(response.json()) == {
        "student_code",
        "class_name",
        "enrollment_year",
        "school_name",
        "bio",
        "interests",
        "status",
        "total_hours",
        "updated_at",
        "skills",
        "contacts",
        "avatar_url",
    }

    skill = (await client.get("/skills")).json()[0]
    updated = await client.put(
        "/profiles/me/skills",
        json={"skills": [{"skill_id": skill["id"], "level": 3}]},
        headers=headers,
    )
    edge = updated.json()["skills"][0]
    assert set(edge) == {"id", "name", "slug", "level"}

    contact = await client.post(
        "/profiles/me/contacts",
        json={"name": "Mom", "phone": "0903333444"},
        headers=headers,
    )
    assert set(contact.json()["contacts"][0]) == {
        "contact_id",
        "name",
        "relation",
        "phone",
        "is_primary",
    }


async def test_skill_catalog_public_and_seeded(client: AsyncClient) -> None:
    """Catalog endpoint needs no auth and carries the seeded slugs."""
    response = await client.get("/skills")
    assert response.status_code == 200
    rows = response.json()
    assert set(rows[0]) == {"id", "name", "slug"}
    slugs = {row["slug"] for row in rows}
    assert {"first-aid", "teaching", "translation"} <= slugs


async def test_error_codes_locked(client: AsyncClient) -> None:
    """Domain codes stay stable so FE copy mapping never breaks."""
    headers = _headers(await _token(client, "r.err@example.com", "0902000011"))
    missing = await client.put(
        "/profiles/me/skills",
        json={
            "skills": [
                {
                    "skill_id": "0197f6a1-0001-7000-8000-999999999999",
                    "level": 1,
                }
            ]
        },
        headers=headers,
    )
    assert missing.status_code == 404
    assert missing.json()["code"] == "SKILL_NOT_FOUND"

    ghost = await client.get(
        "/profiles/0197f6a1-0001-7000-8000-999999999999"
    )
    assert ghost.status_code == 404
    assert ghost.json()["code"] == "NOT_FOUND"

    for index in range(3):
        await client.post(
            "/profiles/me/contacts",
            json={"name": f"C{index}", "phone": "0901234567"},
            headers=headers,
        )
    overflow = await client.post(
        "/profiles/me/contacts",
        json={"name": "Fourth", "phone": "0901234567"},
        headers=headers,
    )
    assert overflow.json()["code"] == "TOO_MANY_CONTACTS"
