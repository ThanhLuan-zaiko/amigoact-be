"""Integration tests: org member presence over the live socket (DB)."""

from __future__ import annotations

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from tests.ws_helpers import next_frame, next_presence, pinned_loop

PASSWORD = "Aa1!secure"


def _access(client: TestClient, email: str, phone: str) -> str:
    response = client.post(
        "/auth/register",
        json={
            "email": email,
            "phone": phone,
            "password": PASSWORD,
            "full_name": "Presence User",
        },
    )
    assert response.status_code == 201, response.text
    logged = client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert logged.status_code == 200, logged.text
    return logged.json()["access_token"]


def _ticket(client: TestClient, headers: dict) -> str:
    issued = client.post("/ws/tickets", headers=headers)
    assert issued.status_code == 201, issued.text
    return issued.json()["ticket"]


def _club_with_member(client: TestClient, tag: str, phones: tuple[str, str]):  # noqa: ANN202
    """Owner org plus one accepted member; returns ids and auth headers."""
    owner = _access(client, f"{tag}.own@example.com", phones[0])
    member = _access(client, f"{tag}.mem@example.com", phones[1])
    oh = {"Authorization": f"Bearer {owner}"}
    mh = {"Authorization": f"Bearer {member}"}
    created = client.post(
        "/orgs",
        json={
            "name": f"{tag.title()} Club",
            "slug": f"{tag}-club",
            "description": "",
            "kind": "club",
        },
        headers=oh,
    )
    assert created.status_code == 201, created.text
    org_id = created.json()["id"]
    invited = client.post(
        f"/orgs/{org_id}/members",
        json={"email": f"{tag}.mem@example.com", "role": "member"},
        headers=oh,
    )
    assert invited.status_code == 201, invited.text
    accepted = client.post(f"/orgs/{org_id}/members/me/accept", headers=mh)
    assert accepted.status_code == 200, accepted.text
    owner_id = client.get("/auth/me", headers=oh).json()["id"]
    member_id = client.get("/auth/me", headers=mh).json()["id"]
    return org_id, owner_id, member_id, oh, mh


def _join(sock, channel: str) -> None:  # noqa: ANN001
    sock.send_json({"type": "subscribe.v1", "data": {"channel": channel}})
    assert next_frame(sock, "subscribed.v1")["data"]["channel"] == channel


def test_member_presence_snapshot_and_transitions(app_client) -> None:  # noqa: ANN001
    """Org roster channel carries the online roster in real time."""
    with pinned_loop(TestClient(app_client)) as client:
        org_id, owner_id, member_id, oh, mh = _club_with_member(
            client, "presence", ("0912345700", "0912345701")
        )
        channel = f"members:{org_id}"
        with client.websocket_connect(f"/ws?ticket={_ticket(client, oh)}") as ws:
            assert ws.receive_json()["type"] == "ready.v1"
            _join(ws, channel)
            # Deterministic order: the snapshot directly follows the ack.
            snap = ws.receive_json()["data"]["payload"]
            assert snap == {"presence": "snapshot", "online": [owner_id]}

            # Member's first socket -> owner sees them come online live.
            with client.websocket_connect(
                f"/ws?ticket={_ticket(client, mh)}"
            ) as msock:
                assert msock.receive_json()["type"] == "ready.v1"
                event = next_presence(ws, channel)
                assert event == {"presence": "online", "user_id": member_id}
            # Member's last socket closed -> owner sees them drop offline.
            event = next_presence(ws, channel)
            assert event == {"presence": "offline", "user_id": member_id}


def test_suspension_revokes_roster_feed_and_hides_presence(app_client) -> None:  # noqa: ANN001
    """A suspended member loses members:{org} on the open socket and no
    longer appears in snapshots."""
    with pinned_loop(TestClient(app_client)) as client:
        org_id, owner_id, member_id, oh, mh = _club_with_member(
            client, "revoke", ("0912345720", "0912345721")
        )
        channel = f"members:{org_id}"
        with client.websocket_connect(f"/ws?ticket={_ticket(client, mh)}") as msock:
            assert msock.receive_json()["type"] == "ready.v1"
            _join(msock, channel)
            assert next_presence(msock, channel)["presence"] == "snapshot"

            suspended = client.patch(
                f"/orgs/{org_id}/members/{member_id}",
                json={"status": "suspended"},
                headers=oh,
            )
            assert suspended.status_code == 200, suspended.text
            revoked = next_frame(msock, "unsubscribed.v1")
            assert revoked["data"] == {
                "channel": channel,
                "reason": "ACCESS_REVOKED",
            }

            # Owner joining now sees only themselves: the suspended
            # member's live socket is hidden from the snapshot.
            with client.websocket_connect(
                f"/ws?ticket={_ticket(client, oh)}"
            ) as ws:
                assert ws.receive_json()["type"] == "ready.v1"
                _join(ws, channel)
                snap = next_presence(ws, channel)
                assert snap == {"presence": "snapshot", "online": [owner_id]}


def test_presence_never_leaks_outside_the_org(app_client) -> None:  # noqa: ANN001
    """A non-member socket gets no snapshot and is closed with 4403."""
    client = TestClient(app_client)
    owner = _access(client, "presence2.own@example.com", "0912345710")
    stranger = _access(client, "presence2.out@example.com", "0912345711")
    oh = {"Authorization": f"Bearer {owner}"}
    sh = {"Authorization": f"Bearer {stranger}"}

    created = client.post(
        "/orgs",
        json={
            "name": "Sealed Club",
            "slug": "sealed-club",
            "description": "",
            "kind": "club",
        },
        headers=oh,
    )
    assert created.status_code == 201, created.text
    org_id = created.json()["id"]

    with client.websocket_connect(f"/ws?ticket={_ticket(client, sh)}") as ws:
        ws.receive_json()  # ready.v1
        ws.send_json(
            {
                "type": "subscribe.v1",
                "data": {"channel": f"members:{org_id}"},
            }
        )
        err = ws.receive_json()
        assert err["data"]["code"] == "FORBIDDEN"
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 4403
