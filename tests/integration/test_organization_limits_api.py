from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import func, insert, select, update

from src.app import app
from src.models.auth import User
from src.models.organizations import Organization
from src.organizations.service import CREATE_LIMIT, MAX_OWNED_ORGANIZATIONS
from tests.conftest import ORG_FIELDS, ApiContext

Bearer = Callable[[str], dict[str, str]]


def seed_owned(api: ApiContext, count: int) -> None:
    """Insert directly, so seeding does not use up the daily rate limit."""
    with app.state.engine.begin() as connection:
        owner_id = connection.scalar(select(User.id).where(User.email == api.email()))
        for index in range(count):
            connection.execute(
                insert(Organization).values(
                    name=f"Seed {index}",
                    slug=f"seed-{api.tag}-{index}",
                    owner_id=owner_id,
                )
            )


def owned_count(api: ApiContext) -> int:
    with app.state.engine.connect() as connection:
        count = connection.scalar(
            select(func.count())
            .select_from(Organization)
            .join(User, User.id == Organization.owner_id)
            .where(User.email == api.email())
        )
    return count or 0


def test_owner_at_the_limit_gets_a_conflict(api: ApiContext, bearer: Bearer) -> None:
    headers = bearer(api.register()["tokens"]["access_token"])
    seed_owned(api, MAX_OWNED_ORGANIZATIONS)

    response = api.client.post(
        "/organizations", headers=headers, json={**ORG_FIELDS, "name": f"CLB {api.tag}"}
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "organization_limit_reached"
    assert owned_count(api) == MAX_OWNED_ORGANIZATIONS


def test_deleted_organization_frees_a_slot(api: ApiContext, bearer: Bearer) -> None:
    headers = bearer(api.register()["tokens"]["access_token"])
    seed_owned(api, MAX_OWNED_ORGANIZATIONS)
    with app.state.engine.begin() as connection:
        connection.execute(
            update(Organization)
            .where(Organization.slug == f"seed-{api.tag}-0")
            .values(deleted_at=datetime.now(UTC))
        )

    response = api.client.post(
        "/organizations", headers=headers, json={**ORG_FIELDS, "name": f"CLB {api.tag}"}
    )

    assert response.status_code == 201


def test_daily_attempts_are_rate_limited(api: ApiContext, bearer: Bearer) -> None:
    headers = bearer(api.register()["tokens"]["access_token"])
    for index in range(CREATE_LIMIT):
        created = api.client.post(
            "/organizations",
            headers=headers,
            json={**ORG_FIELDS, "name": f"CLB {api.tag} {index}"},
        )
        assert created.status_code == 201, created.text

    response = api.client.post(
        "/organizations",
        headers=headers,
        json={**ORG_FIELDS, "name": f"CLB {api.tag} over"},
    )

    assert response.status_code == 429
    assert response.json()["detail"] == "rate_limited"
    assert "Retry-After" in response.headers
