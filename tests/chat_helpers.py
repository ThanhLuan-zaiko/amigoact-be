"""Shared steps for the chat tests."""

from typing import Any

from tests.activity_helpers import Headers
from tests.conftest import ApiContext


def send(
    api: ApiContext, headers: Headers, room_id: str, body: str, **extra: Any
) -> Any:
    return api.client.post(
        f"/rooms/{room_id}/messages", headers=headers, json={"body": body, **extra}
    )


def sent(
    api: ApiContext, headers: Headers, room_id: str, body: str, **extra: Any
) -> dict[str, Any]:
    response = send(api, headers, room_id, body, **extra)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def messages(
    api: ApiContext, headers: Headers, room_id: str, query: str = ""
) -> list[dict[str, Any]]:
    response = api.client.get(f"/rooms/{room_id}/messages{query}", headers=headers)
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return items


def channel(
    api: ApiContext, headers: Headers, slug: str, name: str, **body: Any
) -> dict[str, Any]:
    response = api.client.post(
        f"/organizations/{slug}/chat/channels",
        headers=headers,
        json={"name": name, **body},
    )
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def ticket(api: ApiContext, headers: Headers) -> str:
    response = api.client.post("/chat/tickets", headers=headers)
    assert response.status_code == 201, response.text
    value: str = response.json()["ticket"]
    return value
