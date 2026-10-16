"""Coordinator matching extracted from MemberService: find members by skill."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from orgs.member_helpers import live_org
from orgs.member_listing import SkillMatch

if TYPE_CHECKING:
    from orgs.interfaces import (
        MemberRepository,
        OrgRepository,
        UserDirectory,
    )
    from profiles.interfaces import ProfileStore
    from rbac.interfaces import AccessControl


class MemberMatchingMixin:
    """Skill-based member suggestions; mixed into MemberService."""

    if TYPE_CHECKING:  # attributes supplied by MemberService
        _orgs: OrgRepository
        _members: MemberRepository
        _users: UserDirectory
        _access: AccessControl
        _profiles: ProfileStore | None

        def _require_manager(  # noqa: ANN202
            self, org, actor_id: UUID, permission: str, action: str
        ): ...

        def _audit(  # noqa: ANN202
            self, org_id: UUID, actor_id: UUID, action: str, target: str | None
        ): ...

    def match_by_skill(
        self,
        org_id: UUID,
        skill_id: UUID,
        actor_id: UUID,
        min_level: int = 1,
    ) -> list[SkillMatch]:
        """Coordinator matching: org members holding one skill, best first."""
        org = live_org(self._orgs, org_id)
        self._require_manager(
            org, actor_id, "member:view", "member.match"
        )
        if self._profiles is None:
            return []
        member_ids = {
            row.user_id
            for row in self._members.list_by_org(org_id)
            if getattr(row, "status", "active") == "active"
        }
        member_ids.add(org.owner_id)
        matches: list[SkillMatch] = []
        for edge in self._profiles.list_users_by_skill(skill_id):
            if edge.user_id not in member_ids:
                continue
            if int(getattr(edge, "level", 1) or 1) < min_level:
                continue
            brief = self._users.get_brief(edge.user_id)
            if brief is None or getattr(brief, "status", "active") != "active":
                continue
            matches.append(
                SkillMatch(
                    user_id=edge.user_id,
                    full_name=brief.full_name,
                    level=int(edge.level or 1),
                )
            )
        matches.sort(key=lambda m: (-m.level, m.full_name.lower()))
        self._audit(org_id, actor_id, "member.match", None)
        return matches
