"""Pydantic DTOs for membership application forms and submissions."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

FormFieldType = Literal["text", "textarea", "choice", "consent"]


class MembershipQuestionBody(BaseModel):
    """One question the org asks applicants to answer."""

    label: str = Field(min_length=1, max_length=300)
    field_type: FormFieldType = "text"
    required: bool = False


class MembershipFormBody(BaseModel):
    """Replace the whole membership form."""

    questions: list[MembershipQuestionBody] = Field(
        default_factory=list, max_length=32
    )


class MembershipQuestion(BaseModel):
    """Question row as applicants and reviewers see it."""

    question_id: UUID
    label: str
    field_type: str
    required: bool


class MembershipFormResponse(BaseModel):
    """The org's current membership form, in display order."""

    questions: list[MembershipQuestion]


class ApplyRequest(BaseModel):
    """Applicant answers keyed by question_id; unknown keys are dropped."""

    answers: dict[str, str] = Field(default_factory=dict, max_length=32)


class ApplicationAnswer(BaseModel):
    """One answered question on a submission."""

    question_id: UUID
    label: str
    answer: str


class ApplicationResponse(BaseModel):
    """One applicant's submission, with the questions it answers."""

    user_id: UUID
    submitted_at: datetime
    answers: list[ApplicationAnswer]
