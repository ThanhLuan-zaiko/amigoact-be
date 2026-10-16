"""cqlengine persistence for the profiles bounded context."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from profiles.interfaces import ProfileStore
from profiles.model import (
    EmergencyContact,
    Skill,
    StudentProfile,
    StudentProfileByCode,
    UserBySkill,
    UserSkill,
)


class CqlProfileStore(ProfileStore):
    """Model-backed store; the service never sees cqlengine objects."""

    def get_profile(self, user_id: UUID) -> StudentProfile | None:
        return StudentProfile.objects(user_id=user_id).first()

    def upsert_profile(
        self,
        user_id: UUID,
        student_code: str | None,
        campus_id: UUID | None,
        department_id: UUID | None,
        class_name: str | None,
        enrollment_year: int | None,
        school_name: str | None,
        bio: str | None,
        interests: set[str],
        status: str | None,
        now: datetime,
    ) -> StudentProfile:
        old = self.get_profile(user_id)
        if old is None:
            row = StudentProfile(
                user_id=user_id,
                student_code=student_code,
                campus_id=campus_id,
                department_id=department_id,
                class_name=class_name,
                enrollment_year=enrollment_year,
                school_name=school_name,
                bio=bio,
                interests=interests,
                status=status or "studying",
                total_hours=0.0,
                updated_at=now,
            )
            row.save()
        else:
            old_code = getattr(old, "student_code", None)
            old_campus = getattr(old, "campus_id", None)
            if old_code and old_campus and (
                old_code != student_code or old_campus != campus_id
            ):
                StudentProfileByCode.objects(
                    campus_id=old_campus, student_code=old_code
                ).delete()
            StudentProfile.objects(user_id=user_id).update(
                student_code=student_code,
                campus_id=campus_id,
                department_id=department_id,
                class_name=class_name,
                enrollment_year=enrollment_year,
                school_name=school_name,
                bio=bio,
                interests=interests,
                status=status,
                updated_at=now,
            )
        if student_code and campus_id:
            StudentProfileByCode.create(
                campus_id=campus_id,
                student_code=student_code,
                user_id=user_id,
            )
        return StudentProfile.objects(user_id=user_id).first()

    def lookup_code(
        self, campus_id: UUID, student_code: str
    ) -> StudentProfileByCode | None:
        return StudentProfileByCode.objects(
            campus_id=campus_id, student_code=student_code
        ).first()

    def list_contacts(self, user_id: UUID) -> list[EmergencyContact]:
        return list(EmergencyContact.objects(user_id=user_id).all())

    def put_contact(
        self,
        user_id: UUID,
        contact_id: UUID,
        name: str,
        relation: str | None,
        phone: str,
        is_primary: bool,
    ) -> EmergencyContact:
        row = EmergencyContact(
            user_id=user_id,
            contact_id=contact_id,
            name=name,
            relation=relation,
            phone=phone,
            is_primary=is_primary,
        )
        row.save()
        return row

    def delete_contact(self, user_id: UUID, contact_id: UUID) -> bool:
        if (
            EmergencyContact.objects(
                user_id=user_id, contact_id=contact_id
            ).first()
            is None
        ):
            return False
        EmergencyContact.objects(
            user_id=user_id, contact_id=contact_id
        ).delete()
        return True

    def clear_primary_contacts(self, user_id: UUID, keep: UUID | None) -> None:
        for row in self.list_contacts(user_id):
            if row.contact_id != keep and row.is_primary:
                EmergencyContact.objects(
                    user_id=user_id, contact_id=row.contact_id
                ).update(is_primary=False)

    def list_skills(self) -> list[Skill]:
        return sorted(Skill.objects.all(), key=lambda s: (s.name or "").lower())

    def get_skill(self, skill_id: UUID) -> Skill | None:
        return Skill.objects(id=skill_id).first()

    def list_user_skills(self, user_id: UUID) -> list[UserSkill]:
        return list(UserSkill.objects(user_id=user_id).all())

    def list_users_by_skill(
        self, skill_id: UUID, limit: int = 200
    ) -> list[UserBySkill]:
        return list(
            UserBySkill.objects(skill_id=skill_id).limit(limit)
        )

    def replace_user_skills(
        self, user_id: UUID, edges: list[tuple[UUID, int]]
    ) -> None:
        keep = {skill_id for skill_id, _ in edges}
        for row in self.list_user_skills(user_id):
            if row.skill_id not in keep:
                UserSkill.objects(
                    user_id=user_id, skill_id=row.skill_id
                ).delete()
                UserBySkill.objects(
                    skill_id=row.skill_id, user_id=user_id
                ).delete()
        for skill_id, level in edges:
            UserSkill(
                user_id=user_id, skill_id=skill_id, level=level
            ).save()
            UserBySkill(
                skill_id=skill_id, user_id=user_id, level=level
            ).save()
