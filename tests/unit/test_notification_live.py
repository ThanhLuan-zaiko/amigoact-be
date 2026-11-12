import uuid
from datetime import UTC, datetime

import pytest

from src.models.notifications import Notification
from src.notifications import live


def test_event_matches_an_inbox_item() -> None:
    created = datetime(2026, 11, 12, 8, 30, tzinfo=UTC)
    notification = Notification(
        notification_id=uuid.uuid7(),
        user_id=uuid.uuid7(),
        type="membership_requested",
        data_json={"message": "Xin vao"},
        created_at=created,
    )

    event = live.notification_event(notification)

    assert event == {
        "type": "notification.created",
        "notification": {
            "id": str(notification.notification_id),
            "type": "membership_requested",
            "data": {"message": "Xin vao"},
            "read": False,
            "created_at": created.isoformat(),
        },
    }


@pytest.mark.parametrize(("status", "read"), [("unread", False), ("read", True)])
def test_deleted_event_says_whether_it_was_read(status: str, read: bool) -> None:
    notification = Notification(
        notification_id=uuid.uuid7(),
        user_id=uuid.uuid7(),
        type="membership_requested",
        data_json={"organization_slug": "clb"},
        status=status,
        created_at=datetime(2026, 11, 12, tzinfo=UTC),
    )

    event = live.deleted_event(notification)

    assert event["type"] == "notification.deleted"
    assert event["notification"]["id"] == str(notification.notification_id)
    assert event["notification"]["read"] is read
    assert event["notification"]["data"] == {"organization_slug": "clb"}
