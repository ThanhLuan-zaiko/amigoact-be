import uuid

import pytest
from pydantic import ValidationError

from src.posts.activity_link import LINKABLE_STATUSES, linkable
from src.posts.schemas import PostCreate, PostUpdate

ORG = uuid.uuid7()


@pytest.mark.parametrize("status", ["published", "completed"])
def test_people_can_see_published_and_completed_activities(status: str) -> None:
    assert linkable(ORG, status, ORG) is True


@pytest.mark.parametrize("status", ["draft", "cancelled", "ongoing"])
def test_drafts_and_cancelled_activities_cannot_be_linked(status: str) -> None:
    assert status not in LINKABLE_STATUSES
    assert linkable(ORG, status, ORG) is False


def test_activity_of_another_organization_cannot_be_linked() -> None:
    assert linkable(uuid.uuid7(), "published", ORG) is False


def test_activity_id_must_be_a_uuid7() -> None:
    with pytest.raises(ValidationError):
        PostCreate(
            kind="discussion", title="x", body="y", activity_id=str(uuid.uuid4())
        )


def test_update_tells_a_sent_null_from_a_missing_field() -> None:
    cleared = PostUpdate.model_validate({"activity_id": None})
    untouched = PostUpdate.model_validate({"title": "Moi"})
    assert "activity_id" in cleared.model_fields_set
    assert "activity_id" not in untouched.model_fields_set
