"""Unit tests for the profile slice of AuthService (fake ports)."""

from __future__ import annotations

from datetime import date
from uuid import UUID

import pytest
import uuid_utils

from core.exceptions import InvalidBusinessProfileError, NotFoundError
from tests.unit.auth_fakes import (
    EMAIL,
    NAME,
    PASSWORD,
    PHONE,
    make_service,
)


def test_login_stamps_last_login_at() -> None:
    service, parts = make_service()
    service.register(EMAIL, PHONE, PASSWORD, NAME)
    user = parts["users"].get_by_email(EMAIL)
    assert user.last_login_at is None
    service.login(EMAIL, PASSWORD, "127.0.0.1")
    assert user.last_login_at is not None


def test_update_profile_replaces_and_clears() -> None:
    service, parts = make_service()
    service.register(EMAIL, PHONE, PASSWORD, NAME)
    user = parts["users"].get_by_email(EMAIL)

    profile = service.update_profile(
        user.id,
        "Tran Thi B",
        date_of_birth=date(2000, 5, 15),
        gender="female",
        address="  Da Nang ",
    )
    assert profile.full_name == "Tran Thi B"
    assert profile.date_of_birth == date(2000, 5, 15)
    assert profile.gender == "female"
    assert profile.address == "Da Nang"

    cleared = service.update_profile(user.id, "Tran Thi B")
    assert cleared.date_of_birth is None
    assert cleared.address is None

    with pytest.raises(InvalidBusinessProfileError):
        service.update_profile(user.id, "X")
    with pytest.raises(InvalidBusinessProfileError):
        service.update_profile(
            user.id, "Tran Thi B", date_of_birth=date(2999, 1, 1)
        )
    with pytest.raises(InvalidBusinessProfileError):
        service.update_profile(user.id, "Tran Thi B", gender="alien")
    with pytest.raises(NotFoundError):
        service.update_profile(UUID(str(uuid_utils.uuid7())), "Ghost User")


def test_session_profile_resolves_avatar_url() -> None:
    """/auth/me surfaces the same avatar that /profiles/me edits."""
    service, parts = make_service()
    service.register(EMAIL, PHONE, PASSWORD, NAME)
    user = parts["users"].get_by_email(EMAIL)

    assert service.get_profile(user.id).avatar_url is None

    asset = parts["media"].create_asset(
        uuid_utils.uuid7(),
        user.id,
        "users/u/a.png",
        "image/png",
        4,
        user.created_at,
        role="avatar",
    )
    parts["users"].set_avatar_media(user.id, asset.asset_id, user.created_at)
    assert service.get_profile(user.id).avatar_url == "/media/users/u/a.png"

    parts["media"].delete_asset(asset.asset_id)
    assert service.get_profile(user.id).avatar_url is None
