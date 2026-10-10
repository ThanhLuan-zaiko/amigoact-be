"""Unit tests for Phase 6: leaderboard, prefs, reviews, stats, discovery."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from core.exceptions import (
    ForbiddenError,
    InvalidRegistrationStateError,
    ReviewExistsError,
)
from notifications.interfaces import PreferenceStore
from notifications.service import NotificationService
from reviews.service import ReviewService
from stats.service import OrgStatsService
from tests.unit.activity_fakes import (
    FakeActivities,
    FakeCategories,
    _fields,
    _org_with_owner,
)
from tests.unit.hour_fakes import (
    FakeCertificates,
    FakeLeaderboard,
    FakeLedger,
    make_hour_service,
    uid,
)
from tests.unit.member_fakes import (
    FakeAccess,
    FakeMembers,
    FakeUsers,
)
from tests.unit.org_fakes import FakeOrgs
from tests.unit.registration_fakes import (
    FakeAttendance,
    FakeRegistrations,
)
from tests.unit.test_notifications import FakeStore


# Leaderboard -----------------------------------------------------------


def _hour_setup() -> tuple:
    board = FakeLeaderboard()
    users = FakeUsers()
    service, ledger, activities, orgs, access, notes = make_hour_service(
        leaderboard=board, users=users
    )
    owner = uid()
    org = _org_with_owner(orgs, owner)
    activity = activities.create(
        org.id, owner, _fields(None), datetime.now(UTC)
    )
    return service, ledger, activity, org, owner, board, users


def test_approve_moves_leaderboard_rows() -> None:
    service, ledger, activity, _o, owner, board, users = _hour_setup()
    student = uid()
    users.add(student, "s@x.dev", "Sinh Viên")
    service.record_attendance(
        activity.org_id, activity.id, student, uid(), 3.0, owner
    )
    entry = next(iter(ledger.rows.values()))
    service.review(entry.entry_id, owner, "approved", None)
    calls = {(t, pt, nt) for (t, _s, pt, nt) in board.calls}
    assert (entry.term, 0.0, 3.0) in calls
    assert ("all", 0.0, 3.0) in calls
    top = service.leaderboard_top("all")
    assert top[0].student_name == "Sinh Viên"
    assert service.leaderboard_terms() == sorted(
        {entry.term, "all"}
    )


def test_second_approval_accumulates_board() -> None:
    service, ledger, activity, _o, owner, board, _u = _hour_setup()
    student = uid()
    for _ in range(2):
        service.record_attendance(
            activity.org_id, activity.id, student, uid(), 2.0, owner
        )
    for entry in list(ledger.rows.values()):
        service.review(entry.entry_id, owner, "approved", None)
    assert service.leaderboard_top("all")[0].total_hours == 4.0


def test_reject_does_not_touch_board() -> None:
    service, ledger, activity, _o, owner, board, _u = _hour_setup()
    service.record_attendance(
        activity.org_id, activity.id, uid(), uid(), 2.0, owner
    )
    entry = next(iter(ledger.rows.values()))
    service.review(entry.entry_id, owner, "rejected", None)
    assert board.calls == []
    assert service.leaderboard_top("all") == []


# Notification preferences ----------------------------------------------


class FakePrefs(PreferenceStore):
    def __init__(self) -> None:
        self.rows: dict[UUID, SimpleNamespace] = {}

    def get(self, user_id):  # noqa: ANN001, ANN202
        return self.rows.get(user_id)

    def save(self, user_id, channels, muted_types, now):  # noqa: ANN001, ANN202
        row = SimpleNamespace(
            user_id=user_id, channels=channels,
            muted_types=muted_types, updated_at=now,
        )
        self.rows[user_id] = row
        return row


def _notify_service() -> tuple[NotificationService, FakeStore, FakePrefs]:
    store, prefs = FakeStore(), FakePrefs()
    return NotificationService(store, None, prefs), store, prefs


def test_muted_type_skips_notification() -> None:
    service, store, _p = _notify_service()
    user = uid()
    service.update_preferences(user, None, {"hours"})
    service.notify(user, "hours", "Giờ được duyệt")
    service.notify(user, "system", "Hệ thống")
    assert len(store.rows) == 1


def test_inapp_channel_off_mutes_everything() -> None:
    service, store, _p = _notify_service()
    user = uid()
    service.update_preferences(user, {"inapp": False}, None)
    service.notify(user, "system", "x")
    assert store.rows == {}


def test_preferences_merge_and_defaults() -> None:
    service, _s, _p = _notify_service()
    user = uid()
    view = service.get_preferences(user)
    assert view.channels == {"inapp": True} and view.muted_types == set()
    service.update_preferences(user, None, {"review"})
    view = service.update_preferences(user, {"email": True}, None)
    assert view.channels == {"inapp": True, "email": True}
    assert view.muted_types == {"review"}


# Reviews ---------------------------------------------------------------


class FakeReviews:
    def __init__(self) -> None:
        self.rows: list[SimpleNamespace] = []

    def add(self, review_id, activity_id, student_id, rating, comment, now):  # noqa: ANN001, ANN202
        row = SimpleNamespace(
            review_id=review_id, activity_id=activity_id,
            student_id=student_id, rating=rating, comment=comment,
            created_at=now,
        )
        self.rows.append(row)
        return row

    def list_for_activity(self, activity_id, limit=50):  # noqa: ANN001, ANN202
        return [
            r for r in self.rows if r.activity_id == activity_id
        ][:limit]

    def list_by_student(self, student_id, limit=100):  # noqa: ANN001, ANN202
        return [
            r for r in self.rows if r.student_id == student_id
        ][:limit]


def _review_setup() -> tuple:
    reviews = FakeReviews()
    activities = FakeActivities()
    regs = FakeRegistrations()
    orgs = FakeOrgs()
    users = FakeUsers()
    service = ReviewService(
        reviews=reviews, activities=activities, registrations=regs,
        orgs=orgs, users=users, notifications=None,
    )
    owner = uid()
    org = _org_with_owner(orgs, owner)
    activity = activities.create(
        org.id, owner, _fields(None), datetime.now(UTC)
    )
    return service, reviews, regs, activity, users


def _attend(regs: FakeRegistrations, activity_id, student: UUID) -> None:
    regs.guards[(activity_id, student, UUID(int=0))] = SimpleNamespace(
        status="attended", registration_id=uid()
    )


def test_attended_student_reviews_once() -> None:
    service, _r, regs, activity, users = _review_setup()
    student = uid()
    users.add(student, "s@x.dev", "Reviewer")
    _attend(regs, activity.id, student)
    view = service.create(activity.id, student, 5, "Tuyệt vời")
    assert view.student_name == "Reviewer"
    assert service.list_for_activity(activity.id)[0].rating == 5
    assert not service.can_review(activity.id, student)
    with pytest.raises(ReviewExistsError):
        service.create(activity.id, student, 4, None)


def test_non_attended_cannot_review() -> None:
    service, _r, regs, activity, _u = _review_setup()
    student = uid()
    with pytest.raises(InvalidRegistrationStateError):
        service.create(activity.id, student, 5, None)
    regs.guards[(activity.id, student, UUID(int=0))] = SimpleNamespace(
        status="approved"
    )
    with pytest.raises(InvalidRegistrationStateError):
        service.create(activity.id, student, 5, None)
    assert service.can_review(activity.id, student) is False


# Org stats -------------------------------------------------------------


def _stats_setup() -> tuple:
    orgs, members = FakeOrgs(), FakeMembers()
    activities, ledger = FakeActivities(), FakeLedger()
    attendance, certs = FakeAttendance(), FakeCertificates()
    access = FakeAccess()
    service = OrgStatsService(
        orgs=orgs, members=members, activities=activities,
        hours=ledger, attendance=attendance, certificates=certs,
        access=access,
    )
    owner = uid()
    org = _org_with_owner(orgs, owner)
    return service, org, owner, members, activities, ledger, attendance, certs


def test_org_stats_aggregates_feeds() -> None:
    svc, org, owner, members, activities, ledger, att, certs = (
        _stats_setup()
    )
    activity = activities.create(
        org.id, owner, _fields(None), datetime.now(UTC)
    )
    members.put(org.id, owner, "active", datetime.now(UTC))
    members.put(org.id, uid(), "active", datetime.now(UTC))
    now = datetime.now(UTC)
    att.create(uid(), activity.id, uid(), None, "qr", owner, now)
    ledger.record(
        uid(), org.id, uid(), activity.id, "attendance", 3.0,
        "2026-H1", None, owner, None, now,
    )
    entry = next(iter(ledger.rows.values()))
    entry.status = "approved"
    certs.issue(uid(), activity.id, uid(), None, "AMG-T", owner, now)
    stats = svc.org_stats(org.id, owner)
    assert stats.activities_total == 1
    assert stats.members_total == 2
    assert stats.participants_total == 1
    assert stats.hours_approved == 3.0
    assert stats.certificates_issued == 1


def test_org_stats_forbidden_for_outsiders() -> None:
    svc, org, _o, *_ = _stats_setup()
    with pytest.raises(ForbiddenError):
        svc.org_stats(org.id, uid())


# Discovery -------------------------------------------------------------


def test_discovery_curates_sections() -> None:
    from activities.service import ActivityService
    from tests.unit.member_fakes import FakeAccess

    activities = FakeActivities()
    categories = FakeCategories()
    orgs = FakeOrgs()
    service = ActivityService(
        activities=activities, categories=categories, orgs=orgs,
        access=FakeAccess(),
    )
    owner = uid()
    org = _org_with_owner(orgs, owner)
    cat = categories.seed("Môi trường", "moi-truong")
    for index in range(3):
        row = activities.create(
            org.id, owner,
            _fields(None, category_id=cat.id), datetime.now(UTC),
        )
        row.status = "published"
    draft = activities.create(
        org.id, owner, _fields(None), datetime.now(UTC)
    )
    view = service.discovery(4)
    assert len(view.featured) == 3
    assert len(view.upcoming) == 3
    assert draft.id not in {a.id for a in view.featured}
    assert view.categories[0].name == "Môi trường"
    assert len(view.categories[0].items) == 3
