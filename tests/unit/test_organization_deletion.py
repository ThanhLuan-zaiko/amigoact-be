import re
import uuid
from datetime import UTC, datetime

from src.models.organizations import Organization
from src.organizations.deletion import (
    mark_deleted,
    own_reference_count,
    picture_ids,
    released_slug,
)
from src.organizations.slugs import SLUG_MAX_LENGTH

SLUG_PATTERN = re.compile(r"^[A-Za-z0-9-]{1,80}$")


def organization(slug: str = "doan-truong") -> Organization:
    return Organization(
        id=uuid.uuid7(),
        name="Doan truong",
        slug=slug,
        owner_id=uuid.uuid7(),
        deleted_at=None,
    )


def test_released_slug_is_a_valid_url_part_and_unique() -> None:
    first, second = released_slug(), released_slug()

    assert first != second
    assert SLUG_PATTERN.fullmatch(first)
    assert len(first) <= SLUG_MAX_LENGTH


def test_mark_deleted_moves_the_slug_aside_and_hides_the_row() -> None:
    org = organization("doan-truong")
    now = datetime(2026, 11, 3, tzinfo=UTC)

    mark_deleted(org, now)

    assert org.previous_slug == "doan-truong"
    assert org.slug != "doan-truong"
    assert org.slug.startswith("deleted-")
    assert org.deleted_at == now


def test_mark_deleted_keeps_the_other_fields() -> None:
    org = organization()
    owner_id, org_id = org.owner_id, org.id

    mark_deleted(org, datetime(2026, 11, 3, tzinfo=UTC))

    assert org.owner_id == owner_id
    assert org.id == org_id
    assert org.name == "Doan truong"


def test_own_references_count_each_place_the_organization_uses_a_file() -> None:
    shared = uuid.uuid7()
    other = uuid.uuid7()

    assert own_reference_count(shared, shared, shared, {shared}) == 3
    assert own_reference_count(other, shared, None, {shared}) == 0
    assert own_reference_count(shared, None, None, set()) == 0


def test_picture_ids_cover_logo_cover_and_gallery_without_duplicates() -> None:
    logo, cover, gallery_only = uuid.uuid7(), uuid.uuid7(), uuid.uuid7()
    org = organization()
    org.logo_media_id = logo
    org.cover_media_id = None

    pictures = picture_ids(org, {logo, gallery_only})

    assert pictures == {logo, gallery_only}
    org.cover_media_id = cover
    assert picture_ids(org, set()) == {logo, cover}
