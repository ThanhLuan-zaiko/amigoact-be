"""Membership application errors (split from exceptions.py to keep it under cap)."""

from __future__ import annotations

from core.exceptions import DomainError


class ApplicationNotOpenError(DomainError):
    """The org does not take applications; it is invite-only or open."""

    code = "NOT_ACCEPTING_APPLICATIONS"
    status = 403


class ApplicationRequiredError(DomainError):
    """The org reviews applications; joining must go through one."""

    code = "APPLICATION_REQUIRED"
    status = 403


class AlreadyAppliedError(DomainError):
    """A pending application already exists for this user."""

    code = "ALREADY_APPLIED"
    status = 409


class InvitePendingError(DomainError):
    """The user holds a pending invitation; answering it comes first."""

    code = "INVITE_PENDING"
    status = 409


class AnswerRequiredError(DomainError):
    """A required membership form question was left blank."""

    code = "ANSWER_REQUIRED"
    status = 400


class ApplicationCooldownError(DomainError):
    """The applicant was rejected recently and must wait before applying again."""

    code = "APPLICATION_COOLDOWN"
    status = 409
