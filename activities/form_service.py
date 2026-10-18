"""Per-activity sign-up form management (registration_forms table)."""

from __future__ import annotations

from uuid import UUID

from activities.edge_interfaces import RegistrationFormStore
from activities.interfaces import ActivityEvents, ActivityStore
from core.exceptions import (
    ForbiddenError,
    InvalidRegistrationStateError,
    NotFoundError,
)
from core.ids import uuid7
from orgs.interfaces import OrgRepository
from rbac.interfaces import AccessControl

FIELD_TYPES = {"text", "textarea", "choice", "consent"}
PUBLIC_FORM_STATUSES = {"published", "ongoing"}


class FormService:
    """Managers edit the question list; applicants read it."""

    def __init__(
        self,
        activities: ActivityStore,
        forms: RegistrationFormStore,
        orgs: OrgRepository,
        access: AccessControl,
        events: ActivityEvents | None = None,
    ) -> None:
        self._activities = activities
        self._forms = forms
        self._orgs = orgs
        self._access = access
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

    def get_form(
        self, org_id: UUID, activity_id: UUID, viewer_id: UUID | None
    ):
        """Public while the activity accepts applications, else managers."""
        activity = self._activity(org_id, activity_id)
        if activity.status not in PUBLIC_FORM_STATUSES:
            if viewer_id is None or not self._is_manager(org_id, viewer_id):
                raise ForbiddenError(
                    "The sign-up form is only public while registration is open."
                )
        return self._forms.list_form(activity_id)

    def set_form(
        self,
        org_id: UUID,
        activity_id: UUID,
        actor_id: UUID,
        questions: list[tuple[str, str, bool]],
    ):
        """Replace the whole form; tuples are (label, field_type, required)."""
        if not self._is_manager(org_id, actor_id):
            self._access.record(
                org_id, actor_id, "form.update", "activity",
                str(activity_id), "denied",
            )
            raise ForbiddenError("Only org managers can edit the form.")
        self._activity(org_id, activity_id)
        if len(questions) > 32:
            raise InvalidRegistrationStateError("Too many form questions.")
        rows = []
        for label, field_type, required in questions:
            if field_type not in FIELD_TYPES:
                raise InvalidRegistrationStateError(
                    f"Unknown field type {field_type}."
                )
            if not label.strip():
                raise InvalidRegistrationStateError(
                    "Question label must not be empty."
                )
            rows.append((uuid7(), label.strip(), field_type, required))
        self._forms.replace_form(activity_id, rows)
        if self._events is not None:
            try:
                self._events.activity_changed(
                    org_id, "form_updated", activity_id, actor_id, ""
                )
            except Exception:  # noqa: BLE001 - realtime is best-effort
                pass
        return self._forms.list_form(activity_id)
