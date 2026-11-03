"""Pictures and legal status must not be used to bypass ownership or verification."""

import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.app import app
from src.models.media import MediaAsset
from src.models.organizations import Organization
from tests.conftest import ORG_FIELDS, ApiContext
from tests.media_helpers import db_row, uploaded

Bearer = Callable[[str], dict[str, str]]


def organization_exists(name: str) -> bool:
    with Session(app.state.engine) as session:
        return (
            session.scalar(select(Organization.id).where(Organization.name == name))
            is not None
        )


def test_create_cannot_attach_someone_elses_private_picture(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    # A private upload belongs to its uploader, so another user must not publish it.
    stranger = bearer(api.register("stranger")["tokens"]["access_token"])
    private = uploaded(api, stranger)
    owner = bearer(api.register("owner")["tokens"]["access_token"])
    name = f"CLB {api.tag}"

    response = api.client.post(
        "/organizations",
        headers=owner,
        json={**ORG_FIELDS, "name": name, "logo_asset_id": private["id"]},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "media_not_found"
    assert not organization_exists(name)
    assert db_row(MediaAsset, uuid.UUID(private["id"])).visibility == "private"


def test_patch_cannot_attach_someone_elses_private_picture(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    owner = bearer(api.register("owner")["tokens"]["access_token"])
    stranger = bearer(api.register("stranger")["tokens"]["access_token"])
    private = uploaded(api, stranger)
    slug = api.client.post(
        "/organizations", headers=owner, json={**ORG_FIELDS, "name": f"CLB {api.tag}"}
    ).json()["slug"]

    response = api.client.patch(
        f"/organizations/{slug}",
        headers=owner,
        json={"cover_asset_id": private["id"]},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "media_not_found"
    profile = api.client.get(f"/organizations/{slug}").json()
    assert profile["cover_url"] is None


def test_owner_cannot_set_legal_status_to_verified(
    api: ApiContext, bearer: Bearer
) -> None:
    owner = bearer(api.register()["tokens"]["access_token"])

    created = api.client.post(
        "/organizations",
        headers=owner,
        json={**ORG_FIELDS, "name": f"CLB {api.tag}", "legal_status": "verified"},
    )
    assert created.status_code == 422
    assert created.json()["detail"][0]["type"] == "extra_forbidden"

    slug = api.client.post(
        "/organizations", headers=owner, json={**ORG_FIELDS, "name": f"CLB {api.tag}-2"}
    ).json()["slug"]
    patched = api.client.patch(
        f"/organizations/{slug}", headers=owner, json={"legal_status": "verified"}
    )
    assert patched.status_code == 422
    assert patched.json()["detail"][0]["type"] == "extra_forbidden"


def test_invalid_tax_code_is_rejected_with_a_stable_code(
    api: ApiContext, bearer: Bearer
) -> None:
    owner = bearer(api.register()["tokens"]["access_token"])

    response = api.client.post(
        "/organizations",
        headers=owner,
        json={**ORG_FIELDS, "name": f"CLB {api.tag}", "tax_code": "123"},
    )

    assert response.status_code == 422
    error: dict[str, Any] = response.json()["detail"][0]
    assert error["loc"][-1] == "tax_code"
    assert error["type"] == "tax_code_invalid"
