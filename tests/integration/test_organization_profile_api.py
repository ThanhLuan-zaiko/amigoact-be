"""Legal details and pictures of an organization, through the HTTP API."""

import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.models.media import MediaAsset
from tests.conftest import ApiContext
from tests.media_helpers import WEBP, db_row, uploaded

Bearer = Callable[[str], dict[str, str]]


def create(
    api: ApiContext, headers: dict[str, str], name: str, **extra: Any
) -> dict[str, Any]:
    response = api.client.post(
        "/organizations", headers=headers, json={"name": name, **extra}
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def test_create_stores_contact_and_legal_details(
    api: ApiContext, bearer: Bearer
) -> None:
    headers = bearer(api.register()["tokens"]["access_token"])

    body = create(
        api,
        headers,
        f"CLB {api.tag}",
        email="contact@example.org",
        phone="0912345678",
        website="https://example.org",
        address="12 Le Loi",
        city="Hue",
        legal_name="Cong ty Test",
        tax_code="0101234567001",
        license_number="QD-12/2026",
        legal_rep_name="Nguyen Van A",
        legal_rep_position="Giam doc",
    )

    assert body["email"] == "contact@example.org"
    assert body["phone"] == "+84912345678"
    assert body["website"] == "https://example.org"
    assert body["address"] == "12 Le Loi"
    assert body["city"] == "Hue"
    assert body["legal_name"] == "Cong ty Test"
    assert body["tax_code"] == "0101234567-001"
    assert body["license_number"] == "QD-12/2026"
    assert body["legal_rep_name"] == "Nguyen Van A"
    assert body["legal_rep_position"] == "Giam doc"
    # Only a platform admin can verify, so a new organization starts unverified.
    assert body["legal_status"] == "none"
    assert body["logo_url"] is None
    assert body["cover_url"] is None


def test_create_attaches_uploaded_logo_and_cover(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    headers = bearer(api.register()["tokens"]["access_token"])
    logo = uploaded(api, headers)
    cover = uploaded(api, headers, WEBP)

    body = create(
        api,
        headers,
        f"CLB {api.tag}",
        logo_asset_id=logo["id"],
        cover_asset_id=cover["id"],
    )

    assert body["logo_url"] == f"/media/{logo['id']}/file"
    assert body["cover_url"] == f"/media/{cover['id']}/file"
    assert db_row(MediaAsset, uuid.UUID(logo["id"])).visibility == "public"
    assert db_row(MediaAsset, uuid.UUID(cover["id"])).visibility == "public"


def test_public_profile_serves_the_picture_to_anonymous_visitors(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    headers = bearer(api.register()["tokens"]["access_token"])
    logo = uploaded(api, headers)
    slug = create(api, headers, f"CLB {api.tag}", logo_asset_id=logo["id"])["slug"]

    profile = api.client.get(f"/organizations/{slug}")
    picture = api.client.get(profile.json()["logo_url"])

    assert profile.status_code == 200
    assert picture.status_code == 200
    assert picture.headers["content-type"] == "image/png"


def test_patch_updates_legal_details_and_keeps_the_logo(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    headers = bearer(api.register()["tokens"]["access_token"])
    logo = uploaded(api, headers)
    slug = create(api, headers, f"CLB {api.tag}", logo_asset_id=logo["id"])["slug"]

    response = api.client.patch(
        f"/organizations/{slug}",
        headers=headers,
        json={"legal_rep_name": "Tran Thi B", "tax_code": "0101234567"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["legal_rep_name"] == "Tran Thi B"
    assert body["tax_code"] == "0101234567"
    assert body["logo_url"] == f"/media/{logo['id']}/file"


def test_patch_with_null_clears_the_logo(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    headers = bearer(api.register()["tokens"]["access_token"])
    logo = uploaded(api, headers)
    slug = create(api, headers, f"CLB {api.tag}", logo_asset_id=logo["id"])["slug"]

    response = api.client.patch(
        f"/organizations/{slug}", headers=headers, json={"logo_asset_id": None}
    )

    assert response.status_code == 200
    assert response.json()["logo_url"] is None
