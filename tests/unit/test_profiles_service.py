"""Unit tests for ProfileService: skills, contacts, profile, avatar."""

from __future__ import annotations

import uuid_utils
import pytest

from core.exceptions import (
    InvalidSkillLevelError,
    MediaTooLargeError,
    NotFoundError,
    SkillNotFoundError,
    TooManyContactsError,
    UnsupportedMediaError,
)
from tests.unit.profile_fakes import make_service, new_user


def _png() -> bytes:
    """Minimal 1x1 PNG so media_kind classification passes."""
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\x0bIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
        b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def test_empty_bundle_for_fresh_user() -> None:
    service, _, users, _ = make_service()
    user = new_user(users)
    bundle = service.get_mine(user.id)
    assert bundle.profile is None
    assert bundle.skills == []
    assert bundle.contacts == []
    assert bundle.avatar_url is None


def test_upsert_creates_then_replaces() -> None:
    service, profiles, users, _ = make_service()
    user = new_user(users)
    service.update_mine(
        user.id,
        student_code="SV001", class_name="CTK43",
        enrollment_year=2022, school_name="BK",
        bio="hi", interests={"beach", "code"}, status="studying",
    )
    again = service.update_mine(
        user.id,
        student_code="SV001", class_name="CTK44",
        enrollment_year=2022, school_name="BK",
        bio=None, interests=set(), status="graduated",
    )
    assert again.profile is not None
    assert again.profile.class_name == "CTK44"
    assert again.profile.status == "graduated"
    assert again.profile.total_hours == 0.0
    assert len(profiles.profiles) == 1


def test_set_skills_validates_catalog_and_level() -> None:
    service, profiles, users, _ = make_service()
    user = new_user(users)
    skill = profiles.add_skill("First Aid", "first-aid")
    with pytest.raises(SkillNotFoundError):
        service.set_skills(user.id, [(uuid_utils.uuid7(), 3)])
    with pytest.raises(InvalidSkillLevelError):
        service.set_skills(user.id, [(skill.id, 9)])
    bundle = service.set_skills(user.id, [(skill.id, 4)])
    assert [(s.skill_id, s.level) for s in bundle.skills] == [(skill.id, 4)]
    assert profiles.reverse_skills[skill.id] == {user.id: 4}


def test_set_skills_removes_dropped_edges_both_ways() -> None:
    service, profiles, users, _ = make_service()
    user = new_user(users)
    keep = profiles.add_skill("Keep", "keep")
    drop = profiles.add_skill("Drop", "drop")
    service.set_skills(user.id, [(keep.id, 2), (drop.id, 5)])
    service.set_skills(user.id, [(keep.id, 3)])
    assert drop.id not in profiles.user_skills.get(user.id, {})
    assert user.id not in profiles.reverse_skills.get(drop.id, {})


def test_contacts_cap_and_primary_handoff() -> None:
    service, _, users, _ = make_service()
    user = new_user(users)
    first = service.add_contact(
        user.id, name="Mom", relation="mother", phone="0901234567",
        is_primary=False,
    )
    assert first.contacts[0].is_primary is True
    service.add_contact(
        user.id, name="Dad", relation="father", phone="0907654321",
        is_primary=True,
    )
    bundle = service.get_mine(user.id)
    primaries = [c.name for c in bundle.contacts if c.is_primary]
    assert primaries == ["Dad"]
    service.add_contact(
        user.id, name="Sis", relation=None, phone="0911111111",
        is_primary=False,
    )
    with pytest.raises(TooManyContactsError):
        service.add_contact(
            user.id, name="Fourth", relation=None, phone="0922222222",
            is_primary=False,
        )


def test_remove_contact_promotes_survivor() -> None:
    service, profiles, users, _ = make_service()
    user = new_user(users)
    service.add_contact(
        user.id, name="Mom", relation=None, phone="0901234567",
        is_primary=False,
    )
    bundle = service.add_contact(
        user.id, name="Dad", relation=None, phone="0907654321",
        is_primary=True,
    )
    dad = next(c for c in bundle.contacts if c.name == "Dad")
    after = service.remove_contact(user.id, dad.contact_id)
    assert len(after.contacts) == 1
    assert after.contacts[0].is_primary is True
    with pytest.raises(NotFoundError):
        service.remove_contact(user.id, dad.contact_id)


def test_avatar_upload_writes_asset_and_pointer() -> None:
    service, _, users, media = make_service()
    user = new_user(users)
    url = service.upload_avatar(
        user.id, "me.png", "image/png", _png()
    )
    assert url.startswith("/media/users/")
    assert users.by_id[user.id].avatar_media_id is not None
    assert len(media.assets) == 1
    asset = next(iter(media.assets.values()))
    assert asset.role == "avatar"
    assert asset.uploader_id == user.id


def test_avatar_upload_replaces_old_asset() -> None:
    service, _, users, media = make_service()
    user = new_user(users)
    service.upload_avatar(user.id, "a.png", "image/png", _png())
    service.upload_avatar(user.id, "b.png", "image/png", _png())
    assert len(media.assets) == 1
    asset = next(iter(media.assets.values()))
    assert users.by_id[user.id].avatar_media_id == asset.asset_id


def test_avatar_rejects_non_image_and_oversize() -> None:
    service, _, users, _ = make_service()
    user = new_user(users)
    with pytest.raises(UnsupportedMediaError):
        service.upload_avatar(
            user.id, "clip.mp4", "video/mp4", b"data"
        )
    with pytest.raises(MediaTooLargeError):
        service.upload_avatar(
            user.id, "big.png", "image/png", b"x" * (11 * 1024 * 1024)
        )


def test_public_card_404_and_strips_contacts() -> None:
    service, _, users, _ = make_service()
    with pytest.raises(NotFoundError):
        service.public_card(uuid_utils.uuid7())
    user = new_user(users)
    service.add_contact(
        user.id, name="Mom", relation=None, phone="0901234567",
        is_primary=False,
    )
    card = service.public_card(user.id)
    assert card.full_name == "Volunteer One"
    assert not hasattr(card, "contacts")
