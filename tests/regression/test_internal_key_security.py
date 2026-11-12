"""Lock in what the internal key must keep doing."""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.app import app
from src.internal_key import HEADER, INVALID_CODE
from tests.conftest import ApiContext


@pytest.fixture
def outsider() -> TestClient:
    return TestClient(app)


def test_validation_errors_are_hidden_without_the_key(outsider: TestClient) -> None:
    """A bad body gets 401, never 422, so outsiders cannot map the request fields."""
    response = outsider.post("/auth/register", json={"unknown": "\x00", "email": 5})
    assert response.status_code == 401
    assert response.json() == {"detail": INVALID_CODE}
    assert "loc" not in response.text


def test_validation_still_runs_with_the_key(api: ApiContext) -> None:
    """The key check sits in front of validation; it does not replace it."""
    response = api.client.post("/auth/register", json={"unknown": "x"})
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


def test_a_valid_token_without_the_key_is_refused(
    api: ApiContext, outsider: TestClient
) -> None:
    """A stolen access token alone is not enough to call the API."""
    token = api.register("holder")["tokens"]["access_token"]
    response = outsider.get(
        "/organizations/mine", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401
    assert response.json() == {"detail": INVALID_CODE}


def test_key_with_different_case_header_name_works(api: ApiContext) -> None:
    """HTTP header names are case-insensitive."""
    key = api.client.headers[HEADER]
    response = api.client.get("/organizations", headers={"X-Internal-Key": key})
    assert response.status_code == 200


def test_chat_socket_does_not_need_the_key(outsider: TestClient) -> None:
    """The browser opens the socket itself, so only the ticket guards it.

    The 4401 close comes from the ticket check, which proves the key check let
    the socket through instead of answering with an HTTP 401.
    """
    with (
        outsider,
        pytest.raises(WebSocketDisconnect) as refused,
        outsider.websocket_connect("/ws/chat?ticket=forged-ticket"),
    ):
        pass
    assert refused.value.code == 4401
