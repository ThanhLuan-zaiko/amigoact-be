"""Integration tests: WS tickets + socket handshake (amigoact_test)."""

from __future__ import annotations

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

PASSWORD = "Aa1!secure"


def _access(client: TestClient, email: str, phone: str) -> str:
    response = client.post(
        "/auth/register",
        json={
            "email": email,
            "phone": phone,
            "password": PASSWORD,
            "full_name": "Ws User",
        },
    )
    assert response.status_code == 201, response.text
    logged = client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert logged.status_code == 200, logged.text
    return logged.json()["access_token"]


def test_tickets_require_auth(app_client) -> None:  # noqa: ANN001
    client = TestClient(app_client)
    response = client.post("/ws/tickets")
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"


def test_full_handshake_channels_and_single_use(app_client) -> None:  # noqa: ANN001
    client = TestClient(app_client)
    access = _access(client, "ws@example.com", "0912345600")
    headers = {"Authorization": f"Bearer {access}"}
    me = client.get("/auth/me", headers=headers).json()

    created = client.post(
        "/orgs",
        json={
            "name": "Ws Club",
            "slug": "ws-club",
            "description": "",
            "kind": "club",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    org_id = created.json()["id"]

    issued = client.post("/ws/tickets", headers=headers)
    assert issued.status_code == 201, issued.text
    body = issued.json()
    assert body["expires_in"] == 60

    with client.websocket_connect(f"/ws?ticket={body['ticket']}") as ws:
        ready = ws.receive_json()
        assert ready["type"] == "ready.v1"
        assert ready["data"]["user_id"] == me["id"]
        assert ready["data"]["channels"] == [f"notifications:{me['id']}"]

        ws.send_json(
            {
                "type": "subscribe.v1",
                "data": {"channel": f"activities:{org_id}"},
            }
        )
        ack = ws.receive_json()
        assert ack["type"] == "subscribed.v1"
        assert ack["data"]["channel"] == f"activities:{org_id}"

        ws.send_json(
            {
                "type": "unsubscribe.v1",
                "data": {"channel": f"activities:{org_id}"},
            }
        )
        bye = ws.receive_json()
        assert bye["type"] == "unsubscribed.v1"

        ws.send_json(
            {
                "type": "subscribe.v1",
                "data": {"channel": "notifications:not-a-uuid"},
            }
        )
        err = ws.receive_json()
        assert err["type"] == "error.v1"
        assert err["data"]["code"] == "INVALID_CHANNEL"

        ws.send_json({"type": "ping.v1", "data": {}})
        assert ws.receive_json()["type"] == "pong.v1"

    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect(f"/ws?ticket={body['ticket']}") as ws:
            ws.receive_json()
    assert closed.value.code == 4401  # ticket is single use


def test_subscribe_forbidden_closes_4403(app_client) -> None:  # noqa: ANN001
    client = TestClient(app_client)
    owner = _access(client, "wsowner@example.com", "0912345601")
    stranger = _access(client, "wsstranger@example.com", "0912345602")
    created = client.post(
        "/orgs",
        json={
            "name": "Private Club",
            "slug": "private-club",
            "description": "",
            "kind": "group",
        },
        headers={"Authorization": f"Bearer {owner}"},
    )
    org_id = created.json()["id"]

    headers = {"Authorization": f"Bearer {stranger}"}
    ticket = client.post("/ws/tickets", headers=headers).json()["ticket"]
    with client.websocket_connect(f"/ws?ticket={ticket}") as ws:
        ws.receive_json()  # ready.v1
        ws.send_json(
            {
                "type": "subscribe.v1",
                "data": {"channel": f"activities:{org_id}"},
            }
        )
        err = ws.receive_json()
        assert err["data"]["code"] == "FORBIDDEN"
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 4403
