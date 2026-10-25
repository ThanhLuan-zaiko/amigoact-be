"""Shared in-memory ports, constants and row builders for the browse tests."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

from activities.browse_interfaces import (
    BrowseIndex,
    MyRegistrationBrief,
    RegistrationBriefs,
    SeatCounter,
)
from activities.browse_service import ActivityBrowseService
from core.ids import uuid7

NOW = datetime(2026, 10, 25, 9, 0)
ORG = uuid7()
HA_NOI = "H" + chr(0xE0) + " N" + chr(0x1ED9) + "i"  # "Ha Noi" with diacritics
MOI_TRUONG = "M" + chr(0xF4) + "i tr" + chr(0x1B0) + chr(0x1EDD) + "ng"


def _org(**overrides) -> SimpleNamespace:
    base = dict(
        id=ORG,
        name="CLB Xanh",
        slug="clb-xanh",
        status="active",
        deleted_at=None,
        logo_media_id=None,
        verified_at=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _row(**overrides) -> SimpleNamespace:
    base = dict(
        id=uuid7(),
        org_id=ORG,
        title="Don rac bo bien",
        slug="don-rac",
        status="published",
        start_at=NOW + timedelta(days=5),
        end_at=None,
        published_at=NOW - timedelta(days=1),
        deleted_at=None,
        city=None,
        location=None,
        is_remote=False,
        hours_awarded=2.0,
        category_id=None,
        tag_names=[],
        max_participants=None,
        registration_deadline=None,
        description="",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class FakeIndex(BrowseIndex):
    def __init__(self, rows, truncated=False) -> None:
        self.rows = rows
        self.truncated = truncated

    def candidates(self, phase, now):  # noqa: ANN001, ANN202
        return [row.id for row in self.rows], self.truncated

    def hydrate(self, ids):  # noqa: ANN001, ANN202
        by_id = {row.id: row for row in self.rows}
        return [by_id[item] for item in ids if item in by_id]


class FakeOrgs:
    def __init__(self, *orgs) -> None:  # noqa: ANN002
        self.by_id = {org.id: org for org in orgs}
        self.calls: list[UUID] = []

    def get_by_id(self, org_id):  # noqa: ANN001, ANN202
        self.calls.append(org_id)
        return self.by_id.get(org_id)


class FakeEntries:
    def __init__(self, mapping=None) -> None:  # noqa: ANN001
        self.mapping = mapping or {}

    def list_for_activity(self, activity_id):  # noqa: ANN001, ANN202
        return self.mapping.get(activity_id, [])


class FakeMedia:
    def __init__(self, assets=None) -> None:  # noqa: ANN001
        self.assets = assets or {}

    def get_asset(self, asset_id):  # noqa: ANN001, ANN202
        return self.assets.get(asset_id)


class FakeSeats(SeatCounter):
    def __init__(self, counts=None) -> None:  # noqa: ANN001
        self.counts = counts or {}

    def registered_count(self, activity_id):  # noqa: ANN001, ANN202
        return self.counts.get(activity_id, 0)


class FakeBriefs(RegistrationBriefs):
    def __init__(self, by_activity=None) -> None:  # noqa: ANN001
        self.by_activity = by_activity or {}

    def briefs_for(self, student_id):  # noqa: ANN001, ANN202
        return dict(self.by_activity)


class FakeCategoryNames:
    """Catalog lookup: unknown ids answer None, like the real store."""

    def __init__(self, names=None) -> None:  # noqa: ANN001
        self.names = names or {}

    def get(self, category_id):  # noqa: ANN001, ANN202
        name = self.names.get(category_id)
        if name is None:
            return None
        return SimpleNamespace(id=category_id, name=name)


def _brief(status: str) -> MyRegistrationBrief:
    return MyRegistrationBrief(
        registration_id=uuid7(), status=status, registered_at=NOW
    )


def _service(rows, orgs=None, **kwargs) -> ActivityBrowseService:  # noqa: ANN003
    return ActivityBrowseService(
        index=FakeIndex(rows, kwargs.pop("truncated", False)),
        orgs=orgs or FakeOrgs(_org()),
        entries=FakeEntries(kwargs.pop("entries", None)),
        media=FakeMedia(kwargs.pop("assets", None)),
        seats=FakeSeats(kwargs.pop("seats", None)),
        briefs=FakeBriefs(kwargs.pop("briefs", None)),
        categories=FakeCategoryNames(kwargs.pop("category_names", None)),
    )


ENV = uuid7()
EDU = uuid7()
CATEGORY_NAMES = {ENV: "Environment", EDU: "Education"}

