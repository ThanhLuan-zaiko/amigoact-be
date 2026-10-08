"""Regression tests: frozen org and business-account contracts."""

from __future__ import annotations

from httpx import AsyncClient

PASSWORD = "Aa1!secure"


async def test_business_register_contract_locked(client: AsyncClient) -> None:
    """Business payload shape stays backward compatible with individuals."""
    individual = await client.post(
        "/auth/register",
        json={
            "email": "ind@example.com", "phone": "0912345678",
            "password": PASSWORD, "full_name": "Ca Nhan",
        },
    )
    assert individual.status_code == 201
    assert individual.json()["account_type"] == "individual"

    incomplete = await client.post(
        "/auth/register",
        json={
            "email": "badbiz@example.com", "phone": "0312345678",
            "password": PASSWORD, "full_name": "Thieu MST",
            "account_type": "business",
        },
    )
    assert incomplete.status_code == 422


async def test_org_legal_status_contract_locked(client: AsyncClient) -> None:
    """Club stays none, business stays pending; slug conflicts stay 409."""
    await client.post(
        "/auth/register",
        json={
            "email": "owner@example.com", "phone": "0777777779",
            "password": PASSWORD, "full_name": "Owner",
        },
    )
    logged = await client.post(
        "/auth/login", json={"email": "owner@example.com", "password": PASSWORD}
    )
    headers = {"Authorization": f"Bearer {logged.json()['access_token']}"}
    club = await client.post(
        "/orgs",
        json={"name": "Club", "slug": "locked-club", "description": "", "kind": "club"},
        headers=headers,
    )
    assert club.json()["legal_status"] == "none"
    clash = await client.post(
        "/orgs",
        json={"name": "Other", "slug": "locked-club", "description": "", "kind": "group"},
        headers=headers,
    )
    assert clash.status_code == 409
    assert set(clash.json().keys()) == {"code", "message"}
    assert clash.json()["code"] == "SLUG_TAKEN"


async def test_trash_and_media_contracts_locked(client: AsyncClient) -> None:
    """Soft delete hides, restore revives, hard delete 204s; media stays typed."""
    await client.post(
        "/auth/register",
        json={
            "email": "janitor@example.com", "phone": "0898765432",
            "password": PASSWORD, "full_name": "Janitor",
        },
    )
    logged = await client.post(
        "/auth/login", json={"email": "janitor@example.com", "password": PASSWORD}
    )
    headers = {"Authorization": f"Bearer {logged.json()['access_token']}"}
    created = await client.post(
        "/orgs",
        json={"name": "Temp", "slug": "temp-club", "description": "", "kind": "club"},
        headers=headers,
    )
    org_id = created.json()["id"]
    assert created.json()["deleted_at"] is None

    uploaded = await client.post(
        f"/orgs/{org_id}/media",
        files={"file": ("clip.mp4", b"\x00\x00" + b"2" * 64, "video/mp4")},
        headers=headers,
    )
    assert uploaded.status_code == 201
    assert uploaded.json()["kind"] == "video"

    await client.delete(f"/orgs/{org_id}", headers=headers)
    gallery = await client.get(f"/orgs/{org_id}/media", headers=headers)
    assert gallery.status_code == 410
    assert gallery.json()["code"] == "ORG_DELETED"

    await client.post(f"/orgs/{org_id}/restore", headers=headers)
    gallery = await client.get(f"/orgs/{org_id}/media", headers=headers)
    assert gallery.status_code == 200

    erased = await client.delete(f"/orgs/{org_id}?hard=true", headers=headers)
    assert erased.status_code == 204
    assert erased.text == ""


