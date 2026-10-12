"""Regression tests: frozen presence and revocation wire contract."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.ws_helpers import next_frame, pinned_loop

PASSWORD = "Aa1!secure"


def _login(client: TestClient, email: str, phone: str) -> dict:
    client.post(
        "/auth/register",
        json={
            "email": email,
            "phone": phone,
            "password": PASSWORD,
            "full_name": "Presence Lock",
        },
    )
    logged = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    return {"Authorization": f"Bearer {logged.json()['access_token']}"}


def _org(client: TestClient, headers: dict, slug: str) -> str:
    created = client.post(
        "/orgs",
        json={"name": slug.title(), "slug": slug, "description": "", "kind": "club"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _socket(client: TestClient, headers: dict):  # noqa: ANN202
    ticket = client.post("/ws/tickets", headers=headers).json()["ticket"]
    return client.websocket_connect(f"/ws?ticket={ticket}")


def test_presence_event_contract_locked(app_client) -> None:  # noqa: ANN001
    """Freeze the members:{org} presence frames the FE relies on.

    The snapshot is the frame right after subscribed.v1 (the joiner's own
    online transition is published before ready.v1, never in between).
    Payloads keep the "presence" key and never grow an "action" key -
    member-mutation handlers would otherwise treat socket churn as
    roster edits.
    """
    client = TestClient(app_client)
    headers = _login(client, "presence.lock@example.com", "0912345695")
    me = client.get("/auth/me", headers=headers).json()
    org_id = _org(client, headers, "presence-lock-club")

    with _socket(client, headers) as ws:
        assert ws.receive_json()["type"] == "ready.v1"
        ws.send_json(
            {"type": "subscribe.v1", "data": {"channel": f"members:{org_id}"}}
        )
        assert ws.receive_json()["type"] == "subscribed.v1"
        snap = ws.receive_json()
        assert set(snap.keys()) == {"type", "data"}
        assert snap["type"] == "event.v1"
        assert set(snap["data"].keys()) == {"channel", "payload"}
        assert snap["data"]["channel"] == f"members:{org_id}"
        assert snap["data"]["payload"] == {
            "presence": "snapshot",
            "online": [me["id"]],
        }


def test_access_revoked_unsubscribe_contract_locked(app_client) -> None:  # noqa: ANN001
    """Freeze the server-initiated unsubscribed.v1 the FE uses to stop
    re-joining a channel after a suspension or removal."""
    with pinned_loop(TestClient(app_client)) as client:
        owner = _login(client, "revoke.lock.own@example.com", "0912345696")
        member = _login(client, "revoke.lock.mem@example.com", "0912345697")
        org_id = _org(client, owner, "revoke-lock-club")
        client.post(
            f"/orgs/{org_id}/members",
            json={"email": "revoke.lock.mem@example.com", "role": "member"},
            headers=owner,
        )
        client.post(f"/orgs/{org_id}/members/me/accept", headers=member)
        member_id = client.get("/auth/me", headers=member).json()["id"]
        channel = f"members:{org_id}"

        with _socket(client, member) as ws:
            assert ws.receive_json()["type"] == "ready.v1"
            ws.send_json({"type": "subscribe.v1", "data": {"channel": channel}})
            next_frame(ws, "subscribed.v1")
            removed = client.delete(
                f"/orgs/{org_id}/members/{member_id}", headers=owner
            )
            assert removed.status_code == 204, removed.text
            frame = next_frame(ws, "unsubscribed.v1")
            assert set(frame.keys()) == {"type", "data"}
            assert frame["data"] == {
                "channel": channel,
                "reason": "ACCESS_REVOKED",
            }
