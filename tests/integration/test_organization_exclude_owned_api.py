from collections.abc import Callable

from sqlalchemy import insert, select

from src.app import app
from src.models.auth import User
from src.models.organizations import Organization
from tests.conftest import ApiContext

Bearer = Callable[[str], dict[str, str]]


def seed(api: ApiContext, owner: str, label: str, count: int) -> None:
    """Insert directly, so seeding does not use up the daily rate limit."""
    with app.state.engine.begin() as connection:
        owner_id = connection.scalar(
            select(User.id).where(User.email == api.email(owner))
        )
        for index in range(count):
            connection.execute(
                insert(Organization).values(
                    name=f"{label} {api.tag} {index}",
                    slug=f"{label}-{api.tag}-{index}",
                    owner_id=owner_id,
                )
            )


def names(body: dict[str, list[dict[str, str]]]) -> list[str]:
    return [item["name"] for item in body["items"]]


def test_exclude_owned_hides_only_the_viewers_organizations(
    api: ApiContext, bearer: Bearer
) -> None:
    viewer = bearer(api.register("viewer")["tokens"]["access_token"])
    api.register("other")
    seed(api, "viewer", "mine", 1)
    seed(api, "other", "theirs", 1)

    response = api.client.get(
        "/organizations",
        headers=viewer,
        params={"q": api.tag, "exclude_owned": "true"},
    )

    assert response.status_code == 200
    assert names(response.json()) == [f"theirs {api.tag} 0"]


def test_pages_stay_full_when_the_viewer_owns_the_newest(
    api: ApiContext, bearer: Bearer
) -> None:
    viewer = bearer(api.register("viewer")["tokens"]["access_token"])
    api.register("other")
    seed(api, "other", "theirs", 3)
    seed(api, "viewer", "mine", 2)
    params: dict[str, str | int] = {
        "q": api.tag,
        "exclude_owned": "true",
        "limit": 2,
    }

    first = api.client.get("/organizations", headers=viewer, params=params).json()
    second = api.client.get(
        "/organizations",
        headers=viewer,
        params={**params, "offset": first["next_offset"]},
    ).json()

    assert len(first["items"]) == 2
    assert first["next_offset"] == 2
    assert len(second["items"]) == 1
    assert second["next_offset"] is None
    assert not [name for name in names(first) + names(second) if "mine" in name]
