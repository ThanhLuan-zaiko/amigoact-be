"""Unit tests: threads that link an activity need owner or activity:create."""

from __future__ import annotations

import pytest

from core.exceptions import ForbiddenError
from tests.unit.test_chat_threads import _manager, _member, _thread, _world
from tests.unit.workspace_fakes import _uid


def test_event_thread_needs_owner_or_activity_create() -> None:
    (_s, _r, threads, _rooms, _c, _ch, _o,
     members, users, access, org_id, owner, acts,) = _world()
    activity_id = _uid()
    acts.add(activity_id, org_id, "Beach cleanup")
    plain = _member(members, users, org_id)
    chat_manager = _manager(access, members, users, org_id)
    creator = _member(members, users, org_id, "creator@x.com")
    access.perms.setdefault((org_id, creator), set()).add("activity:create")
    with pytest.raises(ForbiddenError):
        _thread(threads, org_id, org_id, plain, activity_id=activity_id)
    # chat:manage alone does not grant event creation.
    with pytest.raises(ForbiddenError):
        _thread(
            threads, org_id, org_id, chat_manager, activity_id=activity_id
        )
    # Plain threads without an event stay open to every member.
    _thread(threads, org_id, org_id, plain, name="plain-talk")
    snap = _thread(
        threads, org_id, org_id, creator,
        name="creator-thread", activity_id=activity_id,
    )
    assert snap.activity_id == activity_id
    owned = _thread(
        threads, org_id, org_id, owner,
        name="owner-thread", activity_id=activity_id,
    )
    assert owned.activity_id == activity_id
