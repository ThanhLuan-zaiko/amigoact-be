"""Shared steps for the activity API tests."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from tests.conftest import ORG_FIELDS, ApiContext

Bearer = Callable[[str], dict[str, str]]
Headers = dict[str, str]


def at(days: float) -> str:
    """Return an ISO time that many days from now."""
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


def user(api: ApiContext, bearer: Bearer, name: str) -> tuple[Headers, str]:
    body = api.register(name)
    return bearer(body["tokens"]["access_token"]), body["user"]["id"]


def make_org(api: ApiContext, headers: Headers) -> str:
    response = api.client.post(
        "/organizations", headers=headers, json={**ORG_FIELDS, "name": f"CLB {api.tag}"}
    )
    assert response.status_code == 201, response.text
    slug: str = response.json()["slug"]
    return slug


def draft(
    api: ApiContext, headers: Headers, slug: str, **fields: Any
) -> dict[str, Any]:
    body = {
        "title": f"Hoat dong {api.tag}",
        "location": "San truong",
        "start_at": at(10),
        "end_at": at(11),
        **fields,
    }
    response = api.client.post(
        f"/organizations/{slug}/activities", headers=headers, json=body
    )
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def published(
    api: ApiContext, headers: Headers, slug: str, **fields: Any
) -> dict[str, Any]:
    activity = draft(api, headers, slug, **fields)
    response = api.client.post(f"/activities/{activity['id']}/publish", headers=headers)
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def add_shift(
    api: ApiContext,
    headers: Headers,
    activity_id: str,
    *,
    start: float = 10.1,
    end: float = 10.2,
    capacity: int = 5,
    title: str = "Ca sang",
) -> dict[str, Any]:
    response = api.client.post(
        f"/activities/{activity_id}/shifts",
        headers=headers,
        json={
            "title": title,
            "start_at": at(start),
            "end_at": at(end),
            "capacity": capacity,
        },
    )
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def sign_up(
    api: ApiContext, headers: Headers, activity_id: str, **body: Any
) -> dict[str, Any]:
    response = api.client.post(
        f"/activities/{activity_id}/registrations", headers=headers, json=body
    )
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def first_error(body: dict[str, Any]) -> tuple[Any, Any]:
    error = body["detail"][0]
    return error["loc"][-1], error["type"]
