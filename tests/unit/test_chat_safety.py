"""Chat safety: @all, member timeouts and the attachment policy."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from chat.mentions import ALL_USER_ID
from chat.safety import SafetyGate
from chat.safety_interfaces import ChatSafetyStore, TimeoutRecord
from chat.safety_service import ChatSafetyService
from core.exceptions import ForbiddenError, MemberNotFoundError
from core.exceptions_chat import ChatAttachRestrictedError, ChatTimedOutError
from tests.unit.test_channels import _create, _member, _world


class FakeSafetyStore(ChatSafetyStore):
    def __init__(self) -> None:
        self.restricted: set[UUID] = set()
        self.rows: dict[tuple[UUID, UUID], TimeoutRecord] = {}

    def attach_restricted(self, org_id):  # noqa: ANN001, ANN202
        return org_id in self.restricted

    def set_attach_restricted(self, org_id, restricted):  # noqa: ANN001, ANN202
        (self.restricted.add if restricted else self.restricted.discard)(org_id)

    def get_timeout(self, org_id, user_id):  # noqa: ANN001, ANN202
        return self.rows.get((org_id, user_id))

    def put_timeout(self, org_id, record, ttl_seconds):  # noqa: ANN001, ANN202
        self.rows[(org_id, record.user_id)] = record

    def delete_timeout(self, org_id, user_id):  # noqa: ANN001, ANN202
        self.rows.pop((org_id, user_id), None)

    def list_timeouts(self, org_id):  # noqa: ANN001, ANN202
        return [r for (o, _), r in self.rows.items() if o == org_id]


class Spy:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def notify(self, user_id, kind, title, body, data):  # noqa: ANN001, ANN202
        self.calls.append((user_id, kind, title))


def _rig():  # noqa: ANN202
    world = _world()
    svc, _roster, _threads, rooms, _chat, _ch, orgs, members, users, access, org_id, owner = world
    store = FakeSafetyStore()
    rooms._composer._gate = SafetyGate(store, access)
    safety = ChatSafetyService(orgs, members, store, access, users)
    room = _create(svc, org_id, owner).channel_id
    return rooms, safety, store, members, users, access, org_id, owner, room


def _holder(members, users, access, org_id, code, email):  # noqa: ANN001, ANN202
    uid = _member(members, users, org_id, email)
    access.perms.setdefault((org_id, uid), set()).add(code)
    return uid


def test_all_mention_needs_permission_and_notifies_everyone_else() -> None:
    rooms, _s, _st, members, users, access, org_id, owner, room = _rig()
    spy = Spy()
    rooms._composer._notifications = spy
    plain = _member(members, users, org_id, "plain@x.com")
    other = _member(members, users, org_id, "other@x.com")
    allowed = _holder(members, users, access, org_id, "chat:mention-all", "a@x.com")

    quiet = rooms.send_message(room, plain, "hello @all")
    assert quiet.mentions == () and spy.calls == []

    loud = rooms.send_message(room, allowed, "ping @Everyone please")
    assert [(m.user_id, m.name) for m in loud.mentions] == [(ALL_USER_ID, "everyone")]
    notified = {call[0] for call in spy.calls}
    assert notified == {owner, plain, other}  # everyone but the sender
    assert all("c\u1ea3 nh\u00f3m" in call[2] for call in spy.calls)

    umbrella = _holder(members, users, access, org_id, "chat:manage", "m@x.com")
    assert rooms.send_message(room, umbrella, "@all").mentions[0].user_id == ALL_USER_ID


def test_timeout_blocks_send_edit_and_upload_until_lifted() -> None:
    rooms, safety, _st, members, users, access, org_id, owner, room = _rig()
    mod = _holder(members, users, access, org_id, "chat:timeout", "mod@x.com")
    target = _member(members, users, org_id, "t@x.com")
    sent = rooms.send_message(room, target, "before")

    view = safety.timeout(org_id, mod, target, 30, "spam")
    assert view.reason == "spam" and view.user_name
    with pytest.raises(ChatTimedOutError):
        rooms.send_message(room, target, "nope")
    with pytest.raises(ChatTimedOutError):
        rooms.edit_message(room, target, sent.message_id, "edited")
    with pytest.raises(ChatTimedOutError):
        rooms.create_attachment(room, target, "a.png", "image/png", b"x")
    assert safety.overview(org_id, target).my_timeout_until is not None
    assert [t.user_id for t in safety.overview(org_id, mod).timeouts] == [target]
    assert safety.overview(org_id, target).timeouts == []

    safety.lift(org_id, mod, target)
    assert rooms.send_message(room, target, "back").body == "back"


def test_expired_timeout_no_longer_blocks() -> None:
    rooms, _s, store, members, users, _a, org_id, owner, room = _rig()
    target = _member(members, users, org_id, "t@x.com")
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    store.put_timeout(org_id, TimeoutRecord(target, past, owner), 60)
    assert rooms.send_message(room, target, "ok").body == "ok"


def test_timeout_rules_protect_owner_self_and_staff() -> None:
    _r, safety, _st, members, users, access, org_id, owner, _room = _rig()
    mod = _holder(members, users, access, org_id, "chat:timeout", "mod@x.com")
    peer = _holder(members, users, access, org_id, "chat:moderate", "peer@x.com")
    plain = _member(members, users, org_id, "p@x.com")
    for actor, target in ((mod, owner), (mod, mod), (mod, peer), (plain, mod)):
        with pytest.raises(ForbiddenError):
            safety.timeout(org_id, actor, target, 5)
    with pytest.raises(MemberNotFoundError):
        safety.timeout(org_id, mod, uuid4(), 5)
    assert safety.timeout(org_id, owner, peer, 5).user_id == peer  # owner may
    with pytest.raises(ForbiddenError):
        safety.lift(org_id, plain, peer)


def test_attachment_policy_limits_uploads_to_chat_attach() -> None:
    rooms, safety, store, members, users, access, org_id, owner, room = _rig()
    plain = _member(members, users, org_id, "p@x.com")
    allowed = _holder(members, users, access, org_id, "chat:attach", "a@x.com")
    with pytest.raises(ForbiddenError):
        safety.set_attach_restricted(org_id, plain, True)
    assert safety.set_attach_restricted(org_id, owner, True) is True

    with pytest.raises(ChatAttachRestrictedError):
        rooms.create_attachment(room, plain, "a.png", "image/png", b"x")
    with pytest.raises(ChatAttachRestrictedError):
        rooms.send_message(room, plain, "pic", attachment_ids=[uuid4()])
    # Text is never restricted, the holder passes the gate, the owner too.
    assert rooms.send_message(room, plain, "text only").body == "text only"
    for uid in (allowed, owner):
        try:
            rooms.send_message(room, uid, "pic", attachment_ids=[uuid4()])
        except ChatAttachRestrictedError:
            pytest.fail("holder was blocked by the attachment policy")
        except Exception:  # noqa: BLE001 - unknown media id fails later
            pass
    safety.set_attach_restricted(org_id, owner, False)
    assert store.attach_restricted(org_id) is False
