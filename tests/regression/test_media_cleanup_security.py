import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from src.app import app
from src.media.cleanup import apply_plan, run
from src.models.media import MediaAsset
from tests.activity_helpers import user
from tests.conftest import ORG_FIELDS, ApiContext
from tests.media_helpers import (
    GRACE_DAYS,
    age,
    clean,
    db_row,
    set_avatar,
    stored,
    unique_picture,
    uploaded,
)

Bearer = Callable[[str], dict[str, str]]


def test_upload_attached_after_the_plan_was_made_is_kept(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    # Regression guard: a plan is made before the lock, so apply must check again.
    headers, user_id = user(api, bearer, "owner")
    old = uploaded(api, headers, unique_picture())
    age(old["id"], 60)
    with Session(app.state.engine) as db:
        plan = run(
            db,
            media_root,
            now=datetime.now(UTC),
            min_age_days=GRACE_DAYS,
            uploader_id=uuid.UUID(user_id),
        )
    assert uuid.UUID(old["id"]) in plan.assets
    body: dict[str, Any] = {
        **ORG_FIELDS,
        "name": f"CLB {api.tag}",
        "logo_asset_id": old["id"],
    }
    attached = api.client.post("/organizations", headers=headers, json=body)
    assert attached.status_code == 201, attached.text

    with Session(app.state.engine) as db:
        apply_plan(db, plan, datetime.now(UTC))

    assert db_row(MediaAsset, uuid.UUID(old["id"])).upload_status == "active"
    assert len(stored(media_root, old["id"])) == 1


def test_a_removed_upload_can_be_uploaded_again(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    # Regression guard: the dedup by hash must not hand back a removed file.
    headers, user_id = user(api, bearer, "owner")
    data = unique_picture()
    old = uploaded(api, headers, data)
    age(old["id"], 60)
    clean(media_root, user_id, apply=True)

    again = uploaded(api, headers, data)

    assert again["id"] != old["id"]
    shown = api.client.get(f"/media/{again['id']}/file", headers=headers)
    assert shown.status_code == 200


def test_a_removed_upload_cannot_be_attached(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    headers, user_id = user(api, bearer, "owner")
    old = uploaded(api, headers, unique_picture())
    age(old["id"], 60)
    clean(media_root, user_id, apply=True)

    response = set_avatar(api, headers, old["id"])

    assert response.status_code == 404
    assert response.json()["detail"] == "media_not_found"


def test_cleanup_for_one_user_never_touches_another_users_files(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    owner_headers, _ = user(api, bearer, "owner")
    _, other_id = user(api, bearer, "other")
    theirs = uploaded(api, owner_headers, unique_picture())
    age(theirs["id"], 60)

    clean(media_root, other_id, apply=True)

    row = db_row(MediaAsset, uuid.UUID(theirs["id"]))
    assert row.upload_status == "active"
