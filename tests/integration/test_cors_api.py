"""CORS headers and the chat socket follow CORS_ORIGINS from .env."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.app import app
from src.chat import ws_router
from src.cors import get_cors_settings
from tests.activity_helpers import Bearer, user
from tests.chat_helpers import ticket
from tests.conftest import ApiContext

FOREIGN = "http://evil.test"


def test_foreign_origin_gets_no_cors_headers(api: ApiContext) -> None:
    response = api.client.get("/organizations", headers={"Origin": FOREIGN})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers
    refused = api.client.options(
        "/organizations",
        headers={"Origin": FOREIGN, "Access-Control-Request-Method": "GET"},
    )
    assert refused.status_code == 400
    assert "access-control-allow-origin" not in refused.headers


def test_listed_origin_gets_cors_headers(api: ApiContext) -> None:
    origins = get_cors_settings().origins
    if not origins:
        pytest.skip("CORS_ORIGINS is empty in .env")
    response = api.client.options(
        "/organizations",
        headers={"Origin": origins[0], "Access-Control-Request-Method": "GET"},
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origins[0]


@pytest.fixture
def listed(monkeypatch: pytest.MonkeyPatch) -> str:
    # Settings read only .env and ignore keyword arguments, so stand in a plain object.
    origin = "http://allowed.test"
    settings = SimpleNamespace(origins=[origin])
    monkeypatch.setattr(ws_router, "get_cors_settings", lambda: settings)
    return origin


def test_socket_accepts_a_listed_origin(
    api: ApiContext, bearer: Bearer, listed: str
) -> None:
    owner, _ = user(api, bearer, "wsok")
    with api.client.websocket_connect(
        f"/ws/chat?ticket={ticket(api, owner)}", headers={"Origin": listed}
    ) as socket:
        socket.send_json({"op": "ping"})
        assert socket.receive_json() == {"op": "pong"}


def test_socket_refuses_a_foreign_origin(
    api: ApiContext, bearer: Bearer, listed: str
) -> None:
    owner, _ = user(api, bearer, "wsbad")
    good = ticket(api, owner)
    with (
        pytest.raises(WebSocketDisconnect) as refused,
        api.client.websocket_connect(
            f"/ws/chat?ticket={good}", headers={"Origin": FOREIGN}
        ),
    ):
        pass
    assert refused.value.code == ws_router.FORBIDDEN_ORIGIN_CLOSE
    # The ticket was not spent, so the real page can still use it.
    with api.client.websocket_connect(
        f"/ws/chat?ticket={good}", headers={"Origin": listed}
    ) as socket:
        socket.send_json({"op": "ping"})
        assert socket.receive_json() == {"op": "pong"}


def test_preflight_is_answered_before_the_key_check() -> None:
    """Browsers never send the internal key, so CORS answers preflights itself."""
    response = TestClient(app).options(
        "/organizations",
        headers={"Origin": FOREIGN, "Access-Control-Request-Method": "GET"},
    )
    assert response.status_code == 400
    assert "internal_key_invalid" not in response.text
