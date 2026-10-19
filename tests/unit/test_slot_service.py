"""SlotService + slot-aware registration unit tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
import uuid_utils

from activities.slot_service import SlotService
from core.exceptions import (
    ForbiddenError,
    InvalidRegistrationStateError,
    NotFoundError,
)
from registrations.service import RegistrationService
from tests.unit.edge_fakes import FakeSchedules, FakeSlots
from tests.unit.member_fakes import FakeAccess
from tests.unit.org_fakes import FakeOrgs
from tests.unit.registration_fakes import (
    FakeActivities,
    FakeAttendance,
    FakeNotifications,
    FakeRegistrations,
    published_activity,
)


def _svc():
    activities = FakeActivities()
    schedules = FakeSchedules()
    slots = FakeSlots(schedules)
    orgs = FakeOrgs()
    access = FakeAccess()
    regs = FakeRegistrations()
    service = SlotService(
        activities=activities,
        schedules=schedules,
        slots=slots,
        orgs=orgs,
        access=access,
        registrations=regs,
    )
    return service, activities, schedules, slots, orgs, access, regs


def _org(orgs: FakeOrgs, owner: UUID):
    return orgs.create(
        uuid_utils.uuid7(), owner, "Club", "club", "", "club",
        "open", None, None, None, None, "none", datetime.now(UTC),
    )


def test_manager_creates_and_lists_slots():
    service, activities, schedules, slots, orgs, access, _ = _svc()
    owner = uuid_utils.uuid7()
    org = _org(orgs, owner)
    a = published_activity(activities, org.id, owner)
    sch = schedules.create(
        uuid_utils.uuid7(), a.id, "Day 1", None, None, None,
        datetime.now(UTC),
    )
    slot = service.create_slot(
        org.id, a.id, sch.id, owner, "Morning", 5, None, None
    )
    assert slot.title == "Morning"
    rows = service.list_for_activity(org.id, a.id, owner)
    assert [r.slot_id for r in rows] == [slot.slot_id]


def test_create_slot_rejects_foreign_schedule_and_non_manager():
    service, activities, schedules, slots, orgs, access, _ = _svc()
    owner = uuid_utils.uuid7()
    org = _org(orgs, owner)
    a = published_activity(activities, org.id, owner)
    other = published_activity(activities, org.id, owner)
    sch = schedules.create(
        uuid_utils.uuid7(), other.id, "Elsewhere", None, None, None,
        datetime.now(UTC),
    )
    with pytest.raises(NotFoundError):
        service.create_slot(
            org.id, a.id, sch.id, owner, "Morning", 5, None, None
        )
    sch2 = schedules.create(
        uuid_utils.uuid7(), a.id, "Day", None, None, None,
        datetime.now(UTC),
    )
    with pytest.raises(ForbiddenError):
        service.create_slot(
            org.id, a.id, sch2.id, uuid_utils.uuid7(), "Morning",
            5, None, None,
        )


def test_delete_slot_blocked_by_live_registration():
    service, activities, schedules, slots, orgs, access, regs = _svc()
    owner = uuid_utils.uuid7()
    org = _org(orgs, owner)
    a = published_activity(activities, org.id, owner)
    sch = schedules.create(
        uuid_utils.uuid7(), a.id, "Day", None, None, None,
        datetime.now(UTC),
    )
    slot = service.create_slot(
        org.id, a.id, sch.id, owner, "Morning", 5, None, None
    )
    reg = regs.create(
        a.id, uuid_utils.uuid7(), None, uuid_utils.uuid7(),
        datetime.now(UTC), status="approved", slot_id=slot.slot_id,
    )
    assert reg.slot_id == slot.slot_id
    with pytest.raises(InvalidRegistrationStateError):
        service.delete_slot(org.id, a.id, sch.id, slot.slot_id, owner)
    regs.set_status(
        reg.registration_id, "cancelled", owner, None, datetime.now(UTC)
    )
    service.delete_slot(org.id, a.id, sch.id, slot.slot_id, owner)
    assert service.list_for_activity(org.id, a.id, owner) == []


def test_registration_slot_capacity_and_promotion():
    """Slot-scoped capacity waitlists independently of the activity."""
    activities = FakeActivities()
    schedules = FakeSchedules()
    slots = FakeSlots(schedules)
    orgs = FakeOrgs()
    access = FakeAccess()
    regs = FakeRegistrations()
    notifications = FakeNotifications()
    owner = uuid_utils.uuid7()
    org = _org(orgs, owner)
    a = published_activity(activities, org.id, owner)
    a.max_participants = None  # activity-wide: unlimited
    sch = schedules.create(
        uuid_utils.uuid7(), a.id, "Day", None, None, None,
        datetime.now(UTC),
    )
    slot = slots.create(
        uuid_utils.uuid7(), sch.id, "Morning", 1, None, None
    )
    service = RegistrationService(
        registrations=regs,
        attendance=FakeAttendance(),
        activities=activities,
        orgs=orgs,
        users=None,
        access=access,
        notifications=notifications,
        slots=slots,
    )
    s1, s2 = uuid_utils.uuid7(), uuid_utils.uuid7()
    r1 = service.apply(a.id, s1, None, slot_id=slot.slot_id)
    regs.set_status(
        r1.registration_id, "approved", owner, None, datetime.now(UTC)
    )
    r2 = service.apply(a.id, s2, None, slot_id=slot.slot_id)
    assert r2.status == "waitlisted"
    assert r2.slot_id == slot.slot_id
    slot2 = slots.create(
        uuid_utils.uuid7(), sch.id, "Afternoon", 1, None, None
    )
    r3 = service.apply(a.id, uuid_utils.uuid7(), None, slot_id=slot2.slot_id)
    assert r3.status == "pending"
    service.cancel(a.id, r1.registration_id, s1)
    assert regs.rows[r2.registration_id].status == "approved"


def test_apply_unknown_slot_404():
    activities = FakeActivities()
    orgs = FakeOrgs()
    access = FakeAccess()
    owner = uuid_utils.uuid7()
    org = _org(orgs, owner)
    a = published_activity(activities, org.id, owner)
    service = RegistrationService(
        registrations=FakeRegistrations(),
        attendance=FakeAttendance(),
        activities=activities,
        orgs=orgs,
        users=None,
        access=access,
        notifications=FakeNotifications(),
        slots=FakeSlots(),
    )
    with pytest.raises(NotFoundError):
        service.apply(
            a.id, uuid_utils.uuid7(), None, slot_id=uuid_utils.uuid7()
        )
