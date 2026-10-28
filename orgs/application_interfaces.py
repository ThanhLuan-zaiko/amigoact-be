"""Ports for membership application forms and submitted answers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from orgs.model import MembershipApplication, MembershipForm


class MembershipFormStore(ABC):
    """Question list an org asks applicants to answer."""

    @abstractmethod
    def list_form(self, org_id: UUID) -> list[MembershipForm]:
        """Questions in display order."""

    @abstractmethod
    def replace_form(
        self, org_id: UUID, rows: list[tuple[UUID, str, str, bool]]
    ) -> None:
        """Replace the whole list; rows are (question_id, label, type, required)."""


class ApplicationStore(ABC):
    """Answers an applicant submitted, one row per (org, user)."""

    @abstractmethod
    def get(self, org_id: UUID, user_id: UUID) -> MembershipApplication | None:
        """The applicant's latest submission, if any."""

    @abstractmethod
    def put(
        self, org_id: UUID, user_id: UUID, answers: str, now: datetime
    ) -> None:
        """Upsert the answers JSON; re-applying overwrites the old submission."""

    @abstractmethod
    def mark_rejected(self, org_id: UUID, user_id: UUID, now: datetime) -> None:
        """Stamp the rejection time that the re-apply cooldown reads."""
