"""Pydantic DTOs for membership application forms and submissions."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

FormFieldType = Literal["text", "textarea", "choice", "consent", "file"]
MAX_OPTIONS = 20
MAX_OPTION_CHARS = 100


class MembershipQuestionBody(BaseModel):
    """One question the org asks applicants to answer."""

    label: str = Field(min_length=1, max_length=300)
    field_type: FormFieldType = "text"
    required: bool = False
    options: list[str] = Field(default_factory=list, max_length=MAX_OPTIONS)
    allow_other: bool = False

    @field_validator("label")
    @classmethod
    def _no_separator(cls, value: str) -> str:
        # Clients render "|" as a separator in shared form components.
        if "|" in value:
            raise ValueError("Label cannot contain '|'.")
        return value

    @model_validator(mode="after")
    def _check_options(self) -> "MembershipQuestionBody":
        # Only choice questions keep options and "Khác"; the rest drop whatever was sent.
        if self.field_type != "choice":
            self.options = []
            self.allow_other = False
            return self
        cleaned: list[str] = []
        for option in self.options:
            text = option.strip()
            if not text or len(text) > MAX_OPTION_CHARS or "|" in text:
                raise ValueError("Each option needs 1-100 characters and no '|'.")
            if text not in cleaned:
                cleaned.append(text)
        # "Khác" counts as one choice, so a question needs two choices in total.
        if len(cleaned) + (1 if self.allow_other else 0) < 2:
            raise ValueError("A choice question needs at least two choices.")
        self.options = cleaned
        return self


class MembershipFormBody(BaseModel):
    """Replace the whole membership form and its heading."""

    title: str = Field(default="", max_length=120)
    description: str = Field(default="", max_length=1000)
    questions: list[MembershipQuestionBody] = Field(
        default_factory=list, max_length=32
    )


class MembershipQuestion(BaseModel):
    """Question row as applicants and reviewers see it."""

    question_id: UUID
    label: str
    field_type: str
    required: bool
    options: list[str] = Field(default_factory=list)
    allow_other: bool = False


class MembershipFormResponse(BaseModel):
    """The org's current membership form, in display order."""

    title: str = ""
    description: str = ""
    questions: list[MembershipQuestion]


class ApplyRequest(BaseModel):
    """Applicant answers keyed by question_id; unknown keys are dropped."""

    answers: dict[str, str] = Field(default_factory=dict, max_length=32)


class ApplicationFile(BaseModel):
    """Evidence file an applicant attached, as the reviewer sees it."""

    media_id: UUID
    name: str
    mime: str
    size_bytes: int


class StagedFileResponse(ApplicationFile):
    """Result of uploading one evidence file, before the application is sent."""


class ApplicationAnswer(BaseModel):
    """One answered question on a submission."""

    question_id: UUID
    label: str
    answer: str = ""
    # True when the applicant typed their own answer under "Khác".
    is_other: bool = False
    file: ApplicationFile | None = None


class ApplicationResponse(BaseModel):
    """One applicant's submission, with the questions it answers."""

    user_id: UUID
    submitted_at: datetime
    answers: list[ApplicationAnswer]
