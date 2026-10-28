"""In-memory membership form and application stores for unit tests."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

from auth.interfaces import RateLimiter
from notifications.interfaces import NotificationPort
from orgs.application_interfaces import ApplicationStore, MembershipFormStore


class FakeForms(MembershipFormStore):
    def __init__(self) -> None:
        self.rows: dict[UUID, list] = {}
        self.settings: dict[UUID, SimpleNamespace] = {}

    def list_form(self, org_id):  # noqa: ANN001, ANN202
        return list(self.rows.get(org_id, []))

    def replace_form(self, org_id, rows):  # noqa: ANN001, ANN202
        self.rows[org_id] = [
            SimpleNamespace(
                question_id=question_id,
                position=position,
                label=label,
                field_type=field_type,
                required=required,
                options=options,
                allow_other=allow_other,
            )
            for position, (question_id, label, field_type, required, options, allow_other) in enumerate(rows)
        ]

    def get_settings(self, org_id):  # noqa: ANN001, ANN202
        return self.settings.get(org_id)

    def put_settings(self, org_id, title, description):  # noqa: ANN001, ANN202
        self.settings[org_id] = SimpleNamespace(title=title, description=description)


class FakeApplications(ApplicationStore):
    def __init__(self) -> None:
        self.rows: dict[tuple[UUID, UUID], SimpleNamespace] = {}

    def get(self, org_id, user_id):  # noqa: ANN001, ANN202
        return self.rows.get((org_id, user_id))

    def put(self, org_id, user_id, answers, now):  # noqa: ANN001, ANN202
        self.rows[(org_id, user_id)] = SimpleNamespace(
            org_id=org_id,
            user_id=user_id,
            answers=answers,
            submitted_at=now,
            rejected_at=None,
        )

    def mark_rejected(self, org_id, user_id, now):  # noqa: ANN001, ANN202
        self.rows[(org_id, user_id)].rejected_at = now


class FakeLimiter(RateLimiter):
    """Counts hits per bucket; windows are ignored, tests control time instead."""

    def __init__(self) -> None:
        self.hits: dict[str, int] = {}

    def hit(self, bucket, window_seconds):  # noqa: ANN001, ANN202
        self.hits[bucket] = self.hits.get(bucket, 0) + 1
        return self.hits[bucket]


class FakeNotifications(NotificationPort):
    def __init__(self) -> None:
        self.sent: list[tuple] = []

    def notify(self, user_id, category, title, body, payload=None):  # noqa: ANN001, ANN202
        self.sent.append((user_id, category, title))
