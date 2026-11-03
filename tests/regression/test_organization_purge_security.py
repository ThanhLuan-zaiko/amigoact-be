import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.app import app
from src.models.attendance import VolunteerHourLedger
from src.models.organizations import Organization
from tests.activity_helpers import Bearer, make_org, user
from tests.conftest import ApiContext
from tests.integration.test_organization_purge_api import (
    add_hour_entry,
    purge,
    trash,
)


def test_approved_hours_survive_the_purge_without_their_organization(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    _, student_id = user(api, bearer, "student")
    slug = make_org(api, owner)
    org_id = trash(api, owner, slug)
    entry_id = add_hour_entry(student_id, org_id, status="approved")

    response = purge(api, owner, org_id)

    assert response.status_code == 204, response.text
    with Session(app.state.engine) as session:
        entry = session.scalar(
            select(VolunteerHourLedger).where(VolunteerHourLedger.entry_id == entry_id)
        )
    assert entry is not None
    assert entry.status == "approved"
    assert entry.hours == 2
    assert entry.org_id is None


def test_purging_one_trashed_organization_leaves_the_others_alone(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    kept_slug = make_org(api, owner)
    kept_id = api.client.get(f"/organizations/{kept_slug}").json()["id"]
    purged_slug = make_org(api, owner)
    purged_id = trash(api, owner, purged_slug)

    response = purge(api, owner, purged_id)

    assert response.status_code == 204, response.text
    assert api.client.get(f"/organizations/{kept_slug}").status_code == 200
    with Session(app.state.engine) as session:
        kept = session.scalar(
            select(Organization.id).where(Organization.id == uuid.UUID(kept_id))
        )
    assert kept is not None
