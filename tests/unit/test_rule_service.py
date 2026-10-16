"""RuleService unit tests: rule CRUD, matching, and adjustments."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import uuid_utils

from core.exceptions import (
    ForbiddenError,
    InvalidHoursStateError,
    NotFoundError,
)
from hours.rule_service import RuleService, apply_rule, match_rule
from tests.unit.hour_fakes import (
    FakeAdjustments,
    FakeLedger,
    FakeRules,
    make_hour_service,
)
from tests.unit.member_fakes import FakeAccess
from tests.unit.org_fakes import FakeOrgs
from tests.unit.registration_fakes import (
    FakeActivities,
    FakeNotifications,
    published_activity,
)


def _svc():
    activities = FakeActivities()
    orgs = FakeOrgs()
    access = FakeAccess()
    rules = FakeRules()
    adjustments = FakeAdjustments()
    ledger = FakeLedger()
    notes = FakeNotifications()
    service = RuleService(
        rules=rules,
        adjustments=adjustments,
        ledger=ledger,
        activities=activities,
        orgs=orgs,
        access=access,
        notifications=notes,
    )
    return (
        service, activities, orgs, access,
        rules, adjustments, ledger, notes,
    )


def _org(orgs: FakeOrgs):
    owner = uuid_utils.uuid7()
    org = orgs.create(
        uuid_utils.uuid7(), owner, "Club", "club", "", "club",
        "open", None, None, None, None, "none", datetime.now(UTC),
    )
    return owner, org


def test_manager_crud_rules():
    svc, _a, orgs, _ac, rules, _ad, _l, _n = _svc()
    owner, org = _org(orgs)
    category = uuid_utils.uuid7()
    rule = svc.create_rule(
        org.id, owner, 1.5, category, cap_hours=10.0, term="2026-H1"
    )
    assert rule.is_active is True
    rows = svc.list_rules(org.id, owner)
    assert [r.rule_id for r in rows] == [rule.rule_id]
    off = svc.set_rule_active(org.id, rule.rule_id, owner, False)
    assert off.is_active is False
    with pytest.raises(NotFoundError):
        svc.set_rule_active(
            org.id, uuid_utils.uuid7(), owner, True
        )
    with pytest.raises(ForbiddenError):
        svc.create_rule(org.id, uuid_utils.uuid7(), 2.0)
    with pytest.raises(InvalidHoursStateError):
        svc.create_rule(org.id, owner, 0)
    with pytest.raises(InvalidHoursStateError):
        svc.create_rule(org.id, owner, 1.0, cap_hours=-1)


def test_match_rule_specificity():
    cat = uuid_utils.uuid7()
    rules = [
        # org-wide
        _mk_rule(None, None),
        # term only
        _mk_rule(None, "2026-H1"),
        # category only
        _mk_rule(cat, None),
        # category + term (most specific)
        _mk_rule(cat, "2026-H1"),
    ]
    hit = match_rule(rules, cat, "2026-H1")
    assert hit is rules[3]
    hit = match_rule(rules, cat, "2026-H2")
    assert hit is rules[2]
    hit = match_rule(rules, uuid_utils.uuid7(), "2026-H1")
    assert hit is rules[1]
    hit = match_rule(rules, uuid_utils.uuid7(), "2026-H2")
    assert hit is rules[0]
    # inactive rules are skipped entirely
    rules[3].is_active = False
    assert match_rule(rules, cat, "2026-H1") is rules[2]


def _mk_rule(category_id, term):
    from types import SimpleNamespace

    return SimpleNamespace(
        rule_id=uuid_utils.uuid7(), category_id=category_id,
        term=term, multiplier=2.0, cap_hours=None, is_active=True,
    )


def test_apply_rule_multiplies_and_caps():
    cat = uuid_utils.uuid7()
    rules = [
        _mk_rule(cat, None),
    ]
    rules[0].cap_hours = 6.0
    # 4h * 2.0 = 8 -> capped at 6
    assert apply_rule(rules, cat, "2026-H1", 4.0) == 6.0
    # 2h * 2.0 = 4 -> under cap
    assert apply_rule(rules, cat, "2026-H1", 2.0) == 4.0
    # no rule -> raw hours
    assert apply_rule(rules, uuid_utils.uuid7(), "2026-H1", 4.0) == 4.0
    assert apply_rule(None, cat, "2026-H1", 4.0) == 4.0


def test_record_attendance_applies_rule():
    rules = FakeRules()
    svc, ledger, activities, orgs, _ac, _n = make_hour_service(
        rules=rules
    )
    owner, org = _org(orgs)
    a = published_activity(activities, org.id, owner)
    cat = uuid_utils.uuid7()
    a.category_id = cat
    rules.create(
        uuid_utils.uuid7(), org.id, cat, 2.0, None, None
    )
    student = uuid_utils.uuid7()
    svc.record_attendance(
        org.id, a.id, student, uuid_utils.uuid7(), 3.0, owner
    )
    entry = next(iter(ledger.rows.values()))
    assert entry.hours == 6.0
    # Inactive rule -> raw hours again.
    for r in rules.rows.values():
        r.is_active = False
    svc.record_attendance(
        org.id, a.id, student, uuid_utils.uuid7(), 3.0, owner
    )
    entries = list(ledger.rows.values())
    assert entries[-1].hours == 3.0


def test_adjust_queues_ledger_entry_and_audit():
    svc, activities, orgs, _ac, _r, adjustments, ledger, notes = _svc()
    owner, org = _org(orgs)
    a = published_activity(activities, org.id, owner)
    student = uuid_utils.uuid7()
    audit = svc.adjust(
        org.id, owner, student, a.id, -1.5, "Sai gi\u1edd check-out"
    )
    assert audit.delta_hours == -1.5
    entry = next(iter(ledger.rows.values()))
    assert entry.source == "adjustment"
    assert entry.hours == -1.5
    assert entry.status == "pending"
    assert notes.sent[-1][0] == student
    with pytest.raises(InvalidHoursStateError):
        svc.adjust(org.id, owner, student, a.id, 0, "Zero")
    with pytest.raises(InvalidHoursStateError):
        svc.adjust(org.id, owner, student, a.id, 1.0, "  ")
    with pytest.raises(NotFoundError):
        svc.adjust(
            org.id, owner, student, uuid_utils.uuid7(), 1.0, "L\u1ec7ch"
        )
    with pytest.raises(ForbiddenError):
        svc.adjust(
            org.id, uuid_utils.uuid7(), student, a.id, 1.0, "X"
        )
