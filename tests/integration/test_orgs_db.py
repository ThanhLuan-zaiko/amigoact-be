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
    for name, slug in [("Hội An", "hoi-an"), ("Da Nang", "da-nang"), ("Hue", "hue")]:
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


async def test_upload_list_serve_delete_media(client: AsyncClient) -> None:
    access = await _token(client, "media@example.com", "0912345005")
    headers = {"Authorization": f"Bearer {access}"}
    org_id = await _make_org(client, headers, "media-club")
    payload = b"\x89PNG" + b"1" * 200

    uploaded = await client.post(
        f"/orgs/{org_id}/media",
        files={"file": ("pic.png", payload, "image/png")},
        headers=headers,
    )
    assert uploaded.status_code == 201, uploaded.text
    body = uploaded.json()
    assert body["mime"] == "image/png"
    assert body["file_url"].startswith("/media/orgs/")

    bad = await client.post(
        f"/orgs/{org_id}/media",
        files={"file": ("doc.pdf", b"%PDF", "application/pdf")},
        headers=headers,
    )
    assert bad.status_code == 415

    gallery = await client.get(f"/orgs/{org_id}/media", headers=headers)
    assert gallery.status_code == 200
    assert len(gallery.json()) == 1

    served = await client.get(body["file_url"])
    assert served.status_code == 200
    assert served.content == payload

    removed = await client.delete(
        f"/orgs/{org_id}/media/{body['id']}", headers=headers
    )
    assert removed.status_code == 204
    gallery = await client.get(f"/orgs/{org_id}/media", headers=headers)
    assert gallery.json() == []
    assert (await client.get(body["file_url"])).status_code == 404


async def test_media_roles_cover_and_logo(client: AsyncClient) -> None:
    """One cover and one logo per org; brand roles are owner-only images."""
    access = await _token(client, "brand@example.com", "0912345006")
    headers = {"Authorization": f"Bearer {access}"}
    org_id = await _make_org(client, headers, "brand-club")
    png = b"\x89PNG" + b"7" * 120

    first = await client.post(
        f"/orgs/{org_id}/media",
        files={"file": ("a.png", png, "image/png")},
        data={"role": "cover"},
        headers=headers,
    )
    assert first.status_code == 201, first.text
    assert first.json()["role"] == "cover"

    second = await client.post(
        f"/orgs/{org_id}/media",
        files={"file": ("b.png", png, "image/png")},
        data={"role": "cover"},
        headers=headers,
    )
    assert second.status_code == 201, second.text
    gallery = await client.get(f"/orgs/{org_id}/media", headers=headers)
    covers = [item["id"] for item in gallery.json() if item["role"] == "cover"]
    assert covers == [second.json()["id"]]

    remark = await client.patch(
        f"/orgs/{org_id}/media/{first.json()['id']}",
        json={"role": "logo"},
        headers=headers,
    )
    assert remark.status_code == 200, remark.text
    assert remark.json()["role"] == "logo"

    video_cover = await client.post(
        f"/orgs/{org_id}/media",
        files={"file": ("v.mp4", b"\x00\x00" + b"3" * 64, "video/mp4")},
        data={"role": "cover"},
        headers=headers,
    )
    assert video_cover.status_code == 400
    assert video_cover.json()["code"] == "INVALID_MEDIA_ROLE"

    stranger = await _token(client, "brand2@example.com", "0912345007")
    hijack = await client.patch(
        f"/orgs/{org_id}/media/{second.json()['id']}",
        json={"role": "logo"},
        headers={"Authorization": f"Bearer {stranger}"},
    )
    assert hijack.status_code == 403

    cleared = await client.patch(
        f"/orgs/{org_id}/media/{first.json()['id']}",
        json={"role": "gallery"},
        headers=headers,
    )
    assert cleared.status_code == 200
    assert cleared.json()["role"] == "gallery"


async def test_exotic_image_normalized_on_upload(client: AsyncClient) -> None:
    """HEIC/TIFF uploads transcode to web-safe jpeg/png and still serve."""
    import pathlib
    import os

    from io import BytesIO

    from PIL import Image

    access = await _token(client, "exotic@example.com", "0912345010")
    headers = {"Authorization": f"Bearer {access}"}
    org_id = await _make_org(client, headers, "exotic-club")

    buf = BytesIO()
    Image.new("RGB", (12, 12), (10, 90, 200)).save(buf, format="TIFF")
    uploaded = await client.post(
        f"/orgs/{org_id}/media",
        files={"file": ("scan.tiff", buf.getvalue(), "image/tiff")},
        headers=headers,
    )
    assert uploaded.status_code == 201, uploaded.text
    body = uploaded.json()
    assert body["kind"] == "image"
    assert body["mime"] == "image/jpeg"
    assert body["file_url"].endswith(".jpg")

    served = await client.get(body["file_url"])
    assert served.status_code == 200
    assert served.content[:2] == b"\xff\xd8"
    assert not (
        pathlib.Path(os.environ["MEDIA_ROOT"]) / "orgs" / org_id / "scan.tiff"
    ).exists()


async def test_delete_all_media_wipes_gallery(client: AsyncClient) -> None:
    """Owner wipes the whole collection; strangers get 403."""
    import os
    import pathlib

    access = await _token(client, "wipe@example.com", "0912345008")
    headers = {"Authorization": f"Bearer {access}"}
    org_id = await _make_org(client, headers, "wipe-club")
    png = b"\x89PNG" + b"9" * 120
    for name in ("a.png", "b.png"):
        uploaded = await client.post(
            f"/orgs/{org_id}/media",
            files={"file": (name, png, "image/png")},
            headers=headers,
        )
        assert uploaded.status_code == 201, uploaded.text
    org_dir = pathlib.Path(os.environ["MEDIA_ROOT"]) / "orgs" / org_id
    assert len(list(org_dir.iterdir())) == 2

    stranger = await _token(client, "wipe2@example.com", "0912345009")
    denied = await client.delete(
        f"/orgs/{org_id}/media",
        headers={"Authorization": f"Bearer {stranger}"},
    )
    assert denied.status_code == 403

    wiped = await client.delete(f"/orgs/{org_id}/media", headers=headers)
    assert wiped.status_code == 204
    gallery = await client.get(f"/orgs/{org_id}/media", headers=headers)
    assert gallery.json() == []
    assert list(org_dir.iterdir()) == []
