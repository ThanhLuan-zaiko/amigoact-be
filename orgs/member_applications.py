"""Membership applications: applicants answer the org form, managers decide.

Lifecycle: none/left -> applied (apply) -> active (approve) or left (reject).
The applicant withdraws through the existing self-leave, which lands on left.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from uuid import UUID

from core.exceptions import (
    AlreadyMemberError,
    InvalidMemberStateError,
    MemberNotFoundError,
    TooManyRequestsError,
)
from core.exceptions_applications import (
    AlreadyAppliedError,
    AnswerRequiredError,
    ApplicationCooldownError,
    ApplicationNotOpenError,
    InvitePendingError,
)
from core.ids import uuid7
from core.security import utcnow
from orgs.member_helpers import live_org, member_snapshot
from orgs.membership_files import is_attached
from orgs.member_listing import MemberSnapshot

if TYPE_CHECKING:
    from notifications.interfaces import NotificationPort
    from orgs.application_interfaces import ApplicationStore, MembershipFormStore
    from orgs.interfaces import (
        MediaRepository,
        MemberRepository,
        OrgRepository,
        UserDirectory,
    )
    from auth.interfaces import RateLimiter
    from orgs.model import MembershipApplication, MembershipForm, Organization
    from rbac.interfaces import AccessControl

FIELD_TYPES = ("text", "textarea", "choice", "consent", "file")


def _valid_choice(question, text: str) -> bool:  # noqa: ANN001
    """An option from the list, or any non-empty text when the question allows "Khác"."""
    if text in json.loads(question.options or "[]"):
        return True
    return bool(text) and bool(getattr(question, "allow_other", False))
MAX_ANSWER_CHARS = 2000
# Open orgs admit instantly; invite and review orgs both take applications.
APPLY_POLICIES = ("invite", "review")
# A rejected applicant waits this long before applying again; a withdrawal does not.
APPLY_COOLDOWN = timedelta(days=7)
# Per applicant: refused attempts count too, so a retry loop hits the same wall.
APPLY_WINDOW_SECONDS = 3600
APPLY_MAX_ATTEMPTS = 5
# Owners get at most one "new application" ping per window; the roster stays live.
NOTIFY_WINDOW_SECONDS = 900


class MemberApplicationsMixin:
    """Form editing, apply, review and read-back; mixed into MemberService."""

    if TYPE_CHECKING:  # attributes supplied by MemberService
        _orgs: OrgRepository
        _members: MemberRepository
        _users: UserDirectory
        _access: AccessControl
        _notifications: NotificationPort | None
        _forms: MembershipFormStore
        _applications: ApplicationStore
        _limiter: RateLimiter | None
        _media: MediaRepository | None

        def _require_manager(
            self, org: Organization, actor_id: UUID, permission: str,
            action: str, target_id: UUID | None = None,
        ) -> str: ...
        def _audit(
            self, org_id: UUID, actor_id: UUID, action: str,
            target_id: UUID | None,
        ) -> None: ...
        def _emit(
            self, org_id: UUID, action: str, target_id: UUID,
            actor_id: UUID, *, notify: UUID | None = None,
            detail: str | None = None,
        ) -> None: ...

    def list_membership_form(self, org_id: UUID) -> list[MembershipForm]:
        """Questions an applicant answers, in display order."""
        live_org(self._orgs, org_id)
        return self._forms.list_form(org_id)

    def replace_membership_form(
        self,
        org_id: UUID,
        actor_id: UUID,
        questions: list[tuple[str, str, bool, list[str], bool]],
        title: str = "",
        description: str = "",
    ) -> list[MembershipForm]:
        """Managers replace the whole form; tuples are (label, type, required, options, allow_other)."""
        org = live_org(self._orgs, org_id)
        self._require_manager(org, actor_id, "member:invite", "member.form")
        rows = []
        for label, field_type, required, options, allow_other in questions:
            if field_type not in FIELD_TYPES:
                raise ValueError(f"Unknown field type {field_type}.")
            is_choice = field_type == "choice"
            kept = options if is_choice else []
            rows.append(
                (uuid7(), label.strip(), field_type, required, json.dumps(kept), is_choice and allow_other)
            )
        self._forms.replace_form(org_id, rows)
        self._forms.put_settings(org_id, title.strip(), description.strip())
        self._audit(org_id, actor_id, "member.form", None)
        return self._forms.list_form(org_id)

    def check_can_stage_evidence(self, org_id: UUID, user_id: UUID) -> None:
        """Only applicants to a review or invite org may stage evidence files."""
        org = live_org(self._orgs, org_id)
        if (getattr(org, "join_policy", None) or "invite") not in APPLY_POLICIES:
            raise ApplicationNotOpenError("This org does not take applications.")
        if user_id == org.owner_id:
            raise AlreadyMemberError("The owner is already a member.")
        row = self._members.get(org_id, user_id)
        state = None if row is None else (getattr(row, "status", "active") or "active")
        if state in ("active", "suspended"):
            raise AlreadyMemberError("This user is already a member.")

    def membership_form_heading(self, org_id: UUID) -> tuple[str, str]:
        """Title and description shown above the questions; blank when unset."""
        live_org(self._orgs, org_id)
        stored = self._forms.get_settings(org_id)
        if stored is None:
            return "", ""
        return stored.title or "", stored.description or ""

    def apply_to_org(
        self, org_id: UUID, user_id: UUID, answers: dict[str, str]
    ) -> MemberSnapshot:
        """Applicant submits the form: nothing or left -> applied."""
        org = live_org(self._orgs, org_id)
        if (getattr(org, "join_policy", None) or "invite") not in APPLY_POLICIES:
            raise ApplicationNotOpenError("This org does not take applications.")
        if user_id == org.owner_id:
            raise AlreadyMemberError("The owner is already a member.")
        self._throttle_attempts(user_id)
        now = utcnow()
        row = self._members.get(org_id, user_id)
        state = None if row is None else (getattr(row, "status", "active") or "active")
        if state in ("active", "suspended"):
            raise AlreadyMemberError("This user is already a member.")
        if state == "applied":
            raise AlreadyAppliedError("An application is already pending.")
        if state == "invited":
            raise InvitePendingError("Answer the pending invitation first.")
        if state == "left":
            self._check_cooldown(org_id, user_id, now)
        # Answers first: a visible "applied" row always has its submission.
        self._applications.put(
            org_id, user_id, self._answers_json(org_id, user_id, answers), now
        )
        if row is None:
            self._members.put(org_id, user_id, "applied", now)
        else:
            self._members.set_status(org_id, user_id, "applied", now)
        self._audit(org_id, user_id, "member.apply", user_id)
        self._emit(org_id, "applied", user_id, user_id)
        self._notify_owner(org)
        return self._snapshot(org, user_id)

    def review_application(
        self, org_id: UUID, actor_id: UUID, user_id: UUID, approve: bool
    ) -> MemberSnapshot:
        """Manager verdict: applied -> active (approve) or left (reject)."""
        org = live_org(self._orgs, org_id)
        self._require_manager(
            org, actor_id, "member:invite", "member.review", user_id
        )
        row = self._members.get(org_id, user_id)
        if row is None or getattr(row, "status", "active") != "applied":
            raise InvalidMemberStateError("No pending application found.")
        now = utcnow()
        if not approve:
            # Stamp before the status flips: a rejected row without its cooldown would allow an instant retry.
            self._applications.mark_rejected(org_id, user_id, now)
        self._members.set_status(
            org_id, user_id, "active" if approve else "left", now
        )
        action = "member.approve" if approve else "member.reject"
        self._audit(org_id, actor_id, action, user_id)
        self._emit(
            org_id, "approved" if approve else "rejected",
            user_id, actor_id, notify=user_id,
        )
        self._notify_applicant(org, user_id, approve)
        return self._snapshot(org, user_id)

    def get_application(
        self, org_id: UUID, actor_id: UUID, user_id: UUID
    ) -> tuple[MembershipApplication, list[MembershipForm]]:
        """Reviewer reads one submission together with the questions it answers."""
        org = live_org(self._orgs, org_id)
        self._require_manager(
            org, actor_id, "member:invite", "member.application", user_id
        )
        stored = self._applications.get(org_id, user_id)
        if stored is None:
            raise MemberNotFoundError("Application not found.")
        return stored, self._forms.list_form(org_id)

    def _throttle_attempts(self, user_id: UUID) -> None:
        """Cap apply attempts per applicant per window; refused attempts count."""
        if self._limiter is None:
            return
        hits = self._limiter.hit(f"membership_apply:{user_id}", APPLY_WINDOW_SECONDS)
        if hits > APPLY_MAX_ATTEMPTS:
            raise TooManyRequestsError("Too many applications. Try again later.")

    def _check_cooldown(self, org_id: UUID, user_id: UUID, now: datetime) -> None:
        """Block a re-apply for APPLY_COOLDOWN after a manager's rejection."""
        stored = self._applications.get(org_id, user_id)
        rejected_at = None if stored is None else stored.rejected_at
        if rejected_at is None:
            return
        if rejected_at.tzinfo is None:
            rejected_at = rejected_at.replace(tzinfo=timezone.utc)
        if now - rejected_at < APPLY_COOLDOWN:
            raise ApplicationCooldownError("Wait for the cooldown after a rejection.")

    def _own_evidence(self, org_id: UUID, user_id: UUID, text: str) -> bool:
        """True when `text` is a media id of an evidence file this user staged for the org."""
        if self._media is None:
            return False
        try:
            media_id = UUID(text)
        except ValueError:
            return False
        return is_attached(self._media.get_asset(media_id), org_id, user_id)

    def _answers_json(self, org_id: UUID, user_id: UUID, answers: dict[str, str]) -> str:
        """Keep only known questions, enforce required ones, cap each answer."""
        questions = self._forms.list_form(org_id)
        known = {str(q.question_id): q for q in questions}
        clean = {}
        for key, value in answers.items():
            question = known.get(key)
            if question is None:
                continue
            text = str(value).strip()[:MAX_ANSWER_CHARS]
            # A choice answer must be an offered option, or free text when "Khác" is allowed.
            if question.field_type == "choice" and not _valid_choice(question, text):
                continue
            # A file answer must name an evidence file this applicant staged for this org.
            if question.field_type == "file" and not self._own_evidence(org_id, user_id, text):
                continue
            clean[key] = text
        for question in questions:
            if question.required and not clean.get(str(question.question_id)):
                raise AnswerRequiredError("A required answer is missing.")
        return json.dumps(clean)

    def _snapshot(self, org: Organization, user_id: UUID) -> MemberSnapshot:
        fresh = self._members.get(org.id, user_id)
        assert fresh is not None
        return member_snapshot(
            self._users,
            org,
            fresh,
            self._access.role_map(org.id),
            show_email=True,
            media=self._media,
        )

    def _notify_owner(self, org: Organization) -> None:
        if self._notifications is None:
            return
        if self._limiter is not None:
            hits = self._limiter.hit(f"membership_notify:{org.id}", NOTIFY_WINDOW_SECONDS)
            if hits > 1:
                return
        try:
            self._notifications.notify(
                org.owner_id,
                "membership",
                f"H\u1ed3 s\u01a1 m\u1edbi v\u00e0o {org.name}",
                "C\u00f3 ng\u01b0\u1eddi v\u1eeba n\u1ed9p h\u1ed3 s\u01a1 t\u00ecnh nguy\u1ec7n. M\u1edf danh s\u00e1ch th\u00e0nh vi\u00ean \u0111\u1ec3 duy\u1ec7t.",
                f'{{"org_id": "{org.id}", "org_slug": "{org.slug}"}}',
            )
        except Exception:  # noqa: BLE001 - notifications are best-effort
            pass

    def _notify_applicant(
        self, org: Organization, user_id: UUID, approve: bool
    ) -> None:
        if self._notifications is None:
            return
        if approve:
            title = f"H\u1ed3 s\u01a1 v\u00e0o {org.name} \u0111\u00e3 \u0111\u01b0\u1ee3c duy\u1ec7t"
            body = "B\u1ea1n \u0111\u00e3 l\u00e0 th\u00e0nh vi\u00ean c\u1ee7a t\u1ed5 ch\u1ee9c."
        else:
            title = f"H\u1ed3 s\u01a1 v\u00e0o {org.name} ch\u01b0a \u0111\u01b0\u1ee3c duy\u1ec7t"
            body = "B\u1ea1n c\u00f3 th\u1ec3 n\u1ed9p l\u1ea1i h\u1ed3 s\u01a1 sau 7 ng\u00e0y."
        try:
            self._notifications.notify(
                user_id,
                "membership",
                title,
                body,
                f'{{"org_id": "{org.id}", "org_slug": "{org.slug}"}}',
            )
        except Exception:  # noqa: BLE001 - notifications are best-effort
            pass
