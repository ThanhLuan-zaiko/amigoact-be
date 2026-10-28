"""Choice options and the form heading: schema rules and service round-trip."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from orgs.application_schemas import MembershipFormBody
from tests.unit.member_fakes import _new_user, _service


def test_choice_options_are_trimmed_and_deduplicated() -> None:
    body = MembershipFormBody(
        questions=[
            {"label": "Ca học?", "field_type": "choice", "options": [" Sáng ", "Chiều", "Sáng"]}
        ]
    )
    assert body.questions[0].options == ["Sáng", "Chiều"]


def test_choice_needs_at_least_two_options() -> None:
    with pytest.raises(ValidationError):
        MembershipFormBody(
            questions=[{"label": "Ca?", "field_type": "choice", "options": ["Sáng"]}]
        )


def test_non_choice_questions_drop_options() -> None:
    body = MembershipFormBody(
        questions=[{"label": "Ghi chú", "field_type": "text", "options": ["a", "b"]}]
    )
    assert body.questions[0].options == []


def test_label_cannot_contain_the_separator() -> None:
    with pytest.raises(ValidationError):
        MembershipFormBody(questions=[{"label": "a|b"}])


def test_service_stores_options_and_heading() -> None:
    service, _, _, _, _, org_id, owner = _service("review")
    service.replace_membership_form(
        org_id,
        owner,
        [("Ca?", "choice", True, ["Sáng", "Chiều"], False)],
        title=" Đăng ký ",
        description="Mô tả",
    )
    rows = service.list_membership_form(org_id)
    assert json.loads(rows[0].options) == ["Sáng", "Chiều"]
    assert service.membership_form_heading(org_id) == ("Đăng ký", "Mô tả")


def test_heading_defaults_to_blank() -> None:
    service, _, _, _, _, org_id, _ = _service("review")
    assert service.membership_form_heading(org_id) == ("", "")


def test_choice_answer_outside_the_options_is_dropped() -> None:
    service, _, _, users, _, org_id, owner = _service("review")
    service.replace_membership_form(
        org_id, owner, [("Ca?", "choice", False, ["Sáng", "Chiều"], False)]
    )
    question_id = str(service.list_membership_form(org_id)[0].question_id)
    applicant = _new_user(users, "a@example.com")
    service.apply_to_org(org_id, applicant, {question_id: "Tối"})
    stored, _ = service.get_application(org_id, owner, applicant)
    assert json.loads(stored.answers) == {}


def test_other_counts_as_one_choice() -> None:
    body = MembershipFormBody(
        questions=[{"label": "Ca?", "field_type": "choice", "options": ["Sáng"], "allow_other": True}]
    )
    assert body.questions[0].allow_other is True


def test_choice_needs_two_choices_including_other() -> None:
    with pytest.raises(ValidationError):
        MembershipFormBody(
            questions=[{"label": "Ca?", "field_type": "choice", "options": [], "allow_other": True}]
        )


def test_allow_other_is_dropped_for_non_choice() -> None:
    body = MembershipFormBody(
        questions=[{"label": "Ghi chú", "field_type": "text", "allow_other": True}]
    )
    assert body.questions[0].allow_other is False


def test_other_answer_is_kept_when_allowed() -> None:
    service, _, _, users, _, org_id, owner = _service("review")
    service.replace_membership_form(
        org_id, owner, [("Lý do?", "choice", False, ["Ngày nghỉ", "Bận việc"], True)]
    )
    question_id = str(service.list_membership_form(org_id)[0].question_id)
    applicant = _new_user(users, "a@example.com")
    service.apply_to_org(org_id, applicant, {question_id: "Đi công tác xa"})
    stored, _ = service.get_application(org_id, owner, applicant)
    assert json.loads(stored.answers) == {question_id: "Đi công tác xa"}


def test_other_text_is_dropped_when_not_allowed() -> None:
    service, _, _, users, _, org_id, owner = _service("review")
    service.replace_membership_form(
        org_id, owner, [("Lý do?", "choice", False, ["Ngày nghỉ", "Bận việc"], False)]
    )
    question_id = str(service.list_membership_form(org_id)[0].question_id)
    applicant = _new_user(users, "a@example.com")
    service.apply_to_org(org_id, applicant, {question_id: "Đi công tác xa"})
    stored, _ = service.get_application(org_id, owner, applicant)
    assert json.loads(stored.answers) == {}


def test_reviewer_sees_other_answers_flagged() -> None:
    from tests.unit.test_application_routes import _client

    service, _, _, users, _, org_id, owner = _service("review")
    service.replace_membership_form(
        org_id, owner, [("Lý do?", "choice", False, ["Ngày nghỉ", "Bận việc"], True)]
    )
    question_id = str(service.list_membership_form(org_id)[0].question_id)
    applicant = _new_user(users, "a@example.com")
    _client(service, applicant).post(
        f"/orgs/{org_id}/members/apply", json={"answers": {question_id: "Đi công tác xa"}}
    )
    read = _client(service, owner).get(f"/orgs/{org_id}/members/{applicant}/application")
    answer = read.json()["answers"][0]
    assert (answer["answer"], answer["is_other"]) == ("Đi công tác xa", True)
