import pytest
from pydantic import ValidationError

from src.media.sniff import MP4, WEBM, detect_image, detect_video, is_video
from src.organizations.gallery import MAX_GALLERY_ITEMS, has_room
from src.organizations.schemas import OrganizationUpdateRequest


def test_gallery_has_room_below_the_limit_only() -> None:
    assert has_room(MAX_GALLERY_ITEMS - 1)
    assert not has_room(MAX_GALLERY_ITEMS)


def test_video_is_recognized_by_its_first_bytes() -> None:
    assert detect_video(b"\x00\x00\x00\x18ftypmp42") == MP4
    assert detect_video(b"\x1a\x45\xdf\xa3rest") == WEBM
    assert detect_video(b"plain text here") is None
    assert detect_image(b"\x00\x00\x00\x18ftypmp42") is None


def test_is_video_reads_the_mime() -> None:
    assert is_video("video/mp4")
    assert not is_video("image/png")
    assert not is_video(None)


@pytest.mark.parametrize("field", ["description", "email", "phone", "city"])
def test_update_rejects_clearing_a_required_field(field: str) -> None:
    with pytest.raises(ValidationError) as exc:
        OrganizationUpdateRequest.model_validate({field: None})

    assert exc.value.errors()[0]["type"] == "required"
