"""Manager view of one member's volunteer profile: skills and emergency contacts.

Personal data, so every read is gated on the org's member:view permission and
audited. Only active members (or the owner) can be looked up; anyone else is
reported as not found so the endpoint cannot be used to probe other users.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

from core.exceptions import MemberNotFoundError
from orgs.member_helpers import is_active_member, live_org

if TYPE_CHECKING:
    from profiles.model import EmergencyContact, StudentProfile
    from profiles.interfaces import ProfileStore


@dataclass(frozen=True)
class VolunteerSkillRow:
    """One skill the member declared, with its catalog name."""

    skill_id: UUID
    name: str
    level: int


@dataclass(frozen=True)
class VolunteerView:
    """A member's volunteer profile as an org manager may see it."""

    user_id: UUID
    profile: StudentProfile | None
    skills: list[VolunteerSkillRow] = field(default_factory=list)
    contacts: list[EmergencyContact] = field(default_factory=list)


class MemberVolunteerMixin:
    """Manager read of a member's volunteer profile; mixed into MemberService."""

    if TYPE_CHECKING:  # attributes supplied by MemberService
        _orgs: object
        _members: object
        _access: object
        _profiles: ProfileStore | None

        def _require_manager(  # noqa: ANN202
            self, org, actor_id: UUID, permission: str, action: str,
            target_id: UUID | None = None,
        ): ...

        def _audit(  # noqa: ANN202
            self, org_id: UUID, actor_id: UUID, action: str, target_id: UUID | None
        ): ...

    def volunteer_profile(
        self, org_id: UUID, user_id: UUID, actor_id: UUID
    ) -> VolunteerView:
        """Profile, skills and emergency contacts of one member of the org."""
        org = live_org(self._orgs, org_id)
        self._require_manager(
            org, actor_id, "member:view", "member.volunteer.view", user_id
        )
        is_member = user_id == org.owner_id or is_active_member(
            self._members, org.id, user_id
        )
        if self._profiles is None or not is_member:
            raise MemberNotFoundError("Member not found.")
        skills: list[VolunteerSkillRow] = []
        for edge in self._profiles.list_user_skills(user_id):
            skill = self._profiles.get_skill(edge.skill_id)
            if skill is None:
                continue
            skills.append(
                VolunteerSkillRow(
                    skill_id=edge.skill_id,
                    name=skill.name,
                    level=int(edge.level or 1),
                )
            )
        skills.sort(key=lambda row: row.name.lower())
        view = VolunteerView(
            user_id=user_id,
            profile=self._profiles.get_profile(user_id),
            skills=skills,
            contacts=self._profiles.list_contacts(user_id),
        )
        self._audit(org_id, actor_id, "member.volunteer.view", user_id)
        return view
