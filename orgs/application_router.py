"""Membership application endpoints: form editing, apply, review, read-back."""

from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, Response, UploadFile, status
from fastapi.responses import FileResponse

from core.dependencies import (
    CurrentUser,
    get_current_user,
    get_media_store,
    get_member_service,
)
from core.exceptions import MediaTooLargeError, NotFoundError
from core.media import MediaStore
from orgs.application_schemas import (
    ApplicationAnswer,
    ApplicationFile,
    ApplicationResponse,
    ApplyRequest,
    MembershipFormBody,
    MembershipFormResponse,
    MembershipQuestion,
    StagedFileResponse,
)
from orgs.media_repository import CqlMediaRepository
from orgs.membership_files import MAX_EVIDENCE_BYTES, EvidenceFile, MembershipFiles
from orgs.member_schemas import MemberResponse
from orgs.member_service import MemberService
from orgs.members_router import _to_member

router = APIRouter(tags=["orgs"])


def _files(store: MediaStore) -> MembershipFiles:
    return MembershipFiles(CqlMediaRepository(), store)


def _answer_for(question, answers: dict, org_id: UUID, files: MembershipFiles) -> ApplicationAnswer:  # noqa: ANN001
    """One reviewer row; a file question carries the file's metadata, not its id."""
    raw = str(answers.get(str(question.question_id), ""))
    if question.field_type != "file":
        options = json.loads(question.options or "[]")
        is_other = (
            question.field_type == "choice"
            and bool(question.allow_other)
            and raw != ""
            and raw not in options
        )
        return ApplicationAnswer(
            question_id=question.question_id,
            label=question.label,
            answer=raw,
            is_other=is_other,
        )
    evidence: EvidenceFile | None = None
    try:
        evidence = files.describe(org_id, UUID(raw)) if raw else None
    except ValueError:
        evidence = None
    return ApplicationAnswer(
        question_id=question.question_id,
        label=question.label,
        file=None if evidence is None else ApplicationFile(
            media_id=evidence.media_id,
            name=evidence.name,
            mime=evidence.mime,
            size_bytes=evidence.size_bytes,
        ),
    )


def _form_response(rows, heading: tuple[str, str]) -> MembershipFormResponse:  # noqa: ANN001
    title, description = heading
    return MembershipFormResponse(
        title=title,
        description=description,
        questions=[
            MembershipQuestion(
                question_id=row.question_id,
                label=row.label,
                field_type=row.field_type,
                required=row.required,
                options=json.loads(row.options or "[]"),
                allow_other=bool(row.allow_other),
            )
            for row in rows
        ],
    )


@router.get(
    "/orgs/{org_id}/membership-form",
    response_model=MembershipFormResponse,
    status_code=status.HTTP_200_OK,
)
def get_membership_form(
    org_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: MemberService = Depends(get_member_service),
) -> MembershipFormResponse:
    """Questions an applicant answers; any signed-in viewer may read them."""
    return _form_response(
        service.list_membership_form(org_id),
        service.membership_form_heading(org_id),
    )


@router.put(
    "/orgs/{org_id}/membership-form",
    response_model=MembershipFormResponse,
    status_code=status.HTTP_200_OK,
)
def replace_membership_form(
    org_id: UUID,
    body: MembershipFormBody,
    current_user: CurrentUser = Depends(get_current_user),
    service: MemberService = Depends(get_member_service),
) -> MembershipFormResponse:
    """Managers replace the whole form; existing applications keep their answers."""
    rows = service.replace_membership_form(
        org_id,
        current_user.id,
        [(q.label, q.field_type, q.required, q.options, q.allow_other) for q in body.questions],
        title=body.title,
        description=body.description,
    )
    return _form_response(rows, service.membership_form_heading(org_id))


