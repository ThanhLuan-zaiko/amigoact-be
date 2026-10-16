"""Unit tests for custom sign-up forms (registration_forms)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import UUID

import pytest
import uuid_utils

from datetime import UTC, datetime

from activities.form_service import FormService
from core.exceptions import ForbiddenError, InvalidRegistrationStateError
from tests.unit.registration_fakes import (
    make_reg_services,
    published_activity,
)


class FakeForms:
    def __init__(self) -> None:
        self.questions: dict = {}

    def list_form(self, activity_id):  # noqa: ANN001, ANN202
        return self.questions.get(activity_id, [])

    def replace_form(self, activity_id, questions):  # noqa: ANN001, ANN202
        self.questions[activity_id] = [
            SimpleNamespace(
                activity_id=activity_id,
                position=i,
                question_id=qid,
                label=label,
                field_type=ft,
                required=req,
            )
            for i, (qid, label, ft, req) in enumerate(questions)
        ]


def _setup():
    (
        reg_service, _att, regs, _a, activities, orgs, access, users, _n
    ) = make_reg_services()
    forms = FakeForms()
    reg_service._forms = forms
    owner = uuid_utils.uuid7()
    org = orgs.create(
        uuid_utils.uuid7(), owner, "Club", "club", "", "club",
        "open", None, None, None, None, "none", datetime.now(UTC),
    )
    activity = published_activity(activities, org.id, owner)
    svc = FormService(
        activities=activities, forms=forms, orgs=orgs, access=access
    )
    return svc, reg_service, forms, org, owner, activity


def test_set_form_roundtrip_and_validation() -> None:
    svc, reg, forms, org, owner, act = _setup()
    rows = svc.set_form(
        org.id, act.id, owner,
        [("T\xean \u0111\u1ed9i?", "text", True), ("\u0110\u1ed3ng \xfd n\u1ed9i quy", "consent", False)],
    )
    assert [r.label for r in rows] == ["T\xean \u0111\u1ed9i?", "\u0110\u1ed3ng \xfd n\u1ed9i quy"]
    qid = str(rows[0].question_id)
    student = uuid_utils.uuid7()
    with pytest.raises(InvalidRegistrationStateError):
        reg.apply(act.id, student, None, {})
    row = reg.apply(act.id, student, None, {qid: "\u0110\u1ed9i A"})
    assert json.loads(row.form_data) == {qid: "\u0110\u1ed9i A"}


def test_form_acl() -> None:
    svc, _r, _f, org, owner, act = _setup()
    outsider = uuid_utils.uuid7()
    with pytest.raises(ForbiddenError):
        svc.set_form(org.id, act.id, outsider, [])
    # Public read while applyable; managers when not.
    assert svc.get_form(org.id, act.id, None) == []
    act.status = "draft"
    with pytest.raises(ForbiddenError):
        svc.get_form(org.id, act.id, None)
    assert svc.get_form(org.id, act.id, owner) == []


def test_set_form_rejects_bad_type() -> None:
    svc, _r, _f, org, owner, act = _setup()
    with pytest.raises(InvalidRegistrationStateError):
        svc.set_form(org.id, act.id, owner, [("Q?", "bogus", False)])
