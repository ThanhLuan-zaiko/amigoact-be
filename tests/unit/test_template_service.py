"""TemplateService + certificate-issue-with-template tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import uuid_utils

from core.exceptions import (
    ForbiddenError,
    InvalidRegistrationStateError,
    NotFoundError,
)
from tests.unit.hour_fakes import (
    FakeTemplates,
    make_cert_service,
    make_template_service,
)
from tests.unit.registration_fakes import published_activity


def _org(orgs):
    owner = uuid_utils.uuid7()
    org = orgs.create(
        uuid_utils.uuid7(), owner, "Club", "club", "", "club",
        "open", None, None, None, None, "none", datetime.now(UTC),
    )
    return owner, org


def test_template_crud_and_acl():
    svc, templates, orgs, _ac = make_template_service()
    owner, org = _org(orgs)
    tpl = svc.create(
        org.id, owner, "M\u1eabu m\u1eb7c \u0111\u1ecbnh", None, '{"title_y": 120}'
    )
    assert tpl.is_active is True
    rows = svc.list(org.id, owner)
    assert [t.template_id for t in rows] == [tpl.template_id]
    updated = svc.update(
        org.id, tpl.template_id, owner,
        name="M\u1eabu 2026", is_active=False,
    )
    assert updated.name == "M\u1eabu 2026" and updated.is_active is False
    with pytest.raises(NotFoundError):
        svc.update(org.id, uuid_utils.uuid7(), owner, name="X")
    with pytest.raises(ForbiddenError):
        svc.create(org.id, uuid_utils.uuid7(), "X")
    with pytest.raises(InvalidRegistrationStateError):
        svc.create(org.id, owner, "  ")
    with pytest.raises(InvalidRegistrationStateError):
        svc.create(org.id, owner, "Bad", None, "not-json")
    with pytest.raises(InvalidRegistrationStateError):
        svc.create(org.id, owner, "Bad", None, "[1,2]")


def test_issue_with_valid_template_stamps_it():
    templates = FakeTemplates()
    svc, certs, regs, activities, orgs, _ac, _u, _n = (
        make_cert_service(templates)
    )
    owner, org = _org(orgs)
    a = published_activity(activities, org.id, owner)
    tpl = templates.create(
        uuid_utils.uuid7(), org.id, "M\u1eabu", None, None,
        datetime.now(UTC),
    )
    student = uuid_utils.uuid7()
    regs.create(
        a.id, student, None, uuid_utils.uuid7(), datetime.now(UTC),
        status="attended",
    )
    row = svc.issue(a.id, student, owner, tpl.template_id)
    assert row.template_id == tpl.template_id


def test_issue_rejects_wrong_or_inactive_template():
    templates = FakeTemplates()
    svc, _c, regs, activities, orgs, _ac, _u, _n = (
        make_cert_service(templates)
    )
    owner, org = _org(orgs)
    a = published_activity(activities, org.id, owner)
    student = uuid_utils.uuid7()
    regs.create(
        a.id, student, None, uuid_utils.uuid7(), datetime.now(UTC),
        status="attended",
    )
    with pytest.raises(NotFoundError):
        svc.issue(a.id, student, owner, uuid_utils.uuid7())
    # Template of a different org is not usable.
    other = orgs.create(
        uuid_utils.uuid7(), owner, "Club 2", "club-2", "", "club",
        "open", None, None, None, None, "none", datetime.now(UTC),
    )
    foreign = templates.create(
        uuid_utils.uuid7(), other.id, "Foreign", None, None,
        datetime.now(UTC),
    )
    with pytest.raises(NotFoundError):
        svc.issue(a.id, student, owner, foreign.template_id)
    # Inactive template is not usable.
    tpl = templates.create(
        uuid_utils.uuid7(), org.id, "Off", None, None,
        datetime.now(UTC),
    )
    templates.update(tpl.template_id, is_active=False)
    with pytest.raises(NotFoundError):
        svc.issue(a.id, student, owner, tpl.template_id)
    # No template still works.
    row = svc.issue(a.id, student, owner)
    assert row.template_id is None