@router.post(
    "/orgs/{org_id}/members/apply",
    response_model=MemberResponse,
    status_code=status.HTTP_201_CREATED,
)
def apply_to_org(
    org_id: UUID,
    body: ApplyRequest,
    response: Response,
    current_user: CurrentUser = Depends(get_current_user),
    service: MemberService = Depends(get_member_service),
) -> MemberResponse:
    """Submit the form for review; the row becomes applied until a manager decides."""
    snapshot = service.apply_to_org(org_id, current_user.id, body.answers)
    response.headers["Location"] = f"/orgs/{org_id}/members/{current_user.id}"
    return _to_member(snapshot)


@router.post(
    "/orgs/{org_id}/membership-applications/files",
    response_model=StagedFileResponse,
    status_code=status.HTTP_201_CREATED,
)
def stage_evidence_file(
    org_id: UUID,
    file: UploadFile,
    current_user: CurrentUser = Depends(get_current_user),
    service: MemberService = Depends(get_member_service),
    store: MediaStore = Depends(get_media_store),
) -> StagedFileResponse:
    """Applicant uploads one evidence file; send its media_id as the answer."""
    service.check_can_stage_evidence(org_id, current_user.id)
    content = file.file.read(MAX_EVIDENCE_BYTES + 1)
    if len(content) > MAX_EVIDENCE_BYTES:
        raise MediaTooLargeError("File exceeds the size limit.")
    staged = _files(store).stage(
        org_id,
        current_user.id,
        file.filename or "evidence",
        file.content_type or "application/octet-stream",
        content,
    )
    return StagedFileResponse(
        media_id=staged.media_id,
        name=staged.name,
        mime=staged.mime,
        size_bytes=staged.size_bytes,
    )


@router.get(
    "/orgs/{org_id}/members/{user_id}/application",
    response_model=ApplicationResponse,
    status_code=status.HTTP_200_OK,
)
def read_application(
    org_id: UUID,
    user_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: MemberService = Depends(get_member_service),
    store: MediaStore = Depends(get_media_store),
) -> ApplicationResponse:
    """Reviewer reads one submission against the current form questions."""
    stored, questions = service.get_application(org_id, current_user.id, user_id)
    answers = json.loads(stored.answers or "{}")
    files = _files(store)
    return ApplicationResponse(
        user_id=stored.user_id,
        submitted_at=stored.submitted_at,
        answers=[
            _answer_for(question, answers, org_id, files)
            for question in questions
        ],
    )


@router.get("/orgs/{org_id}/members/{user_id}/application-files/{media_id}")
def download_application_file(
    org_id: UUID,
    user_id: UUID,
    media_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: MemberService = Depends(get_member_service),
    store: MediaStore = Depends(get_media_store),
) -> FileResponse:
    """Reviewer downloads one evidence file the submission actually references."""
    stored, _ = service.get_application(org_id, current_user.id, user_id)
    answers = json.loads(stored.answers or "{}")
    if str(media_id) not in {str(value) for value in answers.values()}:
        raise NotFoundError("File not found.")
    evidence, path = _files(store).open(org_id, media_id)
    return FileResponse(
        str(path),
        media_type=evidence.mime,
        filename=evidence.name,
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
    )


@router.post(
    "/orgs/{org_id}/members/{user_id}/approve",
    response_model=MemberResponse,
    status_code=status.HTTP_200_OK,
)
def approve_application(
    org_id: UUID,
    user_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: MemberService = Depends(get_member_service),
) -> MemberResponse:
    """Manager accepts a pending application: applied -> active."""
    snapshot = service.review_application(
        org_id, current_user.id, user_id, approve=True
    )
    return _to_member(snapshot)


@router.post(
    "/orgs/{org_id}/members/{user_id}/reject",
    response_model=MemberResponse,
    status_code=status.HTTP_200_OK,
)
def reject_application(
    org_id: UUID,
    user_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: MemberService = Depends(get_member_service),
) -> MemberResponse:
    """Manager declines a pending application: applied -> left, may re-apply."""
    snapshot = service.review_application(
        org_id, current_user.id, user_id, approve=False
    )
    return _to_member(snapshot)
