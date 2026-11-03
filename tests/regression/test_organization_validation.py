import uuid
from collections.abc import Callable

import pytest
from sqlalchemy import select

from src.app import app
from src.models.organizations import Organization, Role
from src.validation import UUID_V7
from tests.conftest import ORG_FIELDS, PASSWORD, ApiContext

Bearer = Callable[[str], dict[str, str]]


def owner_headers(api: ApiContext, bearer: Bearer) -> dict[str, str]:
    return bearer(api.register("owner")["tokens"]["access_token"])


def create(api: ApiContext, headers: dict[str, str]) -> dict[str, str]:
    response = api.client.post(
        "/organizations", headers=headers, json={**ORG_FIELDS, "name": f"CLB {api.tag}"}
    )
    assert response.status_code == 201, response.text
    body: dict[str, str] = response.json()
    return body


def first_error(body: dict[str, list[dict[str, object]]]) -> tuple[object, object]:
    error = body["detail"][0]
    loc = error["loc"]
    assert isinstance(loc, list)
    return loc[-1], error["type"]


def test_new_ids_are_uuid7(api: ApiContext, bearer: Bearer) -> None:
    body = api.register("owner")
    headers = bearer(body["tokens"]["access_token"])
    org = create(api, headers)

    assert uuid.UUID(body["user"]["id"]).version == UUID_V7
    assert uuid.UUID(org["id"]).version == UUID_V7
    with app.state.engine.connect() as connection:
        role_id = connection.scalar(
            select(Role.id)
            .join(Organization, Organization.id == Role.org_id)
            .where(Organization.slug == org["slug"])
        )
    assert role_id is not None
    assert role_id.version == UUID_V7


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("PATCH", "members/{id}", {"role": "admin"}),
        ("DELETE", "members/{id}", None),
        ("POST", "applications/{id}/approve", None),
        ("POST", "applications/{id}/reject", None),
    ],
)
def test_paths_reject_ids_that_are_not_uuid7(
    api: ApiContext,
    bearer: Bearer,
    method: str,
    suffix: str,
    body: dict[str, str] | None,
) -> None:
    headers = owner_headers(api, bearer)
    slug = create(api, headers)["slug"]
    path = f"/organizations/{slug}/{suffix.format(id=uuid.uuid4())}"

    response = api.client.request(method, path, headers=headers, json=body)

    assert response.status_code == 422
    assert first_error(response.json()) == ("user_id", "uuid_invalid")


def test_paths_reject_text_that_is_not_an_id(api: ApiContext, bearer: Bearer) -> None:
    headers = owner_headers(api, bearer)
    slug = create(api, headers)["slug"]

    response = api.client.delete(
        f"/organizations/{slug}/members/not-an-id", headers=headers
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("payload", "field", "code"),
    [
        ({"name": "a"}, "name", "string_too_short"),
        ({"name": "x" * 121}, "name", "string_too_long"),
        ({"name": "!!!"}, "name", "organization_name_invalid"),
        ({"name": "CLB\x00"}, "name", "text_invalid"),
        ({"name": "CLB", "description": "a\x00b"}, "description", "text_invalid"),
        ({"name": "CLB", "description": "x" * 2001}, "description", "string_too_long"),
        ({"name": "CLB", "org_type": "school"}, "org_type", "literal_error"),
        ({"name": "CLB", "join_policy": "secret"}, "join_policy", "literal_error"),
        ({"name": "CLB", "owner_id": "x"}, "owner_id", "extra_forbidden"),
        ({"name": "CLB", "slug": "x"}, "slug", "extra_forbidden"),
    ],
)
def test_create_reports_the_exact_field_and_code(
    api: ApiContext,
    bearer: Bearer,
    payload: dict[str, str],
    field: str,
    code: str,
) -> None:
    headers = owner_headers(api, bearer)

    response = api.client.post(
        "/organizations", headers=headers, json={**ORG_FIELDS, **payload}
    )

    assert response.status_code == 422
    assert first_error(response.json()) == (field, code)


@pytest.mark.parametrize(
    ("payload", "field", "code"),
    [
        ({"name": None}, "name", "required"),
        ({"org_type": None}, "org_type", "required"),
        ({"email": "khong-phai-email"}, "email", "value_error"),
        ({"phone": "123"}, "phone", "phone_invalid"),
        ({"website": "https://user:pw@example.org"}, "website", "website_invalid"),
        ({"website": "x" * 301}, "website", "string_too_long"),
        ({"city": "Ha\nNoi"}, "city", "text_invalid"),
        ({"address": "x" * 501}, "address", "string_too_long"),
        ({"status": "suspended"}, "status", "extra_forbidden"),
    ],
)
def test_update_reports_the_exact_field_and_code(
    api: ApiContext,
    bearer: Bearer,
    payload: dict[str, str | None],
    field: str,
    code: str,
) -> None:
    headers = owner_headers(api, bearer)
    slug = create(api, headers)["slug"]

    response = api.client.patch(f"/organizations/{slug}", headers=headers, json=payload)

    assert response.status_code == 422
    assert first_error(response.json()) == (field, code)


def test_join_validates_the_message(api: ApiContext, bearer: Bearer) -> None:
    headers = owner_headers(api, bearer)
    slug = create(api, headers)["slug"]
    member = bearer(api.register("member")["tokens"]["access_token"])

    too_long = api.client.post(
        f"/organizations/{slug}/join", headers=member, json={"message": "x" * 1001}
    )
    control = api.client.post(
        f"/organizations/{slug}/join", headers=member, json={"message": "a\x00b"}
    )

    assert first_error(too_long.json()) == ("message", "string_too_long")
    assert first_error(control.json()) == ("message", "text_invalid")


def test_role_accepts_only_admin_or_member(api: ApiContext, bearer: Bearer) -> None:
    body = api.register("owner")
    headers = bearer(body["tokens"]["access_token"])
    slug = create(api, headers)["slug"]

    response = api.client.patch(
        f"/organizations/{slug}/members/{body['user']['id']}",
        headers=headers,
        json={"role": "owner"},
    )

    assert first_error(response.json()) == ("role", "literal_error")


def test_paging_rejects_out_of_range_values(api: ApiContext) -> None:
    for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
        assert api.client.get("/organizations", params=params).status_code == 422


def test_register_with_nul_in_the_name_is_rejected_not_crashed(
    api: ApiContext,
) -> None:
    # Regression guard: PostgreSQL rejects NUL, which used to surface as a server error.
    response = api.client.post(
        "/auth/register",
        json={
            "email": api.email("nul"),
            "password": PASSWORD,
            "full_name": "a\x00b",
        },
    )

    assert response.status_code == 422
    assert first_error(response.json()) == ("full_name", "text_invalid")
