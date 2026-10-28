"""Evidence files on membership applications: upload rules and answer ownership."""

from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import UUID

import pytest

from core.exceptions import UnsupportedMediaError
from core.exceptions_applications import AnswerRequiredError
from core.ids import uuid7
from core.media_rules import MEMBERSHIP_OWNER, prepare_evidence_upload
from orgs.application_schemas import MembershipFormBody
from tests.unit.member_fakes import _new_user, _service

PDF = b"%PDF-1.4\n%fake evidence\n"


class FakeMedia:
    """Only the read side: assets keyed by id."""

    def __init__(self) -> None:
        self.assets: dict[UUID, SimpleNamespace] = {}

    def get_asset(self, asset_id):  # noqa: ANN001, ANN202
        return self.assets.get(asset_id)

    def add(self, org_id, uploader_id, owner_type=MEMBERSHIP_OWNER, name="minh-chung.pdf"):  # noqa: ANN001, ANN202
        asset_id = uuid7()
        self.assets[asset_id] = SimpleNamespace(
            asset_id=asset_id,
            owner_type=owner_type,
            owner_id=org_id,
            uploader_id=uploader_id,
            original_name=name,
            mime="application/pdf",
            size_bytes=len(PDF),
            file_url=f"orgs/{org_id}/{asset_id}.pdf",
        )
        return asset_id


def test_pdf_with_pdf_magic_is_accepted() -> None:
    prepared = prepare_evidence_upload("application/pdf", PDF, 1024)
    assert (prepared.kind, prepared.mime) == ("document", "application/pdf")


def test_pdf_without_pdf_magic_is_rejected() -> None:
    with pytest.raises(UnsupportedMediaError):
        prepare_evidence_upload("application/pdf", b"not a pdf", 1024)


def test_zip_and_video_are_rejected() -> None:
    with pytest.raises(UnsupportedMediaError):
        prepare_evidence_upload("application/zip", b"PK\x03\x04", 1024)
    with pytest.raises(UnsupportedMediaError):
        prepare_evidence_upload("video/mp4", b"\x00\x00\x00\x18ftyp", 1024)


def test_file_question_is_a_valid_form_field() -> None:
    body = MembershipFormBody(
        questions=[{"label": "Giấy xác nhận", "field_type": "file", "required": True, "options": ["x"]}]
    )
    assert body.questions[0].field_type == "file"
    assert body.questions[0].options == []


def test_own_evidence_for_this_org_is_kept() -> None:
    media = FakeMedia()
    service, _, _, users, _, org_id, owner = _service("review", media=media)
    service.replace_membership_form(org_id, owner, [("Giấy xác nhận", "file", True, [], False)])
    applicant = _new_user(users, "a@example.com")
    question_id = str(service.list_membership_form(org_id)[0].question_id)
    file_id = media.add(org_id, applicant)

    service.apply_to_org(org_id, applicant, {question_id: str(file_id)})

    stored, _ = service.get_application(org_id, owner, applicant)
    assert json.loads(stored.answers) == {question_id: str(file_id)}


def test_someone_elses_file_is_dropped_and_required_fails() -> None:
    media = FakeMedia()
    service, _, _, users, _, org_id, owner = _service("review", media=media)
    service.replace_membership_form(org_id, owner, [("Giấy xác nhận", "file", True, [], False)])
    applicant = _new_user(users, "a@example.com")
    other = _new_user(users, "b@example.com")
    question_id = str(service.list_membership_form(org_id)[0].question_id)
    file_id = media.add(org_id, other)

    with pytest.raises(AnswerRequiredError):
        service.apply_to_org(org_id, applicant, {question_id: str(file_id)})


def test_file_from_another_org_is_dropped() -> None:
    media = FakeMedia()
    service, _, _, users, _, org_id, owner = _service("review", media=media)
    service.replace_membership_form(org_id, owner, [("Giấy xác nhận", "file", False, [], False)])
    applicant = _new_user(users, "a@example.com")
    question_id = str(service.list_membership_form(org_id)[0].question_id)
    file_id = media.add(uuid7(), applicant)

    service.apply_to_org(org_id, applicant, {question_id: str(file_id)})

    stored, _ = service.get_application(org_id, owner, applicant)
    assert json.loads(stored.answers) == {}


def test_chat_file_cannot_be_used_as_evidence() -> None:
    media = FakeMedia()
    service, _, _, users, _, org_id, owner = _service("review", media=media)
    service.replace_membership_form(org_id, owner, [("Giấy xác nhận", "file", False, [], False)])
    applicant = _new_user(users, "a@example.com")
    question_id = str(service.list_membership_form(org_id)[0].question_id)
    file_id = media.add(org_id, applicant, owner_type="chat")

    service.apply_to_org(org_id, applicant, {question_id: str(file_id)})

    stored, _ = service.get_application(org_id, owner, applicant)
    assert json.loads(stored.answers) == {}
