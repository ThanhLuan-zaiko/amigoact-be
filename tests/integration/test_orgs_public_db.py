"""Integration tests: public org directory endpoints (amigoact_test)."""

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


async def _make_org(client: AsyncClient, headers: dict[str, str], slug: str) -> str:
    created = await client.post(
        "/orgs",
        json={"name": f"Name {slug}", "slug": slug, "description": "Desc", "kind": "club"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def test_public_directory_guest_readable(client: AsyncClient) -> None:
    """GET /orgs serves guests: orgs of any owner, no private fields."""
    access = await _token(client, "pub1@example.com", "0912345021")
    headers = {"Authorization": f"Bearer {access}"}
    await client.post(
        "/orgs",
        json={
            "name": "Public Club", "slug": "pub-club", "description": "Hi",
            "kind": "club", "email": "hi@club.vn", "city": "Da Nang",
        },
        headers=headers,
    )

    guests = await client.get("/orgs")
    assert guests.status_code == 200, guests.text
    body = guests.json()
    slugs = [o["slug"] for o in body["items"]]
    assert "pub-club" in slugs
    card = next(o for o in body["items"] if o["slug"] == "pub-club")
    for private in (
        "tax_code", "legal_rep_id", "owner_id", "email", "phone",
        "legal_status", "deleted_at",
    ):
        assert private not in card
    assert card["member_count"] == 1
    assert card["city"] == "Da Nang"
    assert card["owner_name"] == "Org User"
    assert card["owner_avatar_url"] is None


async def test_public_directory_carries_owner_avatar(
    client: AsyncClient,
) -> None:
    """Owner display identity rides the card: name plus avatar URL."""
    access = await _token(client, "pub-ava@example.com", "0912345024")
    headers = {"Authorization": f"Bearer {access}"}
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
    await _make_org(client, headers, "pub-ava")

    guests = await client.get("/orgs")
    assert guests.status_code == 200, guests.text
    card = next(
        o for o in guests.json()["items"] if o["slug"] == "pub-ava"
    )
    assert card["owner_name"] == "Org User"
    assert card["owner_avatar_url"] == uploaded.json()["avatar_url"]


async def test_public_directory_card_media_preview(
    client: AsyncClient,
) -> None:
    """Org cards carry a cover-first media strip: images and videos."""
    access = await _token(client, "pub-med@example.com", "0912345025")
    headers = {"Authorization": f"Bearer {access}"}
    org_id = await _make_org(client, headers, "pub-med")
    png = b"\x89PNG" + b"4" * 120

    image = await client.post(
        f"/orgs/{org_id}/media",
        files={"file": ("pic.png", png, "image/png")},
        data={"role": "cover"},
        headers=headers,
    )
    assert image.status_code == 201, image.text
    clip = await client.post(
        f"/orgs/{org_id}/media",
        files={"file": ("v.mp4", b"\x00\x00" + b"3" * 64, "video/mp4")},
        headers=headers,
    )
    assert clip.status_code == 201, clip.text

    guests = await client.get("/orgs")
    assert guests.status_code == 200, guests.text
    card = next(
        o for o in guests.json()["items"] if o["slug"] == "pub-med"
    )
    assert card["media_count"] == 2
    assert len(card["media"]) == 2
    assert card["media"][0]["url"] == image.json()["file_url"]
    assert {m["kind"] for m in card["media"]} == {"image", "video"}
    for tile in card["media"]:
        assert set(tile.keys()) == {"url", "kind", "mime"}


async def test_public_gallery_endpoint_lists_everything(
    client: AsyncClient,
) -> None:
    """GET /orgs/{slug}/gallery feeds the lightbox: cover-first, videos
    included, attachments out, guest-readable, dead orgs 404."""
    access = await _token(client, "pub-gal@example.com", "0912345026")
    headers = {"Authorization": f"Bearer {access}"}
    org_id = await _make_org(client, headers, "pub-gal")
    png = b"\x89PNG" + b"4" * 120

    cover = await client.post(
        f"/orgs/{org_id}/media",
        files={"file": ("c.png", png, "image/png")},
        data={"role": "cover"},
        headers=headers,
    )
    assert cover.status_code == 201, cover.text
    gallery: list[str] = []
    for index in range(3):
        made = await client.post(
            f"/orgs/{org_id}/media",
            files={"file": (f"g{index}.png", png, "image/png")},
            headers=headers,
        )
        assert made.status_code == 201, made.text
        gallery.append(made.json()["file_url"])
    clip = await client.post(
        f"/orgs/{org_id}/media",
        files={"file": ("v.mp4", b"\x00\x00" + b"3" * 64, "video/mp4")},
        headers=headers,
    )
    assert clip.status_code == 201, clip.text
    hidden = await client.post(
        f"/orgs/{org_id}/posts/media",
        files={"file": ("p.png", png, "image/png")},
        headers=headers,
    )
    assert hidden.status_code == 201, hidden.text

    listed = await client.get("/orgs/pub-gal/gallery")  # guest: no auth
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert set(body.keys()) == {"items"}
    urls = [item["url"] for item in body["items"]]
    assert urls[0] == cover.json()["file_url"]
    assert set(gallery) <= set(urls)
    assert clip.json()["file_url"] in urls
    assert hidden.json()["file_url"] not in urls
    assert len(urls) == 5  # cover + 3 gallery + 1 video
    for tile in body["items"]:
        assert set(tile.keys()) == {"url", "kind", "mime"}

    missing = await client.get("/orgs/no-such-org/gallery")
    assert missing.status_code == 404
    await client.delete(f"/orgs/{org_id}", headers=headers)
    trashed = await client.get("/orgs/pub-gal/gallery")
    assert trashed.status_code == 404


async def test_public_directory_hides_trashed_and_revives(
    client: AsyncClient,
) -> None:
    """Soft-deleted orgs leave the directory; restore puts them back."""
    access = await _token(client, "pub2@example.com", "0912345022")
    headers = {"Authorization": f"Bearer {access}"}
    gone_id = await _make_org(client, headers, "pub-gone")
    await _make_org(client, headers, "pub-live")

    await client.delete(f"/orgs/{gone_id}", headers=headers)
    guests = await client.get("/orgs")
    slugs = [o["slug"] for o in guests.json()["items"]]
    assert "pub-gone" not in slugs
    assert "pub-live" in slugs

    await client.post(f"/orgs/{gone_id}/restore", headers=headers)
    guests = await client.get("/orgs")
    slugs = [o["slug"] for o in guests.json()["items"]]
    assert "pub-gone" in slugs


async def test_public_directory_search_filter_sort_page(
    client: AsyncClient,
) -> None:
    """q folds diacritics, kind chips count pre-filter, paging keeps total."""
    access = await _token(client, "pub3@example.com", "0912345023")
    headers = {"Authorization": f"Bearer {access}"}
    for name, slug, kind in [
        ("H\u1ed9i An", "pub-hoi-an", "club"),
        ("Da Nang", "pub-da-nang", "club"),
        ("Hue", "pub-hue", "group"),
    ]:
        made = await client.post(
            "/orgs",
            json={"name": name, "slug": slug, "description": "", "kind": kind},
            headers=headers,
        )
        assert made.status_code == 201, made.text

    folded = await client.get("/orgs?q=hoi+an")
    assert "pub-hoi-an" in [o["slug"] for o in folded.json()["items"]]

    clubs = await client.get("/orgs?kind=club")
    slugs = [o["slug"] for o in clubs.json()["items"]]
    assert "pub-hoi-an" in slugs and "pub-da-nang" in slugs
    assert "pub-hue" not in slugs
    chips = {c["bucket"]: c["count"] for c in clubs.json()["counts"]}
    assert chips["club"] >= 2 and chips["group"] >= 1

    named = await client.get("/orgs?sort=name")
    ordered = [o["slug"] for o in named.json()["items"]]
    assert ordered.index("pub-da-nang") < ordered.index("pub-hoi-an")
    assert ordered.index("pub-hoi-an") < ordered.index("pub-hue")

    first = await client.get("/orgs?sort=name&limit=1&offset=0")
    second = await client.get("/orgs?sort=name&limit=1&offset=1")
    assert first.json()["total"] == second.json()["total"]
    assert (
        first.json()["items"][0]["slug"] != second.json()["items"][0]["slug"]
    )

    bad_kind = await client.get("/orgs?kind=weird")
    assert bad_kind.status_code == 422
    bad_sort = await client.get("/orgs?sort=oldest")
    assert bad_sort.status_code == 422


async def test_public_detail_guest_readable(client: AsyncClient) -> None:
    """GET /orgs/{slug} serves guests the profile plus trust signals."""
    access = await _token(client, "det1@example.com", "0912345031")
    headers = {"Authorization": f"Bearer {access}"}
    created = await client.post(
        "/orgs",
        json={
            "name": "Detail Club", "slug": "det-club", "description": "Hi",
            "kind": "club", "email": "hi@club.vn", "city": "Da Nang",
            "legal_name": "CLB Detail", "license_number": "LN-9",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text

    detail = await client.get("/orgs/det-club")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["slug"] == "det-club"
    assert body["member_count"] == 1
    assert body["email"] == "hi@club.vn"
    assert body["legal_name"] == "CLB Detail"
    assert body["activity_count"] == 0
    assert body["activities"] == []
    for private in (
        "owner_id", "legal_rep_id", "legal_rep_name", "legal_rep_position",
        "previous_slug", "deleted_at", "is_personal",
    ):
        assert private not in body


async def test_public_detail_404s_for_missing_and_trashed(
    client: AsyncClient,
) -> None:
    """Unknown slugs and soft-deleted orgs both 404 for guests."""
    missing = await client.get("/orgs/no-such-org")
    assert missing.status_code == 404

    access = await _token(client, "det2@example.com", "0912345032")
    headers = {"Authorization": f"Bearer {access}"}
    gone_id = await _make_org(client, headers, "det-gone")
    await client.delete(f"/orgs/{gone_id}", headers=headers)
    trashed = await client.get("/orgs/det-gone")
    assert trashed.status_code == 404


async def test_public_detail_lists_only_public_activities(
    client: AsyncClient,
) -> None:
    """Feed adapter hides drafts/cancelled and counts public rows."""
    from datetime import datetime, timezone

    from activities.model import ActivitiesByOrg, Activity
    from core.ids import uuid7

    access = await _token(client, "det3@example.com", "0912345033")
    headers = {"Authorization": f"Bearer {access}"}
    org_id = await _make_org(client, headers, "det-busy")
    now = datetime.now(timezone.utc)

    for status in ("published", "draft", "cancelled"):
        activity_id = uuid7()
        Activity.create(
            id=activity_id, org_id=org_id,
            title=f"Evt {status}", slug=f"evt-{status}",
            status=status, created_by=org_id,
            created_at=now, updated_at=now, start_at=now,
        )
        ActivitiesByOrg.create(
            org_id=org_id, start_at=now, activity_id=activity_id,
            title=f"Evt {status}", status=status,
        )

    detail = await client.get("/orgs/det-busy")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["activity_count"] == 1
    assert [a["status"] for a in body["activities"]] == ["published"]
    assert body["activities"][0]["slug"] == "evt-published"