async def test_media_role_contract_locked(client: AsyncClient) -> None:
    """MediaResponse carries role; single-cover invariant + role codes hold."""
    await client.post(
        "/auth/register",
        json={
            "email": "gallery@example.com", "phone": "0888123456",
            "password": PASSWORD, "full_name": "Gallery Owner",
        },
    )
    logged = await client.post(
        "/auth/login", json={"email": "gallery@example.com", "password": PASSWORD}
    )
    headers = {"Authorization": f"Bearer {logged.json()['access_token']}"}
    created = await client.post(
        "/orgs",
        json={"name": "Gal", "slug": "gal-club", "description": "", "kind": "club"},
        headers=headers,
    )
    org_id = created.json()["id"]
    png = b"\x89PNG" + b"9" * 80

    plain = await client.post(
        f"/orgs/{org_id}/media",
        files={"file": ("p.png", png, "image/png")},
        headers=headers,
    )
    assert plain.status_code == 201
    assert set(plain.json().keys()) == {
        "id", "org_id", "kind", "role", "mime", "size_bytes", "file_url",
        "created_at",
    }
    assert plain.json()["role"] == "gallery"

    bad = await client.patch(
        f"/orgs/{org_id}/media/{plain.json()['id']}",
        json={"role": "weird"},
        headers=headers,
    )
    assert bad.status_code == 422

    marked_id = ""
    for name in ("c1.png", "c2.png"):
        marked = await client.post(
            f"/orgs/{org_id}/media",
            files={"file": (name, png, "image/png")},
            data={"role": "cover"},
            headers=headers,
        )
        assert marked.status_code == 201
        marked_id = marked.json()["id"]
    gallery = await client.get(f"/orgs/{org_id}/media", headers=headers)
    covers = [item for item in gallery.json() if item["role"] == "cover"]
    assert len(covers) == 1
    assert covers[0]["id"] == marked_id


async def test_media_bulk_delete_contract_locked(client: AsyncClient) -> None:
    """DELETE /orgs/{id}/media empties the collection with a bare 204."""
    await client.post(
        "/auth/register",
        json={
            "email": "wipe@example.com", "phone": "0555123456",
            "password": PASSWORD, "full_name": "Wiper",
        },
    )
    logged = await client.post(
        "/auth/login", json={"email": "wipe@example.com", "password": PASSWORD}
    )
    headers = {"Authorization": f"Bearer {logged.json()['access_token']}"}
    created = await client.post(
        "/orgs",
        json={"name": "Wipe", "slug": "wipe-club", "description": "", "kind": "club"},
        headers=headers,
    )
    org_id = created.json()["id"]
    png = b"\x89PNG" + b"5" * 80
    for name in ("x.png", "y.png"):
        uploaded = await client.post(
            f"/orgs/{org_id}/media",
            files={"file": (name, png, "image/png")},
            headers=headers,
        )
        assert uploaded.status_code == 201

    wiped = await client.delete(f"/orgs/{org_id}/media", headers=headers)
    assert wiped.status_code == 204
    assert wiped.text == ""
    gallery = await client.get(f"/orgs/{org_id}/media", headers=headers)
    assert gallery.status_code == 200
    assert gallery.json() == []


async def test_media_normalization_contract_locked(client: AsyncClient) -> None:
    """Non-web-safe image mimes transcode to jpeg/png; web-safe pass through."""
    from io import BytesIO

    from PIL import Image

    await client.post(
        "/auth/register",
        json={
            "email": "norm@example.com", "phone": "0344123456",
            "password": PASSWORD, "full_name": "Norm",
        },
    )
    logged = await client.post(
        "/auth/login", json={"email": "norm@example.com", "password": PASSWORD}
    )
    headers = {"Authorization": f"Bearer {logged.json()['access_token']}"}
    created = await client.post(
        "/orgs",
        json={"name": "Norm", "slug": "norm-club", "description": "", "kind": "club"},
        headers=headers,
    )
    org_id = created.json()["id"]

    buf = BytesIO()
    Image.new("RGB", (8, 8), (1, 2, 3)).save(buf, format="BMP")
    exotic = await client.post(
        f"/orgs/{org_id}/media",
        files={"file": ("raw.bmp", buf.getvalue(), "image/bmp")},
        headers=headers,
    )
    assert exotic.status_code == 201
    assert exotic.json()["mime"] in ("image/jpeg", "image/png")
    assert exotic.json()["file_url"].rsplit(".", 1)[-1] in ("jpg", "png")

    served = await client.get(exotic.json()["file_url"])
    assert served.status_code == 200
