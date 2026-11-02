"""Shared steps for the attendance API tests."""

import uuid
from typing import Any

from sqlalchemy import update

from src.app import app
from src.models.activities import Activity
from tests.activity_helpers import Headers, at
from tests.conftest import ApiContext


def open_session(
    api: ApiContext, headers: Headers, activity_id: str, **body: Any
) -> dict[str, Any]:
    response = api.client.post(
        f"/activities/{activity_id}/attendance-sessions", headers=headers, json=body
    )
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def check_in(api: ApiContext, headers: Headers, **body: str) -> Any:
    return api.client.post("/attendance/check-in", headers=headers, json=body)


def start_now(activity_id: str) -> None:
    """Move the start into the past. The API refuses this for a published activity."""
    with app.state.engine.begin() as connection:
        connection.execute(
            update(Activity)
            .where(Activity.id == uuid.UUID(activity_id))
            .values(start_at=at(-0.1))
        )


def complete(api: ApiContext, headers: Headers, activity_id: str) -> dict[str, Any]:
    start_now(activity_id)
    response = api.client.post(f"/activities/{activity_id}/complete", headers=headers)
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result
