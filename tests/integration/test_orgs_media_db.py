"""Integration tests: org media endpoints over HTTP (amigoact_test)."""

from __future__ import annotations

from httpx import AsyncClient

PASSWORD = "Aa1!secure"


async def _token(client: AsyncClient, email: str, phone: str) -> str:
    response = await client.post(
        "/auth/register",
        json={"email": email, "phone": phone, "password": PASSWORD, "full_name": "Media User"},
    )
    assert response.status_code == 201, response.text
    logged = await client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert logged.status_code == 200, logged.text
    return logged.json()["access_token"]


async def _make_org(client: AsyncClient, headers: dict[str, str], slug: str) -> str:
    created = await client.post(
        "/orgs",
        json={"name": f"Name {slug}", "slug": slug, "description": "Desc", "kind": "club"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


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


async def test_upload_records_uploader_and_brand_sync(
    client: AsyncClient,
) -> None:
    """Registry fields land on upload; cover role feeds cover_media_id."""
    access = await _token(client, "upl@example.com", "0912345014")
    headers = {"Authorization": f"Bearer {access}"}
    me = await client.get("/auth/me", headers=headers)
    org_id = await _make_org(client, headers, "upl-club")

    uploaded = await client.post(
        f"/orgs/{org_id}/media",
        files={"file": ("cover.png", b"\x89PNG" + b"5" * 120, "image/png")},
        data={"role": "cover"},
        headers=headers,
    )
    assert uploaded.status_code == 201, uploaded.text
    body = uploaded.json()
    assert body["uploader_id"] == me.json()["id"]
    assert body["original_name"] == "cover.png"
    assert body["upload_status"] == "active"

    mine = await client.get("/orgs/mine", headers=headers)
    assert mine.json()["items"][0]["cover_media_id"] == body["id"]

    removed = await client.delete(
        f"/orgs/{org_id}/media/{body['id']}", headers=headers
    )
    assert removed.status_code == 204
    mine = await client.get("/orgs/mine", headers=headers)
    assert mine.json()["items"][0]["cover_media_id"] is None


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


async def test_replace_media_file_rewrites_in_place(client: AsyncClient) -> None:
    """PUT .../file swaps bytes under the same asset id, role and URL."""
    access = await _token(client, "replace@example.com", "0912345015")
    headers = {"Authorization": f"Bearer {access}"}
    org_id = await _make_org(client, headers, "replace-club")
    payload = b"\x89PNG" + b"1" * 200

    uploaded = await client.post(
        f"/orgs/{org_id}/media",
        files={"file": ("pic.png", payload, "image/png")},
        data={"role": "cover"},
        headers=headers,
    )
    assert uploaded.status_code == 201, uploaded.text
    body = uploaded.json()

    fresh = b"\x89PNG" + b"2" * 300
    replaced = await client.put(
        f"/orgs/{org_id}/media/{body['id']}/file",
        files={"file": ("pic2.png", fresh, "image/png")},
        headers=headers,
    )
    assert replaced.status_code == 200, replaced.text
    out = replaced.json()
    assert out["id"] == body["id"]
    assert out["role"] == "cover"
    assert out["file_url"] == body["file_url"]
    assert out["size_bytes"] == len(fresh)
    assert out["original_name"] == "pic2.png"
    assert out["updated_at"] is not None

    served = await client.get(out["file_url"])
    assert served.status_code == 200
    assert served.content == fresh

    # The brand pointer still targets the same asset.
    mine = await client.get("/orgs/mine", headers=headers)
    assert mine.json()["items"][0]["cover_media_id"] == body["id"]

    stranger = await _token(client, "replace2@example.com", "0912345016")
    denied = await client.put(
        f"/orgs/{org_id}/media/{body['id']}/file",
        files={"file": ("x.png", fresh, "image/png")},
        headers={"Authorization": f"Bearer {stranger}"},
    )
    assert denied.status_code == 403

    clip = await client.post(
        f"/orgs/{org_id}/media",
        files={"file": ("v.mp4", b"\x00\x00" + b"3" * 64, "video/mp4")},
        headers=headers,
    )
    assert clip.status_code == 201, clip.text
    rejected = await client.put(
        f"/orgs/{org_id}/media/{clip.json()['id']}/file",
        files={"file": ("v2.mp4", b"\x00\x00" + b"4" * 64, "video/mp4")},
        headers=headers,
    )
    assert rejected.status_code == 415
    assert rejected.json()["code"] == "UNSUPPORTED_MEDIA"
