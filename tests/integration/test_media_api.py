import re
import uuid
from pathlib import Path

from src.models.activities import Activity
from src.models.auth import User
from src.models.media import MediaAsset
from src.models.organizations import Organization
from tests.activity_helpers import Bearer, draft, make_org, user
from tests.conftest import ApiContext
from tests.media_helpers import PNG, WEBP, db_row, org_id_for, set_avatar, uploaded


def test_upload_stores_a_private_file_under_a_generated_name(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    headers, user_id = user(api, bearer, "uploader")

    body = uploaded(api, headers)

    assert uuid.UUID(body["id"]).version == 7
    assert body["url"] == f"/media/{body['id']}/file"
    assert body["mime"] == "image/png"
    assert body["size_bytes"] == len(PNG)
    assert body["visibility"] == "private"
    row = db_row(MediaAsset, uuid.UUID(body["id"]))
    assert row.uploader_id == uuid.UUID(user_id)
    assert row.upload_status == "active"
    assert re.fullmatch(r"[0-9a-f]{32}\.png", row.storage_key)
    assert (media_root / row.storage_key).read_bytes() == PNG


def test_uploader_reads_the_file_back_with_safety_headers(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    headers, _ = user(api, bearer, "reader")
    body = uploaded(api, headers, WEBP)

    response = api.client.get(body["url"], headers=headers)

    assert response.status_code == 200
    assert response.content == WEBP
    assert response.headers["content-type"] == "image/webp"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"].startswith("private")


def test_avatar_makes_the_picture_public(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    headers, user_id = user(api, bearer, "avatar")
    body = uploaded(api, headers)

    response = set_avatar(api, headers, body["id"])

    assert response.status_code == 204
    assert db_row(User, uuid.UUID(user_id)).avatar_media_id == uuid.UUID(body["id"])
    assert db_row(MediaAsset, uuid.UUID(body["id"])).visibility == "public"
    anonymous = api.client.get(body["url"])
    assert anonymous.status_code == 200
    assert anonymous.headers["cache-control"].startswith("public")


def test_avatar_can_be_cleared(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    headers, user_id = user(api, bearer, "clear")
    body = uploaded(api, headers)
    set_avatar(api, headers, body["id"])

    response = set_avatar(api, headers, None)

    assert response.status_code == 204
    assert db_row(User, uuid.UUID(user_id)).avatar_media_id is None


def test_manager_sets_org_logo_and_cover(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    headers, _ = user(api, bearer, "org")
    slug = make_org(api, headers)
    logo = uploaded(api, headers)
    cover = uploaded(api, headers, WEBP)

    logo_response = api.client.put(
        f"/organizations/{slug}/logo", headers=headers, json={"asset_id": logo["id"]}
    )
    cover_response = api.client.put(
        f"/organizations/{slug}/cover", headers=headers, json={"asset_id": cover["id"]}
    )

    assert logo_response.status_code == 204
    assert cover_response.status_code == 204
    org = db_row(Organization, org_id_for(slug))
    assert org.logo_media_id == uuid.UUID(logo["id"])
    assert org.cover_media_id == uuid.UUID(cover["id"])


def test_manager_sets_activity_cover(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    headers, _ = user(api, bearer, "activity")
    slug = make_org(api, headers)
    activity = draft(api, headers, slug)
    cover = uploaded(api, headers)

    response = api.client.put(
        f"/activities/{activity['id']}/cover",
        headers=headers,
        json={"asset_id": cover["id"]},
    )

    assert response.status_code == 204
    row = db_row(Activity, uuid.UUID(activity["id"]))
    assert row.cover_media_id == uuid.UUID(cover["id"])
    assert api.client.get(cover["url"]).status_code == 200


def test_same_file_twice_by_one_person_is_stored_once(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    headers, _ = user(api, bearer, "twice")

    first = uploaded(api, headers)
    second = uploaded(api, headers)

    assert first["id"] == second["id"]
