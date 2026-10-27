"""Integration tests: volunteer profiles over HTTP (amigoact_test)."""

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
            "full_name": "Test Volunteer",
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


async def _user_id(client: AsyncClient, token: str) -> str:
    me = await client.get("/auth/me", headers=_headers(token))
    assert me.status_code == 200, me.text
    return me.json()["id"]


async def test_profile_roundtrip_and_public_card(
    client: AsyncClient,
) -> None:
    headers = _headers(await _token(client, "p.one@example.com", "0901000010"))

    empty = await client.get("/profiles/me", headers=headers)
    assert empty.status_code == 200
    assert empty.json()["student_code"] is None
    assert empty.json()["skills"] == []

    missing = await client.put("/profiles/me", json={}, headers=headers)
    assert missing.status_code == 422
    student_blank = await client.put(
        "/profiles/me",
        json={
            "student_code": " ",
            "class_name": "CTK43",
            "school_name": "Bach Khoa",
            "status": "studying",
        },
        headers=headers,
    )
    assert student_blank.status_code == 422
    grad_no_school = await client.put(
        "/profiles/me", json={"status": "graduated"}, headers=headers
    )
    assert grad_no_school.status_code == 422
    working_empty = await client.put(
        "/profiles/me", json={"status": "working"}, headers=headers
    )
    assert working_empty.status_code == 422
    working_ok = await client.put(
        "/profiles/me",
        json={"status": "working", "bio": "Retail staff"},
        headers=headers,
    )
    assert working_ok.status_code == 200, working_ok.text

    updated = await client.put(
        "/profiles/me",
        json={
            "student_code": "SV100",
            "class_name": "CTK43",
            "enrollment_year": 2022,
            "school_name": "Bach Khoa",
            "bio": "Love volunteering",
            "interests": ["beach", "code"],
            "status": "studying",
        },
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["student_code"] == "SV100"
    assert sorted(body["interests"]) == ["beach", "code"]

    catalog = await client.get("/skills")
    assert catalog.status_code == 200
    skills = catalog.json()
    assert len(skills) >= 10
    pick = skills[0]

    with_skills = await client.put(
        "/profiles/me/skills",
        json={"skills": [{"skill_id": pick["id"], "level": 4}]},
        headers=headers,
    )
    assert with_skills.status_code == 200, with_skills.text
    edge = with_skills.json()["skills"][0]
    assert edge["id"] == pick["id"]
    assert edge["name"] == pick["name"]
    assert edge["level"] == 4

    bad_skill = await client.put(
        "/profiles/me/skills",
        json={
            "skills": [
                {
                    "skill_id": "0197f6a1-0001-7000-8000-999999999999",
                    "level": 3,
                }
            ]
        },
        headers=headers,
    )
    assert bad_skill.status_code == 404
    assert bad_skill.json()["code"] == "SKILL_NOT_FOUND"

    bad_level = await client.put(
        "/profiles/me/skills",
        json={"skills": [{"skill_id": pick["id"], "level": 9}]},
        headers=headers,
    )
    assert bad_level.status_code == 422

    uid = await _user_id(client, headers["Authorization"].split()[1])
    card = await client.get(f"/profiles/{uid}")
    assert card.status_code == 200, card.text
    public = card.json()
    assert public["full_name"] == "Test Volunteer"
    assert public["school_name"] == "Bach Khoa"
    assert len(public["skills"]) == 1
    assert "contacts" not in public


async def test_contacts_replace_roundtrip(client: AsyncClient) -> None:
    headers = _headers(await _token(client, "p.contacts@example.com", "0901000042"))

    saved = await client.put(
        "/profiles/me/contacts",
        json={
            "contacts": [
                {"name": "Mom", "relation": "M\u1eb9", "phone": "0901234567"},
                {"name": "Dad", "phone": "0907654321"},
            ]
        },
        headers=headers,
    )
    assert saved.status_code == 200, saved.text
    rows = saved.json()["contacts"]
    assert sorted(row["name"] for row in rows) == ["Dad", "Mom"]
    assert [row["name"] for row in rows if row["is_primary"]] == ["Mom"]

    mom_id = next(row["contact_id"] for row in rows if row["name"] == "Mom")
    kept = await client.put(
        "/profiles/me/contacts",
        json={
            "contacts": [
                {
                    "contact_id": mom_id,
                    "name": "Mom",
                    "relation": "M\u1eb9",
                    "phone": "0901234567",
                }
            ]
        },
        headers=headers,
    )
    assert kept.status_code == 200, kept.text
    assert [row["contact_id"] for row in kept.json()["contacts"]] == [mom_id]
    assert kept.json()["contacts"][0]["is_primary"] is True

    cleared = await client.put(
        "/profiles/me/contacts", json={"contacts": []}, headers=headers
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["contacts"] == []


async def test_emergency_contacts_flow(client: AsyncClient) -> None:
    headers = _headers(await _token(client, "p.two@example.com", "0901000011"))

    first = await client.post(
        "/profiles/me/contacts",
        json={"name": "Mom", "relation": "mother", "phone": "0903333444"},
        headers=headers,
    )
    assert first.status_code == 201, first.text
    assert first.json()["contacts"][0]["is_primary"] is True

    second = await client.post(
        "/profiles/me/contacts",
        json={
            "name": "Dad",
            "relation": "father",
            "phone": "0905555666",
            "is_primary": True,
        },
        headers=headers,
    )
    assert second.status_code == 201
    contacts = second.json()["contacts"]
    assert len(contacts) == 2
    assert sum(1 for c in contacts if c["is_primary"]) == 1

    dad = next(c for c in contacts if c["name"] == "Dad")
    removed = await client.delete(
        f"/profiles/me/contacts/{dad['contact_id']}", headers=headers
    )
    assert removed.status_code == 200
    survivors = removed.json()["contacts"]
    assert len(survivors) == 1
    assert survivors[0]["is_primary"] is True

    ghost = await client.delete(
        f"/profiles/me/contacts/{dad['contact_id']}", headers=headers
    )
    assert ghost.status_code == 404


async def test_contacts_cap_and_auth_required(client: AsyncClient) -> None:
    headers = _headers(await _token(client, "p.three@example.com", "0901000012"))
    for index in range(3):
        created = await client.post(
            "/profiles/me/contacts",
            json={"name": f"C{index}", "phone": f"090{index}111111"},
            headers=headers,
        )
        assert created.status_code == 201
    overflow = await client.post(
        "/profiles/me/contacts",
        json={"name": "Fourth", "phone": "0909999999"},
        headers=headers,
    )
    assert overflow.status_code == 400
    assert overflow.json()["code"] == "TOO_MANY_CONTACTS"

    anon = await client.get("/profiles/me")
    assert anon.status_code == 401


async def test_avatar_upload_and_replace(client: AsyncClient) -> None:
    headers = _headers(await _token(client, "p.four@example.com", "0901000013"))
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\x0bIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
        b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    uploaded = await client.post(
        "/profiles/me/avatar",
        files={"file": ("me.png", png, "image/png")},
        headers=headers,
    )
    assert uploaded.status_code == 200, uploaded.text
    url = uploaded.json()["avatar_url"]
    assert url.startswith("/media/users/")

    me = await client.get("/profiles/me", headers=headers)
    assert me.json()["avatar_url"] == url

    replaced = await client.post(
        "/profiles/me/avatar",
        files={"file": ("new.png", png, "image/png")},
        headers=headers,
    )
    assert replaced.status_code == 200
    assert replaced.json()["avatar_url"] != url

    wrong = await client.post(
        "/profiles/me/avatar",
        files={"file": ("clip.mp4", b"data", "video/mp4")},
        headers=headers,
    )
    assert wrong.status_code == 415
    assert wrong.json()["code"] == "UNSUPPORTED_MEDIA"
