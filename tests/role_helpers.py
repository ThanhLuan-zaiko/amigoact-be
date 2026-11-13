"""Shared setup for the role tests: people, an open organization, and roles."""

from collections.abc import Callable
from typing import Any

from tests.conftest import ORG_FIELDS, ApiContext

Headers = dict[str, str]
Bearer = Callable[[str], Headers]


def person(api: ApiContext, bearer: Bearer, name: str) -> tuple[Headers, str]:
    body = api.register(name)
    return bearer(body["tokens"]["access_token"]), body["user"]["id"]


def open_org(api: ApiContext, owner: Headers) -> str:
    response = api.client.post(
        "/organizations",
        headers=owner,
        json={**ORG_FIELDS, "name": f"Roles {api.tag}", "join_policy": "open"},
    )
    assert response.status_code == 201, response.text
    slug: str = response.json()["slug"]
    return slug


def join(api: ApiContext, slug: str, headers: Headers) -> None:
    response = api.client.post(f"/organizations/{slug}/join", headers=headers, json={})
    assert response.status_code == 200, response.text


def new_role(
    api: ApiContext,
    slug: str,
    headers: Headers,
    name: str,
    *permissions: str,
    **extra: Any,
) -> dict[str, Any]:
    response = api.client.post(
        f"/organizations/{slug}/roles",
        headers=headers,
        json={"name": name, "permissions": list(permissions), **extra},
    )
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def give(
    api: ApiContext, slug: str, headers: Headers, user_id: str, *role_ids: str
) -> Any:
    return api.client.put(
        f"/organizations/{slug}/members/{user_id}/roles",
        headers=headers,
        json={"role_ids": list(role_ids)},
    )


def team(api: ApiContext, bearer: Bearer) -> tuple[str, Headers, Headers, str]:
    """An open organization with its owner and one joined member."""
    owner, _ = person(api, bearer, "owner")
    member, member_id = person(api, bearer, "member")
    slug = open_org(api, owner)
    join(api, slug, member)
    return slug, owner, member, member_id
