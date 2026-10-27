"""chat:moderate / chat:channel / chat:view-private, plus the legacy umbrella."""

from __future__ import annotations

import pytest

from core.exceptions import ForbiddenError
from rbac.catalog import ASSIGNABLE_PERMISSIONS
from tests.unit.test_channels import _create, _member, _world


def _holder(world, code: str):  # noqa: ANN001, ANN202
    *_, members, users, access, org_id, _owner = world
    uid = _member(members, users, org_id, f"{code}@x.com")
    access.perms.setdefault((org_id, uid), set()).add(code)
    return uid


def test_split_codes_are_assignable_and_umbrella_stays() -> None:
    for code in (
        "chat:moderate",
        "chat:channel",
        "chat:view-private",
        "chat:manage",
    ):
        assert code in ASSIGNABLE_PERMISSIONS


def test_moderate_deletes_others_messages_but_cannot_run_channels() -> None:
    world = _world()
    svc, _roster, _threads, rooms, *_rest, org_id, owner = world
    snap = _create(svc, org_id, owner)
    mod = _holder(world, "chat:moderate")
    msg = rooms.send_message(snap.channel_id, owner, "x")
    rooms.delete_message(snap.channel_id, mod, msg.message_id)
    with pytest.raises(ForbiddenError):
        _create(svc, org_id, mod, name="other-room")


def test_channel_holder_runs_channels_but_cannot_moderate_or_peek() -> None:
    world = _world()
    svc, roster, _threads, rooms, *_rest, org_id, owner = world
    snap = _create(svc, org_id, owner)
    locked = _create(svc, org_id, owner, name="secret", visibility="restricted")
    organizer = _holder(world, "chat:channel")
    assert _create(svc, org_id, organizer, name="mine").name == "mine"
    roster.add_channel_member(org_id, locked.channel_id, organizer, organizer)
    msg = rooms.send_message(snap.channel_id, owner, "x")
    with pytest.raises(ForbiddenError):
        rooms.delete_message(snap.channel_id, organizer, msg.message_id)
    names = {c.name for c in svc.list_channels(org_id, _holder(world, "chat:channel"))}
    assert "secret" not in names


def test_view_private_reads_restricted_without_a_seat() -> None:
    world = _world()
    svc, _roster, _threads, rooms, *_rest, org_id, owner = world
    locked = _create(svc, org_id, owner, name="secret", visibility="restricted")
    viewer = _holder(world, "chat:view-private")
    assert rooms.list_messages(locked.channel_id, viewer).items == []
    assert "secret" in {c.name for c in svc.list_channels(org_id, viewer)}
    with pytest.raises(ForbiddenError):
        _create(svc, org_id, viewer, name="nope")


def test_legacy_chat_manage_still_does_everything() -> None:
    world = _world()
    svc, _roster, _threads, rooms, *_rest, org_id, owner = world
    snap = _create(svc, org_id, owner, visibility="restricted")
    legacy = _holder(world, "chat:manage")
    assert rooms.list_messages(snap.channel_id, legacy).items == []
    msg = rooms.send_message(snap.channel_id, owner, "x")
    rooms.delete_message(snap.channel_id, legacy, msg.message_id)
    assert _create(svc, org_id, legacy, name="legacy-room").name == "legacy-room"
