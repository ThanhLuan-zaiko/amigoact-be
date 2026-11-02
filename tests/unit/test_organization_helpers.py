from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from src.models import organizations  # noqa: F401  registers the tables
from src.models.base import Base
from src.organizations.access import Access, resolve_role
from src.organizations.schemas import (
    JoinRequest,
    OrganizationCreateRequest,
    OrganizationUpdateRequest,
    normalize_website,
)
from src.organizations.service import REAPPLY_COOLDOWN, reapply_time
from src.organizations.slugs import (
    FALLBACK_SLUG,
    SLUG_MAX_LENGTH,
    candidate_slug,
    slugify,
)


def test_organization_models_register_their_tables() -> None:
    assert {
        "organizations",
        "organization_members",
        "membership_applications",
        "roles",
        "user_roles",
    } <= set(Base.metadata.tables)


@pytest.mark.parametrize(
    ("name", "slug"),
    [
        ("Doan Truong", "doan-truong"),
        ("\u0110o\xe0n Tr\u01b0\u1eddng \u0110\u1ea1i H\u1ecdc", "doan-truong-dai-hoc"),
        ("  CLB -- T\xecnh nguy\u1ec7n!! ", "clb-tinh-nguyen"),
        ("!!!", FALLBACK_SLUG),
    ],
)
def test_slugify_builds_ascii_words(name: str, slug: str) -> None:
    assert slugify(name) == slug


def test_slugify_limits_length_without_a_trailing_hyphen() -> None:
    slug = slugify(f"{'a' * (SLUG_MAX_LENGTH - 1)} bcd")
    assert len(slug) <= SLUG_MAX_LENGTH
    assert not slug.endswith("-")


def test_candidate_slug_adds_a_suffix_after_the_first_attempt() -> None:
    assert candidate_slug("doan", 0) == "doan"
    assert candidate_slug("doan", 1).startswith("doan-")


@pytest.mark.parametrize("reserved", ["mine", "new"])
def test_candidate_slug_never_returns_a_reserved_path(reserved: str) -> None:
    assert candidate_slug(reserved, 0) != reserved


def test_resolve_role_ranks_owner_then_admin_then_member() -> None:
    assert resolve_role(is_owner=True, is_admin=False, status="active") == "owner"
    assert resolve_role(is_owner=False, is_admin=True, status="active") == "admin"
    assert resolve_role(is_owner=False, is_admin=False, status="active") == "member"


@pytest.mark.parametrize("status", ["applied", "left", "revoked", "suspended", None])
def test_only_active_members_have_a_role(status: str | None) -> None:
    assert resolve_role(is_owner=True, is_admin=True, status=status) is None


def test_only_owner_and_admin_can_manage() -> None:
    assert Access(status="active", role="owner").can_manage
    assert Access(status="active", role="admin").can_manage
    assert not Access(status="active", role="member").can_manage
    assert not Access(status=None, role=None).can_manage


def test_reapply_time_counts_the_cooldown_from_the_rejection() -> None:
    now = datetime(2026, 1, 10, tzinfo=UTC)
    assert reapply_time(None, now) is None
    assert reapply_time(now - REAPPLY_COOLDOWN, now) is None
    recent = now - timedelta(days=1)
    assert reapply_time(recent, now) == recent + REAPPLY_COOLDOWN


def test_website_accepts_only_http_urls() -> None:
    assert normalize_website(" https://example.org ") == "https://example.org"
    for bad in ("javascript:alert(1)", "example.org", "ftp://example.org", "http://"):
        with pytest.raises(ValueError, match="http"):
            normalize_website(bad)


def test_create_request_defaults_to_approval_and_trims_the_name() -> None:
    payload = OrganizationCreateRequest(name="  CLB  ")
    assert payload.name == "CLB"
    assert payload.join_policy == "invite"


def test_create_request_rejects_a_blank_name() -> None:
    with pytest.raises(ValidationError):
        OrganizationCreateRequest(name="   ")


@pytest.mark.parametrize("field", ["name", "org_type", "join_policy"])
def test_update_request_rejects_null_for_required_fields(field: str) -> None:
    with pytest.raises(ValidationError) as caught:
        OrganizationUpdateRequest.model_validate({field: None})
    assert caught.value.errors()[0]["loc"] == (field,)


def test_update_request_allows_null_for_optional_fields() -> None:
    payload = OrganizationUpdateRequest.model_validate({"website": None})
    assert payload.model_fields_set == {"website"}


def test_join_request_treats_a_long_message_as_invalid() -> None:
    with pytest.raises(ValidationError):
        JoinRequest(message="x" * 1001)
