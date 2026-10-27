"""Unit tests: applying stops once an activity's window has closed."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from core.exceptions import RegistrationClosedError
from tests.unit.test_registration_service import _setup


def test_apply_rejects_activity_that_already_ended() -> None:
    (svc, _a, _r, _at, _acts, _o, _acc, _u, _n,
     _org, activity, _owner, student) = _setup()
    activity.start_at = datetime.now(UTC) - timedelta(days=2)
    activity.end_at = datetime.now(UTC) - timedelta(days=1)
    with pytest.raises(RegistrationClosedError):
        svc.apply(activity.id, student, None)


def test_apply_accepts_activity_in_progress() -> None:
    (svc, _a, _r, _at, _acts, _o, _acc, _u, _n,
     _org, activity, _owner, student) = _setup()
    activity.status = "ongoing"
    activity.start_at = datetime.now(UTC) - timedelta(hours=1)
    activity.end_at = datetime.now(UTC) + timedelta(hours=2)
    row = svc.apply(activity.id, student, None)
    assert row.status == "pending"
