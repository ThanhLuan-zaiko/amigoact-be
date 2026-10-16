"""Org hour rules (multiplier/cap) and audited hour adjustments."""

from __future__ import annotations

from uuid import UUID

from activities.interfaces import ActivityStore
from core.exceptions import (
    ForbiddenError,
    InvalidHoursStateError,
    NotFoundError,
)
from core.ids import uuid7
from core.security import utcnow
from hours.interfaces import (
    AdjustmentStore,
    HourLedgerStore,
    HourRuleStore,
)
from hours.model import HourAdjustment, HourRule
from hours.service import term_of
from notifications.interfaces import NotificationPort
from orgs.interfaces import OrgRepository
from rbac.interfaces import AccessControl


class RuleService:
    """Manager-facing: rule CRUD plus correction entries."""

    def __init__(
        self,
        rules: HourRuleStore,
        adjustments: AdjustmentStore,
        ledger: HourLedgerStore,
        activities: ActivityStore,
        orgs: OrgRepository,
        access: AccessControl,
        notifications: NotificationPort | None = None,
    ) -> None:
        self._rules = rules
        self._adjustments = adjustments
        self._ledger = ledger
        self._activities = activities
        self._orgs = orgs
        self._access = access
        self._notifications = notifications

    def _require_manager(
        self, org_id: UUID, actor: UUID, action: str
    ) -> None:
        org = self._orgs.get_by_id(org_id)
        if org is None or getattr(org, "deleted_at", None) is not None:
            raise NotFoundError("Organization not found.")
        if (
            getattr(org, "owner_id", None) != actor
            and not self._access.has_permission(
                org_id, actor, "activity:manage"
            )
        ):
            self._access.record(
                org_id, actor, action, "hour_rule", None, "denied"
            )
            raise ForbiddenError("Only org managers can do this.")

    # Rules ---------------------------------------------------------

    def list_rules(self, org_id: UUID, actor: UUID) -> list[HourRule]:
        """Manager reads the org's full rule set."""
        self._require_manager(org_id, actor, "hours.rules")
        return self._rules.list_by_org(org_id)

    def create_rule(
        self,
        org_id: UUID,
        actor: UUID,
        multiplier: float,
        category_id: UUID | None = None,
        cap_hours: float | None = None,
        term: str | None = None,
    ) -> HourRule:
        """Attach a multiplier (optionally capped) to a category/term."""
        self._require_manager(org_id, actor, "hours.rule.create")
        if multiplier <= 0:
            raise InvalidHoursStateError(
                "Multiplier must be positive."
            )
        if cap_hours is not None and cap_hours <= 0:
            raise InvalidHoursStateError("Cap must be positive.")
        return self._rules.create(
            uuid7(), org_id, category_id, multiplier, cap_hours, term
        )

    def set_rule_active(
        self, org_id: UUID, rule_id: UUID, actor: UUID, active: bool
    ) -> HourRule:
        """Toggle a rule on/off without deleting audit data."""
        self._require_manager(org_id, actor, "hours.rule.toggle")
        rule = self._rules.get(rule_id)
        if rule is None or rule.org_id != org_id:
            raise NotFoundError("Hour rule not found.")
        updated = self._rules.set_active(rule_id, active)
        assert updated is not None
        return updated

    # Adjustments ----------------------------------------------------

    def adjust(
        self,
        org_id: UUID,
        actor: UUID,
        student_id: UUID,
        activity_id: UUID,
        delta_hours: float,
        reason: str,
    ) -> HourAdjustment:
        """Queue an 'adjustment' ledger entry plus its audit row."""
        self._require_manager(org_id, actor, "hours.adjust")
        activity = self._activities.get(activity_id)
        if activity is None or activity.org_id != org_id:
            raise NotFoundError("Activity not found.")
        if delta_hours == 0:
            raise InvalidHoursStateError(
                "Adjustment must be non-zero."
            )
        if not reason.strip():
            raise InvalidHoursStateError(
                "Adjustment requires a reason."
            )
        now = utcnow()
        audit = self._adjustments.create(
            uuid7(), student_id, activity_id, delta_hours,
            reason.strip(), actor, now,
        )
        entry = self._ledger.record(
            uuid7(), org_id, student_id, activity_id,
            "adjustment", delta_hours, term_of(now), None,
            actor, f"adjust:{audit.adjustment_id} {reason.strip()}",
            now,
        )
        self._access.record(
            org_id, actor, "hours.adjust", "hour_entry",
            entry.entry_id, "allowed",
        )
        if self._notifications is not None:
            try:
                self._notifications.notify(
                    student_id, "hours",
                    "Gi\u1edd t\xecnh nguy\u1ec7n \u0111\u01b0\u1ee3c \u0111i\u1ec1u ch\u1ec9nh",
                    f"Ban t\u1ed5 ch\u1ee9c \u0111\u1ec1 xu\u1ea5t \u0111i\u1ec1u ch\u1ec9nh {delta_hours} gi\u1edd.",
                    None,
                )
            except Exception:  # noqa: BLE001 - best-effort
                pass
        return audit


def match_rule(
    rules: list[HourRule], category_id: UUID | None, term: str
) -> HourRule | None:
    """Most specific active rule wins; None when nothing matches."""
    candidates = [r for r in rules if r.is_active]

    def score(rule: HourRule) -> int:
        cat = (
            2
            if rule.category_id is not None
            and rule.category_id == category_id
            else (0 if rule.category_id is None else -1)
        )
        trm = (
            1
            if rule.term is not None and rule.term == term
            else (0 if rule.term is None else -1)
        )
        return cat + trm if cat >= 0 and trm >= 0 else -1

    best = max(candidates, key=score, default=None)
    return best if best is not None and score(best) >= 0 else None


def apply_rule(
    rules: list[HourRule] | None,
    category_id: UUID | None,
    term: str,
    hours: float,
) -> float:
    """Multiply then cap; pass-through when no rule matches."""
    if not rules:
        return hours
    rule = match_rule(rules, category_id, term)
    if rule is None:
        return hours
    adjusted = hours * (rule.multiplier or 1.0)
    if rule.cap_hours is not None:
        adjusted = min(adjusted, rule.cap_hours)
    return round(adjusted, 2)
