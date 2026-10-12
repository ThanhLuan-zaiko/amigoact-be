"""Unit tests for realtime presence: tracking, snapshots, fan-out."""

from __future__ import annotations

import asyncio

from core.realtime import ConnectionManager
from realtime.presence import fan_presence, read_roster, send_presence_snapshot
from tests.unit.realtime_fakes import (
    FakeMembership,
    FakePresence,
    FakeSocket,
    clear_overrides,
    make_service,
    uid,
    ws,
    ws_app,
)
from tests.ws_helpers import next_presence, pinned_loop


def test_online_counting_and_offline_hook() -> None:
    """Presence is per user: the hook fires on the last socket only."""
    manager = ConnectionManager()
    user_id = uid()
    seen: list = []

    first, second = FakeSocket(), FakeSocket()
    manager.register(ws(first), user_id, on_offline=seen.append)
    assert manager.is_online(user_id)
    assert manager.online_user_ids() == {user_id}
    manager.register(ws(second), user_id, on_offline=seen.append)
    assert manager.sockets_of(user_id) == [ws(first), ws(second)]

    manager.unregister(ws(FakeSocket()))  # unknown socket: no-op
    manager.unregister(ws(second))
    assert manager.is_online(user_id)
    assert seen == []

    manager.unregister(ws(first))  # last socket drops -> offline once
    assert not manager.is_online(user_id)
    assert seen == [user_id]
    manager.unregister(ws(first))  # double unregister stays silent
    assert seen == [user_id]


def test_guest_and_hookless_sockets_never_fire() -> None:
    manager = ConnectionManager()
    guest, plain = FakeSocket(), FakeSocket()
    manager.register(ws(guest), None)
    manager.register(ws(plain), uid())
    manager.unregister(ws(guest))
    manager.unregister(ws(plain))
    assert manager.online_user_ids() == set()


async def test_dead_socket_in_publish_still_fires_offline() -> None:
    """A send failure inside publish() must not strand the online flag."""

    class DeadSocket(FakeSocket):
        async def send_text(self, text: str) -> None:
            raise RuntimeError("gone")

    manager = ConnectionManager()
    user_id = uid()
    seen: list = []
    dead = DeadSocket()
    manager.register(ws(dead), user_id, on_offline=seen.append)
    manager.subscribe(ws(dead), "members:c")

    assert await manager.publish("members:c") == 0
    assert not manager.is_online(user_id)
    assert seen == [user_id]


async def test_schedule_holds_task_until_done() -> None:
    manager = ConnectionManager()
    done = asyncio.Event()

    async def work() -> None:
        done.set()

    assert manager.schedule(work())
    assert len(manager._tasks) == 1
    await done.wait()
    await asyncio.sleep(0)
    assert manager._tasks == set()


def test_presence_reads_noop_when_unwired() -> None:
    """A service without the directory port must not break sockets."""
    service = make_service()
    assert service.presence_orgs_of(uid()) == []
    assert service.presence_member_ids(uid()) == []


async def test_snapshot_intersects_roster_with_live_online_set() -> None:
    org, member, offline_member, outsider = uid(), uid(), uid(), uid()
    service = make_service(
        presence=FakePresence({(org, member), (org, offline_member)})
    )
    manager = ConnectionManager()
    manager.register(ws(FakeSocket()), member)
    manager.register(ws(FakeSocket()), outsider)
    sock = FakeSocket()

    roster = await read_roster(service, org)
    await send_presence_snapshot(manager, ws(sock), f"members:{org}", roster)
    assert sock.sent[0]["data"]["payload"] == {
        "presence": "snapshot",
        "online": [str(member)],
    }


async def test_read_roster_swallows_lookup_failure() -> None:
    class Broken(FakePresence):
        def member_ids_of(self, org_id):  # noqa: ANN001, ANN202
            raise RuntimeError("db down")

    assert await read_roster(make_service(presence=Broken()), uid()) == []


def test_presence_payload_carries_no_action() -> None:
    """Presence frames use the "presence" key - never the "action" key
    member-mutation events rely on (wire contract)."""
    manager = ConnectionManager()
    org, user_id = uid(), uid()
    sock = FakeSocket()
    manager.register(ws(sock), uid())
    manager.register(ws(FakeSocket()), user_id)
    manager.subscribe(ws(sock), f"members:{org}")
    service = make_service(presence=FakePresence({(org, user_id)}))

    asyncio.run(fan_presence(manager, service, user_id))
    frame = sock.sent[0]
    assert frame["type"] == "event.v1"
    payload = frame["data"]["payload"]
    assert payload == {"presence": "online", "user_id": str(user_id)}
    assert "action" not in payload


async def test_fan_presence_publishes_current_state_not_trigger() -> None:
    """A late fan-out for a user who already left reports offline, so
    racing transitions converge on the registry's final state."""
    manager = ConnectionManager()
    org, user_id = uid(), uid()
    sock = FakeSocket()
    manager.register(ws(sock), uid())
    manager.subscribe(ws(sock), f"members:{org}")
    service = make_service(presence=FakePresence({(org, user_id)}))

    await fan_presence(manager, service, user_id)
    assert sock.sent[-1]["data"]["payload"]["presence"] == "offline"


async def test_fan_presence_swallows_lookup_failure() -> None:
    class Broken(FakePresence):
        def orgs_of(self, user_id):  # noqa: ANN001, ANN202
            raise RuntimeError("db down")

    manager = ConnectionManager()
    await fan_presence(manager, make_service(presence=Broken()), uid())


def test_presence_snapshot_and_transitions_over_members_channel() -> None:
    """End-to-end: snapshot on subscribe, online/offline fan-out."""
    org = uid()
    ann, bob = uid(), uid()
    client, _, service = ws_app(
        members=FakeMembership({(org, ann), (org, bob)}),
        presence=FakePresence({(org, ann), (org, bob)}),
    )
    channel = f"members:{org}"
    try:
        bob_ticket = service.issue_ticket(bob).token
        ann_ticket = service.issue_ticket(ann).token
        with (
            pinned_loop(client),
            client.websocket_connect(f"/ws?ticket={bob_ticket}") as bsock,
        ):
            bsock.receive_json()  # ready.v1 - bob online but unsubscribed
            bsock.send_json(
                {"type": "subscribe.v1", "data": {"channel": channel}}
            )
            assert bsock.receive_json()["type"] == "subscribed.v1"
            # The snapshot is the very next frame after subscribed.v1.
            snap = bsock.receive_json()
            assert snap["data"]["payload"] == {
                "presence": "snapshot",
                "online": [str(bob)],
            }

            # Ann's first socket -> bob sees her come online live.
            with client.websocket_connect(f"/ws?ticket={ann_ticket}") as asock:
                assert asock.receive_json()["type"] == "ready.v1"
                event = next_presence(bsock, channel)
                assert event == {"presence": "online", "user_id": str(ann)}
            # Ann's last socket closed -> bob sees offline.
            event = next_presence(bsock, channel)
            assert event == {"presence": "offline", "user_id": str(ann)}
    finally:
        clear_overrides()
