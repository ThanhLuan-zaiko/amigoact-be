import uuid

from src.models.organizations import Organization
from src.organizations.picture_router import (
    PictureChoice,
    keep_in_gallery,
    owned_picture_ids,
)


def test_owned_pictures_are_logo_cover_and_gallery() -> None:
    logo, cover, photo = uuid.uuid7(), uuid.uuid7(), uuid.uuid7()
    org = Organization(logo_media_id=logo, cover_media_id=cover)

    assert owned_picture_ids(org, {photo}) == {logo, cover, photo}


def test_missing_pictures_are_not_owned() -> None:
    org = Organization(logo_media_id=None, cover_media_id=None)

    assert owned_picture_ids(org, set()) == set()


def test_left_out_fields_are_not_set() -> None:
    choice = PictureChoice.model_validate({"logo_asset_id": None})

    assert choice.model_fields_set == {"logo_asset_id"}


def test_replaced_pictures_move_to_the_gallery() -> None:
    old_logo, old_cover, new = uuid.uuid7(), uuid.uuid7(), uuid.uuid7()

    kept = keep_in_gallery((old_logo, old_cover), (new, old_cover), set())

    assert kept == [old_logo]


def test_swapped_or_already_kept_pictures_are_not_added() -> None:
    logo, cover = uuid.uuid7(), uuid.uuid7()

    assert keep_in_gallery((logo, cover), (cover, logo), set()) == []
    assert keep_in_gallery((logo, None), (None, None), {logo}) == []
