"""Regression tests: frozen realtime wire contract (AGENTS.md 16)."""

from __future__ import annotations

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

PASSWORD = "Aa1!secure"


def test_close_codes_locked() -> None:
    """Application close codes stay stable across releases."""
    from core.realtime import (
        CLOSE_BAD_FRAME,
        CLOSE_FORBIDDEN,
        CLOSE_PONG_TIMEOUT,
        CLOSE_UNAUTHORIZED,
    )

    assert CLOSE_BAD_FRAME == 4400
    assert CLOSE_UNAUTHORIZED == 4401
    assert CLOSE_FORBIDDEN == 4403
    assert CLOSE_PONG_TIMEOUT == 4408


def test_ticket_and_envelope_contract_locked(app_client) -> None:  # noqa: ANN001
    """Ticket response + frame shapes keep the {"type","data"} envelope."""
    client = TestClient(app_client)
    client.post(
        "/auth/register",
        json={
            "email": "locked@example.com",
            "phone": "0912345699",
            "password": PASSWORD,
            "full_name": "Locked User",
        },
    )
    logged = client.post(
        "/auth/login",
        json={"email": "locked@example.com", "password": PASSWORD},
    )
    headers = {"Authorization": f"Bearer {logged.json()['access_token']}"}
    me = client.get("/auth/me", headers=headers).json()

    issued = client.post("/ws/tickets", headers=headers)
    assert issued.status_code == 201
    body = issued.json()
    assert set(body.keys()) == {"ticket", "expires_in"}
    assert body["expires_in"] == 60

    with client.websocket_connect(f"/ws?ticket={body['ticket']}") as ws:
        ready = ws.receive_json()
        assert set(ready.keys()) == {"type", "data"}
        assert ready["type"] == "ready.v1"
        assert set(ready["data"].keys()) == {
            "user_id",
            "channels",
            "heartbeat_seconds",
        }
        assert ready["data"]["heartbeat_seconds"] == 25
        ws.send_text("}{")
        err = ws.receive_json()
        assert set(err.keys()) == {"type", "data"}
        assert err["type"] == "error.v1"
        assert err["data"]["code"] == "BAD_FRAME"
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 4400


def test_expired_ticket_closes_4401(app_client) -> None:  # noqa: ANN001
    """An expired ticket is rejected at consume time."""
    from datetime import timedelta

    from core.security import hash_token, utcnow

    client = TestClient(app_client)
    client.post(
        "/auth/register",
        json={
            "email": "expired@example.com",
            "phone": "0912345698",
            "password": PASSWORD,
            "full_name": "Expired User",
        },
    )
    logged = client.post(
        "/auth/login",
        json={"email": "expired@example.com", "password": PASSWORD},
    )
    headers = {"Authorization": f"Bearer {logged.json()['access_token']}"}
    ticket = client.post("/ws/tickets", headers=headers).json()["ticket"]
    from realtime.model import WsTicket

    WsTicket.objects(ticket_hash=hash_token(ticket)).update(
        expires_at=utcnow() - timedelta(seconds=1)
    )
    with client.websocket_connect(f"/ws?ticket={ticket}") as ws:
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 4401
