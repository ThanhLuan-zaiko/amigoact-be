"""Activity detail rules: skills, partners, staff, schedules, news."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from activities.interfaces import (
    ActivityLinkStore,
    ActivityStaffStore,
    ActivityStore,
    AnnouncementStore,
    ScheduleStore,
)
from activities.model import (
    Activity,
    ActivityAnnouncement,
    ActivitySchedule,
)
from core.exceptions import ForbiddenError, NotFoundError
from core.security import utcnow
from notifications.interfaces import NotificationPort
from orgs.interfaces import OrgRepository, UserDirectory
from profiles.interfaces import ProfileStore
from rbac.interfaces import AccessControl

_PUBLIC_STATUSES = {"published", "ongoing", "completed"}
_STAFF_ROLES = {"organizer", "supervisor", "supporter"}
_PARTNER_ROLES = {"co_organizer", "sponsor"}


@dataclass(frozen=True)
class SkillEdgeDetail:
    """Activity skill edge joined with the catalog name."""

    skill_id: UUID
    name: str
    slug: str
    is_required: bool


@dataclass(frozen=True)
class PartnerDetail:
    """Partner edge joined with the org name."""

    org_id: UUID
    name: str
    role: str
    note: str | None


@dataclass(frozen=True)
class StaffDetail:
    """Staff row joined with the user's display name."""

    user_id: UUID
    full_name: str
    staff_role: str
    assigned_at: datetime | None


@dataclass(frozen=True)
class ActivityDetail:
    """Everything the detail page renders in one request."""

    activity: Activity
    skills: list[SkillEdgeDetail]
    partners: list[PartnerDetail]
    staff: list[StaffDetail]
    schedules: list[ActivitySchedule]
    announcements: list[ActivityAnnouncement]


