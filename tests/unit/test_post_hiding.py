import uuid

from src.models.posts import OrgPost
from src.organizations.access import ACTIVE, Access
from src.organizations.permissions import ALL, DEFAULT_ADMIN
from src.posts.hiding import sees_hidden
from src.posts.views import _viewer_flags


def _post(status: str = "active") -> OrgPost:
    return OrgPost(
        post_id=uuid.uuid7(),
        org_id=uuid.uuid7(),
        author_id=uuid.uuid7(),
        kind="announcement",
        status=status,
    )


def test_only_active_managers_see_hidden_posts() -> None:
    assert sees_hidden(Access(status=ACTIVE, role="owner", permissions=ALL)) is True
    assert (
        sees_hidden(Access(status=ACTIVE, role="admin", permissions=DEFAULT_ADMIN))
        is True
    )
    assert sees_hidden(Access(status=ACTIVE, role="member")) is False
    assert (
        sees_hidden(Access(status="pending", role="admin", permissions=DEFAULT_ADMIN))
        is False
    )
    assert sees_hidden(None) is False


def test_can_hide_only_for_managers_on_published_posts() -> None:
    viewer = uuid.uuid7()
    owner = Access(status=ACTIVE, role="owner", permissions=ALL)
    member = Access(status=ACTIVE, role="member")

    assert _viewer_flags(_post(), owner, viewer).can_hide is True
    assert _viewer_flags(_post(), member, viewer).can_hide is False
    assert _viewer_flags(_post("draft"), owner, viewer).can_hide is False
    assert _viewer_flags(_post(), None, None).can_hide is False
