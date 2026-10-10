"""Org dashboard statistics computed live over existing feed tables.

Reads stay partition-local (per-activity feeds capped), so this is an
MVP projection — pre-aggregated org_monthly_stats can replace it once
write-path counters land, without changing the HTTP contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from activities.interfaces import ActivityStore
from certificates.interfaces import CertificateStore
from core.exceptions import ForbiddenError, NotFoundError
from hours.interfaces import HourLedgerStore
from orgs.interfaces import MemberRepository, OrgRepository
from rbac.interfaces import AccessControl
from registrations.interfaces import AttendanceStore

_MAX_ACTIVITIES = 50


@dataclass(frozen=True)
class OrgStats:
    """Counts a manager dashboard renders for one org."""

    activities_total: int
    members_total: int
    participants_total: int
    hours_approved: float
    hours_pending: int
    certificates_issued: int


class OrgStatsService:
    """Manager-scoped live stats over denormalized feeds."""

    def __init__(
        self,
        orgs: OrgRepository,
        members: MemberRepository,
        activities: ActivityStore,
        hours: HourLedgerStore,
        attendance: AttendanceStore,
        certificates: CertificateStore,
        access: AccessControl,
    ) -> None:
        self._orgs = orgs
        self._members = members
        self._activities = activities
        self._hours = hours
        self._attendance = attendance
        self._certificates = certificates
        self._access = access

    def org_stats(self, org_id: UUID, actor_id: UUID) -> OrgStats:
        """Owner or activity:manage holder reads their org's numbers."""
        org = self._orgs.get_by_id(org_id)
        if org is None or getattr(org, "deleted_at", None) is not None:
            raise NotFoundError("Organization not found.")
        if (
            getattr(org, "owner_id", None) != actor_id
            and not self._access.has_permission(
                org_id, actor_id, "activity:manage"
            )
        ):
            raise ForbiddenError("Only org managers can view stats.")
        activities = self._activities.list_by_org(
            org_id, _MAX_ACTIVITIES
        )
        members = self._members.list_by_org(org_id)
        participants = 0
        approved = 0.0
        pending = 0
        certs = 0
        for activity in activities:
            participants += len(
                self._attendance.list_by_activity(activity.id)
            )
            for entry in self._hours.list_by_activity(activity.id):
                if entry.status == "approved":
                    approved += entry.hours or 0.0
                elif entry.status == "pending":
                    pending += 1
            certs += sum(
                1
                for row in self._certificates.list_by_activity(
                    activity.id
                )
                if row.status == "issued"
            )
        return OrgStats(
            activities_total=len(activities),
            members_total=len(members),
            participants_total=participants,
            hours_approved=round(approved, 1),
            hours_pending=pending,
            certificates_issued=certs,
        )
