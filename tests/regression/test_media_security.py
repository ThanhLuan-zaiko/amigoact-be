import uuid
from pathlib import Path

from src.models.media import MediaAsset
from src.models.organizations import Organization
from tests.activity_helpers import Bearer, make_org, user
from tests.conftest import ApiContext
from tests.media_helpers import (
    JPEG,
    PNG,
    db_row,
    org_id_for,
    set_avatar,
    upload,
    uploaded,
)


def test_text_with_an_image_name_is_rejected(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    headers, _ = user(api, bearer, "fake")

    response = upload(api, headers, data=b"<script>alert(1)</script>")

    assert response.status_code == 415
    assert response.json()["detail"] == "unsupported_media_type"
    assert list(media_root.iterdir()) == []


def test_empty_file_is_rejected(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    headers, _ = user(api, bearer, "empty")

    response = upload(api, headers, data=b"")

    assert response.status_code == 400
    assert response.json()["detail"] == "file_empty"


def test_file_over_five_megabytes_is_rejected(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    headers, _ = user(api, bearer, "big")
    too_big = PNG + b"\x00" * (5 * 1024 * 1024)

    response = upload(api, headers, data=too_big)

    assert response.status_code == 413
    assert response.json()["detail"] == "file_too_large"
    assert list(media_root.iterdir()) == []


def test_control_characters_in_the_filename_are_removed(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    headers, _ = user(api, bearer, "nul")

    response = upload(api, headers, data=JPEG, name="a\0b\x1f.jpg")

    assert response.status_code == 201, response.text
    row = db_row(MediaAsset, uuid.UUID(response.json()["id"]))
    # PostgreSQL rejects NUL, so the name must reach the database without one.
    assert "\0" not in (row.original_name or "")


def test_private_file_is_hidden_from_other_people(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    owner, _ = user(api, bearer, "owner")
    other, _ = user(api, bearer, "other")
    body = uploaded(api, owner)

    assert api.client.get(body["url"], headers=other).status_code == 404
    assert api.client.get(body["url"]).status_code == 404
    assert api.client.get(body["url"], headers=owner).status_code == 200


def test_someone_elses_upload_cannot_be_attached(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    owner, _ = user(api, bearer, "victim")
    attacker, _ = user(api, bearer, "attacker")
    body = uploaded(api, owner)

    response = set_avatar(api, attacker, body["id"])

    assert response.status_code == 404
    assert response.json()["detail"] == "media_not_found"
    assert db_row(MediaAsset, uuid.UUID(body["id"])).visibility == "private"
    assert api.client.get(body["url"]).status_code == 404


def test_outsider_cannot_set_org_logo(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    owner, _ = user(api, bearer, "org")
    outsider, _ = user(api, bearer, "outsider")
    slug = make_org(api, owner)
    logo = uploaded(api, outsider)

    response = api.client.put(
        f"/organizations/{slug}/logo", headers=outsider, json={"asset_id": logo["id"]}
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "organization_forbidden"
    assert db_row(Organization, org_id_for(slug)).logo_media_id is None


def test_identical_file_from_another_person_is_not_shared(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    first, _ = user(api, bearer, "first")
    second, _ = user(api, bearer, "second")
    original = uploaded(api, first)

    copy = uploaded(api, second)

    assert copy["id"] != original["id"]
    assert copy["visibility"] == "private"
    assert api.client.get(copy["url"], headers=second).status_code == 200
    assert api.client.get(original["url"], headers=second).status_code == 404
    assert db_row(MediaAsset, uuid.UUID(copy["id"])).file_hash is None


def test_attaching_and_uploading_need_a_login(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    headers, _ = user(api, bearer, "anon")
    body = uploaded(api, headers)

    assert (
        api.client.put("/account/me/avatar", json={"asset_id": body["id"]}).status_code
        == 401
    )
    assert (
        api.client.post(
            "/media", files={"file": ("a.png", PNG, "image/png")}
        ).status_code
        == 401
    )


def test_attach_body_rejects_unknown_fields(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    headers, _ = user(api, bearer, "extra")
    body = uploaded(api, headers)

    response = api.client.put(
        "/account/me/avatar",
        headers=headers,
        json={"asset_id": body["id"], "owner_id": str(uuid.uuid4())},
    )

    assert response.status_code == 422


def test_file_path_must_be_a_uuid7(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    headers, _ = user(api, bearer, "path")

    response = api.client.get(f"/media/{uuid.uuid4()}/file", headers=headers)

    assert response.status_code == 422
