"""Waitlist transitions and slot-scoped promotion for registrations."""

from __future__ import annotations

from uuid import UUID

from core.security import utcnow


class WaitlistMixin:
    """Promotes the oldest waiter when capacity frees on a slot/activity."""

    def _mark_waitlist(
        self,
        activity_id: UUID,
        student_id: UUID,
        slot_id: UUID | None,
        status: str,
        promoted_at,
    ) -> None:
        """Flip the student's waiting entry, if one exists."""
        for entry in self._registrations.list_waitlist(
            activity_id, "waiting"
        ):
            if entry.student_id == student_id and (
                slot_id is None or entry.slot_id == slot_id
            ):
                self._registrations.mark_waitlist(
                    activity_id, entry.joined_at, entry.waitlist_id,
                    status, promoted_at,
                )

    def _promote_next(
        self, activity: object, slot_id: UUID, actor_id: UUID
    ) -> None:
        """A freed slot approves the oldest waitlisted applicant on it."""
        slot = (
            next(
                (
                    s
                    for s in self._slots.list_for_activity(activity.id)
                    if s.slot_id == slot_id
                ),
                None,
            )
            if self._slots is not None and slot_id != UUID(int=0)
            else None
        )
        capacity = (
            getattr(slot, "capacity", None)
            if slot is not None
            else getattr(activity, "max_participants", None)
        )
        if capacity is None or (
            self._registrations.count_active(
                activity.id,
                slot_id if slot is not None else None,
            )
            >= capacity
        ):
            return
        now = utcnow()
        for entry in self._registrations.list_waitlist(
            activity.id, "waiting"
        ):
            if entry.slot_id != slot_id:
                continue
            guard = self._registrations.get_for_student(
                activity.id, entry.student_id, entry.slot_id
            )
            row = (
                self._registrations.get(guard.registration_id)
                if guard is not None
                else None
            )
            if row is None or row.status != "waitlisted":
                self._registrations.mark_waitlist(
                    activity.id, entry.joined_at, entry.waitlist_id,
                    "expired", None,
                )
                continue
            self._registrations.set_status(
                row.registration_id, "approved", None,
                "promoted from waitlist", now,
            )
            self._registrations.mark_waitlist(
                activity.id, entry.joined_at, entry.waitlist_id,
                "promoted", now,
            )
            self._registrations.record_history(
                row.registration_id, "waitlisted", "approved", actor_id,
                "promoted from waitlist", now,
            )
            self._notify(
                row.student_id,
                "\u0110\u0103ng k\xfd \u0111\u01b0\u1ee3c duy\u1ec7t",
                f"\u0110\u01a1n tham gia {activity.title} \u0111\u01b0\u1ee3c duy\u1ec7t t\u1eeb danh s\xe1ch ch\u1edd.",
                {
                    "activity_id": str(activity.id),
                    "org_id": str(activity.org_id),
                    "activity_slug": activity.slug,
                },
            )
            return
