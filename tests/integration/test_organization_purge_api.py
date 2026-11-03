import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.app import app
from src.models.activities import Activity
from src.models.attendance import VolunteerHourLedger
from src.models.organizations import Organization
from tests.activity_helpers import Bearer, draft, make_org, user
from tests.attendance_helpers import attended_activity
from tests.conftest import ApiContext

Headers = dict[str, str]


def trash(api: ApiContext, headers: Headers, slug: str) -> str:
    """Soft delete the organization and return its id from the trash."""
    response = api.client.delete(f"/organizations/{slug}", headers=headers)
    assert response.status_code == 204, response.text
    items: list[dict[str, Any]] = api.client.get(
        "/organizations/mine/deleted", headers=headers
    ).json()
    return str(items[0]["id"])


def purge(api: ApiContext, headers: Headers, org_id: str) -> Any:
    return api.client.delete(f"/organizations/mine/deleted/{org_id}", headers=headers)


def org_row_exists(org_id: str) -> bool:
    with Session(app.state.engine) as session:
        found = session.scalar(
            select(Organization.id).where(Organization.id == uuid.UUID(org_id))
        )
    return found is not None


def add_hour_entry(student_id: str, org_id: str | None, status: str) -> uuid.UUID:
    """Write a ledger row directly, because a pending entry needs a typed code to arise."""
    with Session(app.state.engine) as session:
        entry = VolunteerHourLedger(
            student_id=uuid.UUID(student_id),
            org_id=uuid.UUID(org_id) if org_id else None,
            source="manual",
            hours=Decimal("2.00"),
            status=status,
        )
        session.add(entry)
        session.commit()
        return entry.entry_id


def test_owner_purges_a_trashed_organization_and_its_activities(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    slug = make_org(api, owner)
    activity = draft(api, owner, slug)
    org_id = trash(api, owner, slug)

    response = purge(api, owner, org_id)

    assert response.status_code == 204, response.text
    assert not org_row_exists(org_id)
    assert api.client.get("/organizations/mine/deleted", headers=owner).json() == []
    with Session(app.state.engine) as session:
        activity_row = session.scalar(
            select(Activity.id).where(Activity.id == uuid.UUID(activity["id"]))
        )
    assert activity_row is None


def test_a_live_organization_cannot_be_purged(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    slug = make_org(api, owner)
    org_id = api.client.get(f"/organizations/{slug}").json()["id"]

    response = purge(api, owner, org_id)

    assert response.status_code == 404
    assert response.json()["detail"] == "organization_not_found"
    assert org_row_exists(org_id)


def test_another_user_cannot_purge_the_trash_of_an_owner(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    other, _ = user(api, bearer, "other")
    slug = make_org(api, owner)
    org_id = trash(api, owner, slug)

    response = purge(api, other, org_id)

    assert response.status_code == 404
    assert response.json()["detail"] == "organization_not_found"
    assert org_row_exists(org_id)
    assert len(api.client.get("/organizations/mine/deleted", headers=owner).json()) == 1


def test_issued_certificates_block_the_purge(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    volunteer, _ = user(api, bearer, "volunteer")
    slug = make_org(api, owner)
    activity = attended_activity(api, owner, volunteer, slug=slug)
    issued = api.client.post(
        f"/activities/{activity['id']}/certificates", headers=owner
    )
    assert issued.json() == {"issued": 1}
    org_id = trash(api, owner, slug)

    response = purge(api, owner, org_id)

    assert response.status_code == 409
    assert response.json()["detail"] == "organization_has_certificates"
    assert org_row_exists(org_id)
    certificates = api.client.get("/certificates/mine", headers=volunteer).json()
    assert len(certificates) == 1


def test_pending_hours_block_the_purge(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    _, student_id = user(api, bearer, "student")
    slug = make_org(api, owner)
    org_id = trash(api, owner, slug)
    add_hour_entry(student_id, org_id, status="pending")

    response = purge(api, owner, org_id)

    assert response.status_code == 409
    assert response.json()["detail"] == "organization_has_pending_hours"
    assert org_row_exists(org_id)
