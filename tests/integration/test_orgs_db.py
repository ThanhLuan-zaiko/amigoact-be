"""Integration tests: org endpoints over HTTP (amigoact_test)."""

from __future__ import annotations

from httpx import AsyncClient

PASSWORD = "Aa1!secure"


async def _token(client: AsyncClient, email: str, phone: str) -> str:
    response = await client.post(
        "/auth/register",
        json={"email": email, "phone": phone, "password": PASSWORD, "full_name": "Org User"},
    )
    assert response.status_code == 201, response.text
    logged = await client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert logged.status_code == 200, logged.text
    return logged.json()["access_token"]


async def test_create_and_list_mine(client: AsyncClient) -> None:
    access = await _token(client, "org1@example.com", "0912345678")
    headers = {"Authorization": f"Bearer {access}"}
    created = await client.post(
        "/orgs",
        json={"name": "Club A", "slug": "club-a", "description": "Good club", "kind": "club"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["member_count"] == 1

    duplicate = await client.post(
        "/orgs",
        json={"name": "Club B", "slug": "club-a", "description": "", "kind": "group"},
        headers=headers,
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "SLUG_TAKEN"

    mine = await client.get("/orgs/mine", headers=headers)
    assert mine.status_code == 200
    assert [o["slug"] for o in mine.json()["items"]] == ["club-a"]
    assert mine.json()["total"] == 1


async def test_mine_search_filter_sort_and_page(client: AsyncClient) -> None:
    access = await _token(client, "orgpage@example.com", "0912345679")
    headers = {"Authorization": f"Bearer {access}"}
    for name, slug in [("H\u1ed9i An", "hoi-an"), ("Da Nang", "da-nang"), ("Hue", "hue")]:
        made = await client.post(
            "/orgs",
            json={"name": name, "slug": slug, "description": "", "kind": "club"},
            headers=headers,
        )
        assert made.status_code == 201, made.text

    folded = await client.get("/orgs/mine?q=hoi+an", headers=headers)
    assert [o["slug"] for o in folded.json()["items"]] == ["hoi-an"]

    named = await client.get("/orgs/mine?sort=name", headers=headers)
    assert [o["slug"] for o in named.json()["items"]] == ["da-nang", "hoi-an", "hue"]
    assert named.json()["total"] == 3
    assert {c["bucket"]: c["count"] for c in named.json()["counts"]} == {"active": 3}

    first = await client.get("/orgs/mine?sort=name&limit=2&offset=0", headers=headers)
    assert [o["slug"] for o in first.json()["items"]] == ["da-nang", "hoi-an"]
    assert first.json()["total"] == 3
    second = await client.get("/orgs/mine?sort=name&limit=2&offset=2", headers=headers)
    assert [o["slug"] for o in second.json()["items"]] == ["hue"]

    pending = await client.get("/orgs/mine?status=pending", headers=headers)
    assert pending.json()["items"] == []
    assert pending.json()["total"] == 0

    bad_sort = await client.get("/orgs/mine?sort=oldest", headers=headers)
    assert bad_sort.status_code == 422


async def test_business_org_requires_legal_head(client: AsyncClient) -> None:
    access = await _token(client, "orgbiz@example.com", "0312345678")
    headers = {"Authorization": f"Bearer {access}"}
    missing = await client.post(
        "/orgs",
        json={"name": "Biz", "slug": "biz-1", "description": "", "kind": "business"},
        headers=headers,
    )
    assert missing.status_code == 422

    created = await client.post(
        "/orgs",
        json={
            "name": "Biz", "slug": "biz-1", "description": "",
            "kind": "business", "tax_code": "0312345678",
            "legal_rep_name": "Nguyen Van A", "legal_rep_id": "012345678901",
            "legal_rep_position": "Giam doc",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["legal_status"] == "pending"


async def test_business_register_then_create_org(client: AsyncClient) -> None:
    response = await client.post(
        "/auth/register",
        json={
            "email": "fullbiz@example.com", "phone": "0523456789",
            "password": PASSWORD, "full_name": "Cong Ty ABC",
            "account_type": "business", "tax_code": "0312345678",
            "company_name": "Cong Ty ABC", "legal_rep_name": "Nguyen Van A",
            "legal_rep_id": "012345678901", "legal_rep_position": "Giam doc",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["account_type"] == "business"


async def _make_org(client: AsyncClient, headers: dict[str, str], slug: str) -> str:
    created = await client.post(
        "/orgs",
        json={"name": f"Name {slug}", "slug": slug, "description": "Desc", "kind": "club"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def test_update_org_and_owner_guard(client: AsyncClient) -> None:
    access = await _token(client, "upd@example.com", "0912345001")
    headers = {"Authorization": f"Bearer {access}"}
    org_id = await _make_org(client, headers, "upd-club")

    renamed = await client.patch(
        f"/orgs/{org_id}", json={"name": "New Name", "description": "New desc"},
        headers=headers,
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "New Name"

    stranger = await _token(client, "stranger@example.com", "0912345002")
    hijack = await client.patch(
        f"/orgs/{org_id}", json={"name": "Hijack", "description": ""},
        headers={"Authorization": f"Bearer {stranger}"},
    )
    assert hijack.status_code == 403


async def test_soft_delete_restore_and_trash(client: AsyncClient) -> None:
    access = await _token(client, "trash@example.com", "0912345003")
    headers = {"Authorization": f"Bearer {access}"}
    org_id = await _make_org(client, headers, "trash-club")

    trashed = await client.delete(f"/orgs/{org_id}", headers=headers)
    assert trashed.status_code == 200, trashed.text
    assert trashed.json()["deleted_at"] is not None

    mine = await client.get("/orgs/mine", headers=headers)
    assert [o["slug"] for o in mine.json()["items"]] == []
    trash = await client.get("/orgs/mine?include_deleted=true", headers=headers)
    assert [o["slug"] for o in trash.json()["items"]] == ["trash-club"]

    blocked = await client.patch(
        f"/orgs/{org_id}", json={"name": "Edit Trash", "description": ""},
        headers=headers,
    )
    assert blocked.status_code == 410
    assert blocked.json()["code"] == "ORG_DELETED"

    restored = await client.post(f"/orgs/{org_id}/restore", headers=headers)
    assert restored.status_code == 200, restored.text
    assert restored.json()["deleted_at"] is None
    mine = await client.get("/orgs/mine", headers=headers)
    assert [o["slug"] for o in mine.json()["items"]] == ["trash-club"]


async def test_hard_delete_erases_rows_and_files(client: AsyncClient) -> None:
    import os
    import pathlib

    access = await _token(client, "gone@example.com", "0912345004")
    headers = {"Authorization": f"Bearer {access}"}
    org_id = await _make_org(client, headers, "gone-club")

    uploaded = await client.post(
        f"/orgs/{org_id}/media",
        files={"file": ("pic.png", b"\x89PNG" + b"0" * 100, "image/png")},
        headers=headers,
    )
    assert uploaded.status_code == 201, uploaded.text
    org_dir = pathlib.Path(os.environ["MEDIA_ROOT"]) / "orgs" / org_id
    assert org_dir.is_dir()

    erased = await client.delete(f"/orgs/{org_id}?hard=true", headers=headers)
    assert erased.status_code == 204, erased.text
    assert not org_dir.exists()
    mine = await client.get("/orgs/mine?include_deleted=true", headers=headers)
    assert mine.json()["items"] == []
