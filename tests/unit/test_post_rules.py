import pytest
from pydantic import ValidationError

from src.organizations.access import Access
from src.organizations.permissions import DEFAULT_ADMIN
from src.posts.rules import (
    ANNOUNCEMENT,
    DISCUSSION,
    MEMBERS,
    PUBLIC,
    default_visibility,
    may_post,
    tag_slug,
)
from src.posts.schemas import CommentCreate, PostCreate, PostUpdate


def test_announcements_default_to_public_and_discussions_to_members() -> None:
    assert default_visibility(ANNOUNCEMENT) == PUBLIC
    assert default_visibility(DISCUSSION) == MEMBERS


def test_outsiders_and_pending_members_cannot_post() -> None:
    assert may_post(DISCUSSION, Access(status=None, role=None)) is False
    assert may_post(DISCUSSION, Access(status="pending", role=None)) is False


def test_any_active_member_may_discuss_but_only_managers_announce() -> None:
    member = Access(status="active", role="member")
    manager = Access(status="active", role="admin", permissions=DEFAULT_ADMIN)
    assert may_post(DISCUSSION, member) is True
    assert may_post(ANNOUNCEMENT, member) is False
    assert may_post(ANNOUNCEMENT, manager) is True


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("M\u00f4i tr\u01b0\u1eddng", "moi-truong"),
        ("\u0110o\u00e0n tr\u01b0\u1eddng", "doan-truong"),
        ("  Hi\u1ebfn m\u00e1u!! ", "hien-mau"),
        ("---", None),
        ("!!!", None),
    ],
)
def test_tag_names_become_ascii_slugs(name: str, expected: str | None) -> None:
    assert tag_slug(name) == expected


def test_long_tag_slug_is_cut_without_a_trailing_hyphen() -> None:
    slug = tag_slug("a" * 39 + " bbbb")
    assert slug == "a" * 39


def test_post_needs_a_title_and_a_kind() -> None:
    with pytest.raises(ValidationError):
        PostCreate.model_validate({"kind": "discussion", "body": "x"})
    with pytest.raises(ValidationError):
        PostCreate.model_validate({"kind": "gossip", "title": "x", "body": "x"})


def test_post_refuses_more_than_five_tags() -> None:
    with pytest.raises(ValidationError):
        PostCreate(
            kind="discussion", title="x", body="y", tags=["a", "b", "c", "d", "e", "f"]
        )


def test_post_title_refuses_line_breaks_and_nul() -> None:
    with pytest.raises(ValidationError):
        PostCreate(kind="discussion", title="a\nb", body="y")
    with pytest.raises(ValidationError):
        PostCreate(kind="discussion", title="a\x00b", body="y")


def test_post_body_is_trimmed() -> None:
    payload = PostCreate(kind="discussion", title=" Tieu de ", body="  Noi dung  ")
    assert payload.title == "Tieu de"
    assert payload.body == "Noi dung"


def test_update_sends_only_what_it_changes() -> None:
    payload = PostUpdate.model_validate({"title": "Moi"})
    assert payload.model_fields_set == {"title"}


def test_comment_body_cannot_be_blank() -> None:
    with pytest.raises(ValidationError):
        CommentCreate(body="   ")
