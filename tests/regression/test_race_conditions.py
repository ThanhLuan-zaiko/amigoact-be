"""Race guards: two operations on the same row must wait for each other.

Each test holds a lock in one session and makes the real change there, without committing.
The second operation runs in a background thread and must wait. After the holder commits,
the second one must see the committed change and act on it. Without the lock, the second
operation would finish first, and the test would fail.
"""

import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.orm import Session

from src.activities.rules import PUBLISHED
from src.activities.service import publish_activity
from src.app import app
from src.media.cleanup import apply_plan, run, still_unused
from src.media.service import PUBLIC, check_attachable
from src.models.activities import Activity
from src.models.auth import User
from src.models.media import MediaAsset
from src.models.organizations import Organization
from src.organizations.deletion import (
    lock_live_organization,
    mark_deleted,
    soft_delete_organization,
)
from tests.activity_helpers import draft, make_org
from tests.activity_helpers import user as activity_user
from tests.conftest import ORG_FIELDS, ApiContext
from tests.media_helpers import (
    GRACE_DAYS,
    age,
    db_row,
    org_id_for,
    stored,
    unique_picture,
    uploaded,
)

Bearer = Callable[[str], dict[str, str]]


class Background:
    """Runs one operation in its own thread and session, and keeps its result or error."""

    def __init__(self, work: Callable[[Session], Any]) -> None:
        self.error: BaseException | None = None
        self._thread = threading.Thread(target=self._run, args=(work,), daemon=True)
        self._thread.start()

    def _run(self, work: Callable[[Session], Any]) -> None:
        try:
            with Session(app.state.engine) as db:
                work(db)
        except Exception as exc:  # noqa: BLE001 - kept here, the test asserts on it
            self.error = exc

    def still_waiting(self, seconds: float = 1.0) -> bool:
        """True if the operation is still running after a short pause, so it is blocked."""
        time.sleep(seconds)
        return self._thread.is_alive()

    def finish(self) -> None:
        self._thread.join(timeout=20)
        assert not self._thread.is_alive(), "the waiting operation never finished"


def soft_delete_work(org_id: uuid.UUID) -> Callable[[Session], None]:
    def work(db: Session) -> None:
        org = db.get(Organization, org_id)
        assert org is not None
        soft_delete_organization(db, org)

    return work


def publish_work(activity_id: uuid.UUID) -> Callable[[Session], None]:
    def work(db: Session) -> None:
        activity = db.get(Activity, activity_id)
        assert activity is not None
        publish_activity(db, activity)

    return work


def test_cleanup_waits_for_an_attach_and_keeps_the_file(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    # Regression guard: the cleanup must re-check references after it gets the lock.
    headers, user_id = activity_user(api, bearer, "owner")
    old = uploaded(api, headers, unique_picture())
    age(old["id"], 60)
    asset_id, owner = uuid.UUID(old["id"]), uuid.UUID(user_id)
    with Session(app.state.engine) as db:
        plan = run(
            db,
            media_root,
            now=datetime.now(UTC),
            min_age_days=GRACE_DAYS,
            uploader_id=owner,
        )
    assert asset_id in plan.assets

    with Session(app.state.engine) as holder:
        # An attach in progress: it has locked the upload and set the reference.
        check_attachable(holder, asset_id, owner)
        holder.execute(
            update(User).where(User.id == owner).values(avatar_media_id=asset_id)
        )
        cleanup = Background(lambda db: apply_plan(db, plan, datetime.now(UTC)))
        assert cleanup.still_waiting()
        holder.commit()
    cleanup.finish()

    assert cleanup.error is None
    assert db_row(MediaAsset, asset_id).upload_status == "active"
    assert len(stored(media_root, old["id"])) == 1


def test_attach_waits_for_a_cleanup_and_is_refused_once_it_commits(
    api: ApiContext, bearer: Bearer
) -> None:
    # Regression guard: an attach must not link a file that the cleanup has just removed.
    headers, user_id = activity_user(api, bearer, "owner")
    old = uploaded(api, headers, unique_picture())
    age(old["id"], 60)
    asset_id, owner = uuid.UUID(old["id"]), uuid.UUID(user_id)

    with Session(app.state.engine) as holder:
        # A cleanup in progress: it has locked the expired upload and found it unused.
        assert still_unused(holder, [asset_id]) == [asset_id]
        holder.execute(
            update(MediaAsset)
            .where(MediaAsset.asset_id == asset_id)
            .values(upload_status="deleted", deleted_at=datetime.now(UTC))
        )
        attach = Background(lambda db: check_attachable(db, asset_id, owner))
        assert attach.still_waiting()
        holder.commit()
    attach.finish()

    assert isinstance(attach.error, HTTPException)
    assert attach.error.detail == "media_not_found"


def test_publish_waits_for_a_delete_and_is_refused_once_it_commits(
    api: ApiContext, bearer: Bearer
) -> None:
    # Regression guard: an activity must not open in an organization that was deleted.
    owner, _ = activity_user(api, bearer, "owner")
    slug = make_org(api, owner)
    activity_id = uuid.UUID(draft(api, owner, slug)["id"])
    org_id = org_id_for(slug)

    with Session(app.state.engine) as holder:
        # A soft delete in progress: it has locked the organization and hidden it.
        org = holder.get(Organization, org_id, with_for_update=True)
        assert org is not None
        mark_deleted(org, datetime.now(UTC))
        publish = Background(publish_work(activity_id))
        assert publish.still_waiting()
        holder.commit()
    publish.finish()

    assert isinstance(publish.error, HTTPException)
    assert publish.error.detail == "organization_not_found"


def test_delete_waits_for_a_publish_and_is_refused_once_it_commits(
    api: ApiContext, bearer: Bearer
) -> None:
    # Regression guard: an organization with an open activity must not be deleted.
    owner, _ = activity_user(api, bearer, "owner")
    slug = make_org(api, owner)
    activity_id = uuid.UUID(draft(api, owner, slug)["id"])
    org_id = org_id_for(slug)

    with Session(app.state.engine) as holder:
        # A publish in progress: it has locked the organization and published the activity.
        assert lock_live_organization(holder, org_id)
        holder.execute(
            update(Activity).where(Activity.id == activity_id).values(status=PUBLISHED)
        )
        delete = Background(soft_delete_work(org_id))
        assert delete.still_waiting()
        holder.commit()
    delete.finish()

    assert isinstance(delete.error, HTTPException)
    assert delete.error.detail == "organization_has_open_activities"
    assert api.client.get(f"/organizations/{slug}").status_code == 200


def test_delete_waits_for_an_attach_and_keeps_a_picture_still_in_use(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    # Regression guard: a picture that gets a second use during the delete stays public.
    headers, user_id = activity_user(api, bearer, "owner")
    logo = uploaded(api, headers, unique_picture())
    body = {**ORG_FIELDS, "name": f"CLB {api.tag}", "logo_asset_id": logo["id"]}
    created = api.client.post("/organizations", headers=headers, json=body)
    assert created.status_code == 201, created.text
    org_id = uuid.UUID(created.json()["id"])
    logo_id, owner = uuid.UUID(logo["id"]), uuid.UUID(user_id)

    with Session(app.state.engine) as holder:
        # An attach in progress: the same logo is being set as the owner's avatar.
        check_attachable(holder, logo_id, owner)
        holder.execute(
            update(User).where(User.id == owner).values(avatar_media_id=logo_id)
        )
        delete = Background(soft_delete_work(org_id))
        assert delete.still_waiting()
        holder.commit()
    delete.finish()

    assert delete.error is None
    assert db_row(MediaAsset, logo_id).visibility == PUBLIC
