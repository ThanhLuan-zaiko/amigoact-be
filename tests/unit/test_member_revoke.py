"""Unit tests: roster exits revoke the target's org channel subscriptions."""

from __future__ import annotations

import asyncio

import pytest

from core.realtime import ConnectionManager
from orgs.member_events import REVOKING_ACTIONS, WsMemberEvents, revoke_channels
from tests.unit.realtime_fakes import FakeSocket, uid, ws


def _subscribed(manager: ConnectionManager, user_id, org) -> FakeSocket:  # noqa: ANN001
    sock = FakeSocket()
    manager.register(ws(sock), user_id)
    for channel in (
        f"notifications:{user_id}",
        f"members:{org}",
        f"activities:{org}",
    ):
        manager.subscribe(ws(sock), channel)
    return sock


async def _drain() -> None:
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    await asyncio.gather(*pending)


async def test_revoke_drops_channels_on_every_socket_and_tells_client() -> None:
    manager = ConnectionManager()
    org, user_id = uid(), uid()
    tabs = [_subscribed(manager, user_id, org) for _ in range(2)]

    dropped = await revoke_channels(
        manager, user_id, (f"members:{org}", f"activities:{org}")
    )
    assert dropped == 4
    for sock in tabs:
        state = manager.state_of(ws(sock))
        assert state is not None
        assert state.channels == {f"notifications:{user_id}"}
        assert [frame["data"] for frame in sock.sent] == [
            {"channel": f"members:{org}", "reason": "ACCESS_REVOKED"},
            {"channel": f"activities:{org}", "reason": "ACCESS_REVOKED"},
        ]
        assert {frame["type"] for frame in sock.sent} == {"unsubscribed.v1"}
    # Already revoked: nothing left to drop, no duplicate frames.
    assert await revoke_channels(manager, user_id, (f"members:{org}",)) == 0


@pytest.mark.parametrize("action", sorted(REVOKING_ACTIONS))
async def test_exit_actions_publish_then_revoke(action: str) -> None:
    manager = ConnectionManager()
    org, target, actor = uid(), uid(), uid()
    sock = _subscribed(manager, target, org)

    WsMemberEvents(manager).member_changed(org, action, target, actor)
    await _drain()

    # The roster event explaining the exit still reaches the target (the
    # publish captured its socket list first), plus both revocations.
    events = [f for f in sock.sent if f["type"] == "event.v1"]
    assert [f["data"]["payload"]["action"] for f in events] == [action]
    revoked = [f for f in sock.sent if f["type"] == "unsubscribed.v1"]
    assert len(revoked) == 2


@pytest.mark.parametrize("action", ["reactivated", "accepted", "promoted"])
async def test_non_exit_actions_keep_subscriptions(action: str) -> None:
    manager = ConnectionManager()
    org, target = uid(), uid()
    sock = _subscribed(manager, target, org)

    WsMemberEvents(manager).member_changed(org, action, target, uid())
    await _drain()

    assert [frame["type"] for frame in sock.sent] == ["event.v1"]
    state = manager.state_of(ws(sock))
    assert state is not None and f"members:{org}" in state.channels
