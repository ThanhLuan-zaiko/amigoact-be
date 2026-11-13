import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.organizations.access import Access
from src.organizations.permissions import (
    ADMINISTRATOR,
    ALL,
    DEFAULT_ADMIN,
    POSTS_PIN,
    ROLES_ASSIGN,
    ROLES_CREATE,
    ROLES_DELETE,
    ROLES_UPDATE,
)
from src.organizations.role_schemas import (
    PermissionCode,
    RoleCreateRequest,
    RoleUpdateRequest,
)


def test_schema_seeds_the_same_permissions_as_the_code() -> None:
    sql = Path("schema.sql").read_text(encoding="utf-8")
    block = sql.split("INSERT INTO permissions", 1)[1].split("ON CONFLICT", 1)[0]
    assert set(re.findall(r"\('([a-z_.]+)',\s+'", block)) == ALL


def test_request_schema_lists_every_permission() -> None:
    assert set(PermissionCode.__args__) == ALL  # type: ignore[attr-defined]


def test_new_admin_role_cannot_hand_out_roles_or_administrator() -> None:
    assert ADMINISTRATOR not in DEFAULT_ADMIN
    assert ROLES_CREATE not in DEFAULT_ADMIN
    assert DEFAULT_ADMIN == ALL - {
        ADMINISTRATOR,
        ROLES_CREATE,
        ROLES_UPDATE,
        ROLES_DELETE,
        ROLES_ASSIGN,
    }


def test_access_has_checks_the_named_permission() -> None:
    access = Access(status="active", role="admin", permissions=frozenset({POSTS_PIN}))
    assert access.has(POSTS_PIN)
    assert not access.has(ROLES_CREATE)
    assert access.can_manage


def test_administrator_holds_every_permission() -> None:
    access = Access(
        status="active", role="admin", permissions=frozenset({ADMINISTRATOR})
    )
    assert all(access.has(code) for code in ALL)


def test_a_plain_member_holds_nothing() -> None:
    access = Access(status="active", role="member")
    assert not access.can_manage
    assert not access.has(POSTS_PIN)


def test_role_color_is_lowercased_and_checked() -> None:
    assert RoleCreateRequest(name="A", color="#ABCDEF").color == "#abcdef"
    assert RoleCreateRequest(name="A").color == ""
    for bad in ("red", "#abc", "#12345g", "abcdef"):
        with pytest.raises(ValidationError):
            RoleCreateRequest(name="A", color=bad)


def test_role_name_is_trimmed_and_needs_a_letter() -> None:
    assert RoleCreateRequest(name="  Team   lead ").name == "Team lead"
    for bad in ("", "   ", "123", "a" * 51):
        with pytest.raises(ValidationError):
            RoleCreateRequest(name=bad)


def test_update_rejects_null_and_unknown_fields() -> None:
    assert RoleUpdateRequest().model_fields_set == set()
    for body in ({"name": None}, {"permissions": None}, {"position": 3}):
        with pytest.raises(ValidationError):
            RoleUpdateRequest(**body)  # type: ignore[arg-type]


def test_has_any_matches_a_whole_module() -> None:
    access = Access(
        status="active", role="admin", permissions=frozenset({"activities.create"})
    )
    assert access.has_any("activities")
    assert not access.has("activities.delete")
    assert not access.has_any("posts")
    assert Access(
        status="active", role="admin", permissions=frozenset({ADMINISTRATOR})
    ).has_any("posts")


def test_every_code_is_module_dot_action() -> None:
    for code in ALL - {ADMINISTRATOR}:
        module, _, action = code.partition(".")
        assert module and action
