import pytest
from pydantic import ValidationError

from src.models import certificates, notifications  # noqa: F401  registers the tables
from src.models.base import Base
from src.notifications.delivery import SUBJECTS, email_content
from src.notifications.events import NOTIFICATION_TYPES, QueuedEmail
from src.notifications.schemas import PreferencesRequest


def test_models_register_their_tables() -> None:
    assert {
        "notifications",
        "notification_preferences",
        "certificates",
        "certificate_revocations",
    } <= set(Base.metadata.tables)


def test_every_type_has_an_email_subject() -> None:
    assert set(NOTIFICATION_TYPES) == set(SUBJECTS)


def test_email_names_the_activity_and_links_to_the_app() -> None:
    subject, body = email_content(
        QueuedEmail(to="a@example.com", type="hours_awarded", subject_detail="Mua he"),
        "https://amigo.vn",
    )
    assert subject == "Your volunteer hours were recorded: Mua he"
    assert "https://amigo.vn/notifications" in body


def test_email_without_detail_keeps_a_clean_subject() -> None:
    subject, _ = email_content(
        QueuedEmail(to="a@example.com", type="activity_cancelled", subject_detail=""),
        "https://amigo.vn",
    )
    assert subject == "An activity was cancelled"


def test_preferences_default_to_in_app_only() -> None:
    payload = PreferencesRequest()
    assert payload.inapp is True
    assert payload.email is False
    assert payload.muted_types == []


def test_preferences_reject_unknown_types() -> None:
    with pytest.raises(ValidationError):
        PreferencesRequest.model_validate({"muted_types": ["made_up"]})
