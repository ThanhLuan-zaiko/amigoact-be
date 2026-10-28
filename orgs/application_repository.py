"""cqlengine persistence for membership application forms and answers."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from orgs.application_interfaces import ApplicationStore, MembershipFormStore
from orgs.model import (
    MembershipApplication,
    MembershipForm,
    MembershipFormSettings,
)


class CqlMembershipFormStore(MembershipFormStore):
    """Questions partitioned by org, clustered by display position."""

    def list_form(self, org_id: UUID) -> list[MembershipForm]:
        return list(MembershipForm.objects(org_id=org_id).all())

    def replace_form(
        self, org_id: UUID, rows: list[tuple[UUID, str, str, bool, str, bool]]
    ) -> None:
        # Full-key deletes: each row is removed by its complete primary key.
        for old in self.list_form(org_id):
            old.delete()
        for position, (question_id, label, field_type, required, options, allow_other) in enumerate(rows):
            MembershipForm.create(
                org_id=org_id,
                position=position,
                question_id=question_id,
                label=label,
                field_type=field_type,
                required=required,
                options=options,
                allow_other=allow_other,
            )

    def get_settings(self, org_id: UUID) -> MembershipFormSettings | None:
        return MembershipFormSettings.objects(org_id=org_id).first()

    def put_settings(self, org_id: UUID, title: str, description: str) -> None:
        MembershipFormSettings.create(
            org_id=org_id, title=title, description=description
        )


class CqlApplicationStore(ApplicationStore):
    """One submission per (org, user); a new apply overwrites the old one."""

    def get(self, org_id: UUID, user_id: UUID) -> MembershipApplication | None:
        return MembershipApplication.objects(
            org_id=org_id, user_id=user_id
        ).first()

    def put(
        self, org_id: UUID, user_id: UUID, answers: str, now: datetime
    ) -> None:
        # rejected_at=None writes a tombstone: an old rejection never outlives a new submission.
        MembershipApplication.create(
            org_id=org_id,
            user_id=user_id,
            answers=answers,
            submitted_at=now,
            rejected_at=None,
        )

    def mark_rejected(self, org_id: UUID, user_id: UUID, now: datetime) -> None:
        MembershipApplication.objects(org_id=org_id, user_id=user_id).update(
            rejected_at=now
        )