class ActivityDetailService:
    """Composes the detail surface; managers mutate each edge set."""

    def __init__(  # noqa: PLR0913  (six small stores, one aggregate)
        self,
        activities: ActivityStore,
        links: ActivityLinkStore,
        staff: ActivityStaffStore,
        schedules: ScheduleStore,
        announcements: AnnouncementStore,
        orgs: OrgRepository,
        users: UserDirectory,
        skills: ProfileStore,
        access: AccessControl,
        notifications: NotificationPort | None = None,
    ) -> None:
        self._activities = activities
        self._links = links
        self._staff = staff
        self._schedules = schedules
        self._announcements = announcements
        self._orgs = orgs
        self._users = users
        self._skills = skills
        self._access = access
        self._notifications = notifications

    def _manager(self, org_id: UUID, actor_id: UUID) -> None:
        org = self._orgs.get_by_id(org_id)
        if org is None:
            raise NotFoundError("Organization not found.")
        if getattr(org, "owner_id", None) != actor_id and not (
            self._access.has_permission(
                org_id, actor_id, "activity:manage"
            )
        ):
            raise ForbiddenError("Only org managers can do this.")

    def _org_activity(self, org_id: UUID, activity_id: UUID) -> Activity:
        row = self._activities.get(activity_id)
        if row is None or row.org_id != org_id:
            raise NotFoundError("Activity not found.")
        return row

    def _visible(
        self, org_id: UUID, activity_id: UUID, viewer_id: UUID | None
    ) -> Activity:
        row = self._org_activity(org_id, activity_id)
        if row.status not in _PUBLIC_STATUSES and (
            viewer_id is None
            or not self._orgs.is_member(org_id, viewer_id)
        ):
            raise NotFoundError("Activity not found.")
        return row

    def detail(
        self, org_id: UUID, activity_id: UUID, viewer_id: UUID | None
    ) -> ActivityDetail:
        """Full composed detail for the event page."""
        row = self._visible(org_id, activity_id, viewer_id)
        return ActivityDetail(
            activity=row,
            skills=self._skill_details(activity_id),
            partners=self._partner_details(activity_id),
            staff=self._staff_details(activity_id),
            schedules=self._schedules.list(activity_id),
            announcements=self._announcements.list(activity_id),
        )

    def _skill_details(self, activity_id: UUID) -> list[SkillEdgeDetail]:
        edges: list[SkillEdgeDetail] = []
        for row in self._links.list_skills(activity_id):
            skill = self._skills.get_skill(row.skill_id)
            if skill is None:
                continue
            edges.append(
                SkillEdgeDetail(
                    skill_id=row.skill_id,
                    name=skill.name,
                    slug=skill.slug,
                    is_required=bool(row.is_required),
                )
            )
        return sorted(edges, key=lambda e: e.name.lower())

    def _partner_details(self, activity_id: UUID) -> list[PartnerDetail]:
        rows: list[PartnerDetail] = []
        for edge in self._links.list_partners(activity_id):
            org = self._orgs.get_by_id(edge.org_id)
            rows.append(
                PartnerDetail(
                    org_id=edge.org_id,
                    name=getattr(org, "name", "T\u1ed5 ch\u1ee9c") if org else "?",
                    role=edge.role,
                    note=edge.note,
                )
            )
        return rows

    def _staff_details(self, activity_id: UUID) -> list[StaffDetail]:
        rows: list[StaffDetail] = []
        for edge in self._staff.list_staff(activity_id):
            brief = self._users.get_brief(edge.user_id)
            rows.append(
                StaffDetail(
                    user_id=edge.user_id,
                    full_name=(
                        brief.full_name if brief else "Th\u00e0nh vi\u00ean"
                    ),
                    staff_role=edge.staff_role,
                    assigned_at=edge.assigned_at,
                )
            )
        return rows

    def set_skills(
        self,
        org_id: UUID,
        activity_id: UUID,
        actor_id: UUID,
        edges: list[tuple[UUID, bool]],
    ) -> ActivityDetail:
        """Replace skill edges; every id must exist in the catalog."""
        self._manager(org_id, actor_id)
        self._org_activity(org_id, activity_id)
        seen: set[UUID] = set()
        for skill_id, _ in edges:
            if skill_id in seen:
                continue
            seen.add(skill_id)
            if self._skills.get_skill(skill_id) is None:
                raise NotFoundError("Skill does not exist.")
        self._links.set_skills(
            activity_id, [e for e in edges if e[0] in seen]
        )
        return self.detail(org_id, activity_id, actor_id)

    def set_partners(
        self,
        org_id: UUID,
        activity_id: UUID,
        actor_id: UUID,
        edges: list[tuple[UUID, str, str | None]],
    ) -> ActivityDetail:
        """Replace partner edges; partners must be live orgs."""
        self._manager(org_id, actor_id)
        activity = self._org_activity(org_id, activity_id)
        merged: dict[UUID, tuple[str, str | None]] = {}
        for partner_id, role, note in edges:
            if role not in _PARTNER_ROLES:
                raise ForbiddenError("Partner role is invalid.")
            partner = self._orgs.get_by_id(partner_id)
            if partner is None or getattr(partner, "deleted_at", None):
                raise NotFoundError("Partner organization not found.")
            merged[partner_id] = (role, note)
        self._links.set_partners(
            activity,
            [(pid, role, note) for pid, (role, note) in merged.items()],
        )
        return self.detail(org_id, activity_id, actor_id)

    def set_staff(
        self,
        org_id: UUID,
        activity_id: UUID,
        actor_id: UUID,
        rows: list[tuple[UUID, str]],
    ) -> ActivityDetail:
        """Replace staff; every member must belong to the org."""
        self._manager(org_id, actor_id)
        activity = self._org_activity(org_id, activity_id)
        merged: dict[UUID, str] = {}
        for user_id, staff_role in rows:
            if staff_role not in _STAFF_ROLES:
                raise ForbiddenError("Staff role is invalid.")
            if not self._orgs.is_member(org_id, user_id):
                raise ForbiddenError("Staff must be org members.")
            merged[user_id] = staff_role
        self._staff.set_staff(
            activity_id, list(merged.items()), actor_id, utcnow()
        )
        if self._notifications is not None:
            for user_id, staff_role in merged.items():
                self._notifications.notify(
                    user_id,
                    "staff",
                    "B\u1ea1n \u0111\u01b0\u1ee3c ph\u00e2n c\u00f4ng s\u1ef1 ki\u1ec7n",
                    f"Vai tr\u00f2 {staff_role} trong m\u1ed9t ho\u1ea1t \u0111\u1ed9ng m\u1edbi.",
                    f'{{"activity_id": "{activity_id}", '
                    f'"org_id": "{org_id}", '
                    f'"activity_slug": "{activity.slug}"}}',
                )
        return self.detail(org_id, activity_id, actor_id)

    def add_schedule(
        self,
        org_id: UUID,
        activity_id: UUID,
        actor_id: UUID,
        title: str,
        location: str | None,
        start_at: datetime | None,
        end_at: datetime | None,
    ) -> ActivityDetail:
        """Append one session to the activity."""
        self._manager(org_id, actor_id)
        self._org_activity(org_id, activity_id)
        from core.ids import uuid7

        self._schedules.create(
            uuid7(), activity_id, title, location, start_at, end_at,
            utcnow(),
        )
        return self.detail(org_id, activity_id, actor_id)

    def delete_schedule(
        self,
        org_id: UUID,
        activity_id: UUID,
        schedule_id: UUID,
        actor_id: UUID,
    ) -> ActivityDetail:
        """Remove one session from the activity."""
        self._manager(org_id, actor_id)
        if not self._schedules.delete(activity_id, schedule_id):
            raise NotFoundError("Schedule not found.")
        return self.detail(org_id, activity_id, actor_id)

    def add_announcement(
        self,
        org_id: UUID,
        activity_id: UUID,
        actor_id: UUID,
        title: str,
        body: str,
    ) -> ActivityDetail:
        """Post one item onto the activity news board."""
        self._manager(org_id, actor_id)
        self._org_activity(org_id, activity_id)
        from core.ids import uuid7

        self._announcements.create(
            activity_id, uuid7(), title, body, actor_id, utcnow()
        )
        return self.detail(org_id, activity_id, actor_id)

    def partner_feed(self, org_id: UUID) -> list[Activity]:
        """Activities the org partners on (public surface)."""
        if self._orgs.get_by_id(org_id) is None:
            raise NotFoundError("Organization not found.")
        return self._links.list_partner_feed(org_id)
