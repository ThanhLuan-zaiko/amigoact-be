"""cqlengine persistence for activity edges: skills, partners, staff."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from activities.edge_interfaces import (
    ActivityLinkStore,
    ActivityStaffStore,
    RegistrationFormStore,
)
from activities.model import (
    RegistrationForm,
    Activity,
    ActivityPartner,
    ActivitySkill,
    ActivityStaff,
    PartnerActivitiesByOrg,
)


class CqlActivityLinkStore(ActivityLinkStore):
    """Edge writes replace whole sets; reverse feeds stay in sync."""

    def set_skills(
        self, activity_id: UUID, edges: list[tuple[UUID, bool]]
    ) -> None:
        keep = {skill_id for skill_id, _ in edges}
        for row in self.list_skills(activity_id):
            if row.skill_id not in keep:
                ActivitySkill.objects(
                    activity_id=activity_id, skill_id=row.skill_id
                ).delete()
        for skill_id, is_required in edges:
            ActivitySkill(
                activity_id=activity_id,
                skill_id=skill_id,
                is_required=is_required,
            ).save()

    def list_skills(self, activity_id: UUID) -> list[ActivitySkill]:
        return list(ActivitySkill.objects(activity_id=activity_id).all())

    def set_partners(
        self,
        activity: Activity,
        edges: list[tuple[UUID, str, str | None]],
    ) -> None:
        keep = {org_id for org_id, _, _ in edges}
        for row in self.list_partners(activity.id):
            if row.org_id not in keep:
                ActivityPartner.objects(
                    activity_id=activity.id, org_id=row.org_id
                ).delete()
                PartnerActivitiesByOrg.objects(
                    org_id=row.org_id,
                    start_at=activity.start_at,
                    activity_id=activity.id,
                ).delete()
        for org_id, role, note in edges:
            ActivityPartner(
                activity_id=activity.id, org_id=org_id, role=role, note=note
            ).save()
            PartnerActivitiesByOrg(
                org_id=org_id,
                start_at=activity.start_at,
                activity_id=activity.id,
                title=activity.title,
                role=role,
            ).save()

    def list_partners(self, activity_id: UUID) -> list[ActivityPartner]:
        return list(ActivityPartner.objects(activity_id=activity_id).all())

    def list_partner_feed(
        self, org_id: UUID, limit: int = 50
    ) -> list[Activity]:
        feed = list(
            PartnerActivitiesByOrg.objects(org_id=org_id)
            .limit(limit)
            .all()
        )
        rows = {
            row.id: row
            for row in (
                Activity.objects(id=f.activity_id).first() for f in feed
            )
            if row is not None
        }
        return [rows[f.activity_id] for f in feed if f.activity_id in rows]


class CqlActivityStaffStore(ActivityStaffStore):
    """Assignment rows replace whole sets, like the other edges."""

    def set_staff(
        self,
        activity_id: UUID,
        rows: list[tuple[UUID, str]],
        assigned_by: UUID,
        now: datetime,
    ) -> None:
        keep = {user_id for user_id, _ in rows}
        for row in self.list_staff(activity_id):
            if row.user_id not in keep:
                ActivityStaff.objects(
                    activity_id=activity_id, user_id=row.user_id
                ).delete()
        for user_id, staff_role in rows:
            ActivityStaff(
                activity_id=activity_id,
                user_id=user_id,
                staff_role=staff_role,
                assigned_by=assigned_by,
                assigned_at=now,
            ).save()

    def list_staff(self, activity_id: UUID) -> list[ActivityStaff]:
        return list(ActivityStaff.objects(activity_id=activity_id).all())


class CqlRegistrationFormStore(RegistrationFormStore):
    """Form questions replace as a set; position comes from list order."""

    def list_form(self, activity_id: UUID) -> list[RegistrationForm]:
        return list(RegistrationForm.objects(activity_id=activity_id).all())

    def replace_form(
        self,
        activity_id: UUID,
        questions: list[tuple[UUID, str, str, bool]],
    ) -> None:
        for row in self.list_form(activity_id):
            RegistrationForm.objects(
                activity_id=activity_id,
                position=row.position,
                question_id=row.question_id,
            ).delete()
        for position, (question_id, label, field_type, required) in enumerate(
            questions
        ):
            RegistrationForm(
                activity_id=activity_id,
                position=position,
                question_id=question_id,
                label=label,
                field_type=field_type,
                required=required,
            ).save()
