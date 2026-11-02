"""Shared steps for the organization feed tests."""

import uuid
from typing import Any

from tests.activity_helpers import Headers
from tests.conftest import ApiContext


def open_org(api: ApiContext, headers: Headers) -> str:
    """An organization anyone can join at once."""
    response = api.client.post(
        "/organizations",
        headers=headers,
        json={"name": f"CLB {uuid.uuid4().hex[:6]}", "join_policy": "open"},
    )
    assert response.status_code == 201, response.text
    slug: str = response.json()["slug"]
    return slug


def join(api: ApiContext, slug: str, headers: Headers) -> None:
    response = api.client.post(f"/organizations/{slug}/join", headers=headers, json={})
    assert response.status_code == 200, response.text


def post(api: ApiContext, headers: Headers, slug: str, **body: Any) -> Any:
    """Post a discussion unless the caller says otherwise."""
    payload = {"kind": "discussion", "title": "Hello", "body": "First text", **body}
    return api.client.post(
        f"/organizations/{slug}/posts", headers=headers, json=payload
    )


def created(
    api: ApiContext, headers: Headers, slug: str, **body: Any
) -> dict[str, Any]:
    response = post(api, headers, slug, **body)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def comment(api: ApiContext, headers: Headers, post_id: str, text: str) -> Any:
    return api.client.post(
        f"/posts/{post_id}/comments", headers=headers, json={"body": text}
    )
