"""Unit tests for ActivityDetailService: skills, partners, staff."""

from __future__ import annotations

import uuid_utils
import pytest

from core.exceptions import ForbiddenError, NotFoundError
from tests.unit.activity_fakes import (
    _fields,
    _org_with_owner,
    make_services,
)


def _setup():
    svc = make_services()
    service, detail, _, orgs, _, _, users, skills = svc
    owner, member = uuid_utils.uuid7(), uuid_utils.uuid7()
    org = _org_with_owner(orgs, owner)
    orgs.members[org.id].add(member)
    activity = service.create_activity(org.id, owner, _fields(None))
    return detail, orgs, skills, users, org, activity, owner, member


def test_set_skills_validates_catalog() -> None:
    detail, _, skills, _, org, activity, owner, _ = _setup()
    skill = skills.add_skill("First Aid", "first-aid")
    with pytest.raises(NotFoundError):
        detail.set_skills(
            org.id, activity.id, owner, [(uuid_utils.uuid7(), True)]
        )
    view = detail.set_skills(
        org.id, activity.id, owner, [(skill.id, True)]
    )
    assert view.skills[0].name == "First Aid"
    assert view.skills[0].is_required is True


def test_set_partners_requires_live_orgs() -> None:
    detail, orgs, _, _, org, activity, owner, _ = _setup()
    partner = _org_with_owner(orgs, uuid_utils.uuid7(), slug="biz")
    with pytest.raises(NotFoundError):
        detail.set_partners(
            org.id, activity.id, owner,
            [(uuid_utils.uuid7(), "sponsor", None)],
        )
    view = detail.set_partners(
        org.id, activity.id, owner,
        [(partner.id, "sponsor", "VND 5tr")],
    )
    assert view.partners[0].role == "sponsor"
    assert view.partners[0].name == "Club"


def test_set_staff_requires_membership() -> None:
    detail, orgs, _, users, org, activity, owner, member = _setup()
    outsider = uuid_utils.uuid7()
    with pytest.raises(ForbiddenError):
        detail.set_staff(
            org.id, activity.id, owner, [(outsider, "organizer")]
        )
    view = detail.set_staff(
        org.id, activity.id, owner, [(member, "supervisor")]
    )
    assert view.staff[0].staff_role == "supervisor"


def test_schedules_and_announcements_flow() -> None:
    detail, _, _, _, org, activity, owner, member = _setup()
    from datetime import UTC, datetime, timedelta

    start = datetime.now(UTC) + timedelta(days=3)
    view = detail.add_schedule(
        org.id, activity.id, owner, "Day 1", "Beach", start, None
    )
    assert len(view.schedules) == 1
    schedule_id = view.schedules[0].id
    view = detail.delete_schedule(
        org.id, activity.id, schedule_id, owner
    )
    assert view.schedules == []
    with pytest.raises(NotFoundError):
        detail.delete_schedule(org.id, activity.id, schedule_id, owner)

    view = detail.add_announcement(
        org.id, activity.id, owner, "Reminder", "Bring gloves"
    )
    assert view.announcements[0].title == "Reminder"

    with pytest.raises(ForbiddenError):
        detail.add_announcement(
            org.id, activity.id, member, "Hack", "member can't post"
        )


def test_detail_visibility() -> None:
    detail, _, _, _, org, activity, owner, member = _setup()
    with pytest.raises(NotFoundError):
        detail.detail(org.id, activity.id, None)
    assert detail.detail(org.id, activity.id, member).activity.id == activity.id
