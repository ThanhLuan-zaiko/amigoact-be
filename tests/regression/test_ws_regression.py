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


def test_attendance_event_contract_locked(app_client) -> None:  # noqa: ANN001
    """Freeze the attendance:{id} event.v1 payload shape for the FE."""
    client = TestClient(app_client)
    owner = client.post(
        "/auth/register",
        json={
            "email": "att.own@example.com",
            "phone": "0912345697",
            "password": PASSWORD,
            "full_name": "Att Owner",
        },
    )
    assert owner.status_code == 201, owner.text
    owner = client.post(
        "/auth/login",
        json={"email": "att.own@example.com", "password": PASSWORD},
    ).json()["access_token"]
    student = client.post(
        "/auth/register",
        json={
            "email": "att.stu@example.com",
            "phone": "0912345696",
            "password": PASSWORD,
            "full_name": "Att Student",
        },
    )
    assert student.status_code == 201, student.text
    student = client.post(
        "/auth/login",
        json={"email": "att.stu@example.com", "password": PASSWORD},
    ).json()["access_token"]
    oh = {"Authorization": f"Bearer {owner}"}
    sh = {"Authorization": f"Bearer {student}"}

    org = client.post(
        "/orgs",
        json={
            "name": "Contract Club",
            "slug": "contract-club",
            "description": "",
            "kind": "club",
        },
        headers=oh,
    ).json()
    aid = client.post(
        f"/orgs/{org['id']}/activities",
        json={"title": "Run", "start_at": "2030-06-01T08:00:00Z"},
        headers=oh,
    ).json()["id"]
    client.post(
        f"/orgs/{org['id']}/activities/{aid}/status",
        json={"status": "published"},
        headers=oh,
    )
    rid = client.post(
        f"/activities/{aid}/registrations", json={}, headers=sh
    ).json()["registration_id"]
    client.post(
        f"/activities/{aid}/registrations/{rid}/review",
        json={"status": "approved"},
        headers=oh,
    )
    token = client.get(
        f"/activities/{aid}/registrations/{rid}/ticket", headers=sh
    ).json()["checkin_token"]

    ticket = client.post("/ws/tickets", headers=oh).json()["ticket"]
    with client.websocket_connect(f"/ws?ticket={ticket}") as ws:
        ws.receive_json()  # ready.v1
        ws.send_json(
            {
                "type": "subscribe.v1",
                "data": {"channel": f"attendance:{aid}"},
            }
        )
        assert ws.receive_json()["type"] == "subscribed.v1"
        client.post(
            f"/activities/{aid}/checkin",
            json={"checkin_token": token},
            headers=oh,
        )
        event = ws.receive_json()
        assert set(event.keys()) == {"type", "data"}
        assert event["type"] == "event.v1"
        assert set(event["data"].keys()) == {"channel", "payload"}
        assert event["data"]["channel"] == f"attendance:{aid}"
        assert set(event["data"]["payload"].keys()) == {
            "action",
            "record_id",
            "student_id",
            "actor_id",
        }
        assert event["data"]["payload"]["action"] in {
            "checked_in",
            "checked_out",
        }


def test_orgs_directory_event_contract_locked(app_client) -> None:  # noqa: ANN001
    """Freeze the public orgs:directory guest contract for the FE."""
    client = TestClient(app_client)
    client.post(
        "/auth/register",
        json={
            "email": "dirlock@example.com",
            "phone": "0912345697",
            "password": PASSWORD,
            "full_name": "Dir Lock",
        },
    )
    logged = client.post(
        "/auth/login",
        json={"email": "dirlock@example.com", "password": PASSWORD},
    )
    headers = {"Authorization": f"Bearer {logged.json()['access_token']}"}

    with client.websocket_connect("/ws") as ws:
        ready = ws.receive_json()
        assert set(ready.keys()) == {"type", "data"}
        assert ready["type"] == "ready.v1"
        assert set(ready["data"].keys()) == {
            "user_id",
            "channels",
            "heartbeat_seconds",
        }
        assert ready["data"]["user_id"] is None
        assert ready["data"]["channels"] == []
        ws.send_json(
            {"type": "subscribe.v1", "data": {"channel": "orgs:directory"}}
        )
        assert ws.receive_json()["type"] == "subscribed.v1"

        created = client.post(
            "/orgs",
            json={
                "name": "Lock Club",
                "slug": "lock-club",
                "description": "",
                "kind": "club",
            },
            headers=headers,
        )
        assert created.status_code == 201, created.text

        event = ws.receive_json()
        assert set(event.keys()) == {"type", "data"}
        assert event["type"] == "event.v1"
        assert set(event["data"].keys()) == {"channel", "payload"}
        assert event["data"]["channel"] == "orgs:directory"
        assert set(event["data"]["payload"].keys()) == {
            "action",
            "org_id",
            "slug",
        }
        assert event["data"]["payload"]["action"] in {
            "created",
            "updated",
            "restored",
            "removed",
        }
