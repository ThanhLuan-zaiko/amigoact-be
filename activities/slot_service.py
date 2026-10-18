"""Per-schedule capacity slots (activity_slots table)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from activities.edge_interfaces import ScheduleStore, SlotStore
from activities.interfaces import ActivityEvents, ActivityStore
from core.exceptions import (
    ForbiddenError,
    InvalidRegistrationStateError,
    NotFoundError,
)
from core.ids import uuid7
from orgs.interfaces import OrgRepository
from rbac.interfaces import AccessControl
from registrations.interfaces import RegistrationStore

PUBLIC_SLOT_STATUSES = {"published", "ongoing"}


class SlotService:
    """Managers edit slots; applicants read them while applying."""

    def __init__(
        self,
        activities: ActivityStore,
        schedules: ScheduleStore,
        slots: SlotStore,
        orgs: OrgRepository,
        access: AccessControl,
        registrations: RegistrationStore | None = None,
        events: ActivityEvents | None = None,
    ) -> None:
        self._activities = activities
        self._schedules = schedules
        self._slots = slots
        self._orgs = orgs
        self._access = access
        self._registrations = registrations
        self._events = events

    def _is_manager(self, org_id: UUID, actor_id: UUID) -> bool:
        org = self._orgs.get_by_id(org_id)
        if org is None or getattr(org, "deleted_at", None) is not None:
            raise NotFoundError("Organization not found.")
        return org.owner_id == actor_id or self._access.has_permission(
            org_id, actor_id, "activity:manage"
        )

    def _activity(self, org_id: UUID, activity_id: UUID):
        row = self._activities.get(activity_id)
        if (
            row is None
            or row.org_id != org_id
            or row.deleted_at is not None
        ):
            raise NotFoundError("Activity not found.")
        return row

    def _emit(self, org_id: UUID, action: str, activity_id: UUID, actor_id: UUID) -> None:
        if self._events is not None:
            try:
                self._events.activity_changed(
                    org_id, action, activity_id, actor_id, ""
                )
            except Exception:  # noqa: BLE001 - realtime is best-effort
                pass

    def list_for_activity(
        self, org_id: UUID, activity_id: UUID, viewer_id: UUID | None
    ):
        """Slots plus live counts; public while registration is open."""
        activity = self._activity(org_id, activity_id)
        if activity.status not in PUBLIC_SLOT_STATUSES and (
            viewer_id is None or not self._is_manager(org_id, viewer_id)
        ):
            raise ForbiddenError(
                "Slots are only public while registration is open."
            )
        counts: dict[UUID, int] = {}
        if self._registrations is not None:
            for reg in self._registrations.list_by_activity(activity_id):
                if reg.status in ("approved", "attended"):
                    counts[reg.slot_id] = counts.get(reg.slot_id, 0) + 1
        rows = []
        for slot in self._slots.list_for_activity(activity_id):
            slot.registered = counts.get(slot.slot_id, 0)
            rows.append(slot)
        return rows

    def create_slot(
        self,
        org_id: UUID,
        activity_id: UUID,
        schedule_id: UUID,
        actor_id: UUID,
        title: str,
        capacity: int | None,
        start_at: datetime | None,
        end_at: datetime | None,
    ):
        if not self._is_manager(org_id, actor_id):
            self._access.record(
                org_id, actor_id, "slot.create", "activity",
                str(activity_id), "denied",
            )
            raise ForbiddenError("Only org managers can add slots.")
        self._activity(org_id, activity_id)
        schedule = next(
            (
                s
                for s in self._schedules.list(activity_id)
                if s.id == schedule_id
            ),
            None,
        )
        if schedule is None:
            raise NotFoundError("Schedule not found.")
        row = self._slots.create(
            uuid7(), schedule_id, title.strip(), capacity, start_at, end_at
        )
        self._emit(org_id, "slot_created", activity_id, actor_id)
        return row

    def delete_slot(
        self,
        org_id: UUID,
        activity_id: UUID,
        schedule_id: UUID,
        slot_id: UUID,
        actor_id: UUID,
    ) -> None:
        if not self._is_manager(org_id, actor_id):
            self._access.record(
                org_id, actor_id, "slot.delete", "activity",
                str(activity_id), "denied",
            )
            raise ForbiddenError("Only org managers can remove slots.")
        self._activity(org_id, activity_id)
        if self._registrations is not None:
            for reg in self._registrations.list_by_activity(activity_id):
                if reg.slot_id == slot_id and reg.status not in (
                    "cancelled",
                    "rejected",
                ):
                    raise InvalidRegistrationStateError(
                        "Slot still has live registrations."
                    )
        if not self._slots.delete(schedule_id, slot_id):
            raise NotFoundError("Slot not found.")
        self._emit(org_id, "slot_deleted", activity_id, actor_id)
