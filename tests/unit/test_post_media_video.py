import uuid
from typing import Any

import pytest
from fastapi import HTTPException

from src.media import service
from src.models.media import MediaAsset


class FakeSession:
    """Returns one asset for every lookup, so no database is needed."""

    def __init__(self, asset: MediaAsset) -> None:
        self.asset = asset

    def get(self, *_args: Any, **_kwargs: Any) -> MediaAsset:
        return self.asset


def asset(mime: str, uploader: uuid.UUID) -> MediaAsset:
    return MediaAsset(
        asset_id=uuid.uuid7(),
        mime=mime,
        uploader_id=uploader,
        upload_status="active",
        visibility="private",
    )


def test_video_is_refused_unless_the_caller_allows_it() -> None:
    owner = uuid.uuid7()
    video = asset("video/mp4", owner)

    with pytest.raises(HTTPException) as caught:
        service.owned_asset(FakeSession(video), video.asset_id, owner)  # type: ignore[arg-type]

    assert caught.value.detail == "unsupported_media_type"


def test_allowed_video_is_returned_and_stays_private() -> None:
    owner = uuid.uuid7()
    video = asset("video/webm", owner)

    result = service.owned_asset(
        FakeSession(video),  # type: ignore[arg-type]
        video.asset_id,
        owner,
        allow_video=True,
    )

    assert result is video
    assert result.visibility == "private"


def test_allow_video_does_not_skip_the_owner_check() -> None:
    video = asset("video/mp4", uuid.uuid7())

    with pytest.raises(HTTPException) as caught:
        service.owned_asset(
            FakeSession(video),  # type: ignore[arg-type]
            video.asset_id,
            uuid.uuid7(),
            allow_video=True,
        )

    assert caught.value.detail == "media_not_found"
