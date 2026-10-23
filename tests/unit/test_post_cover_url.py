"""Cover lookup: the cover image, then the first other image."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

from posts.cover_url import CqlPostCovers


def _asset(asset_id: UUID, mime: str, file_url: str):
    return SimpleNamespace(asset_id=asset_id, mime=mime, file_url=file_url)


class _Media:
    def __init__(self) -> None:
        self.assets: dict[UUID, SimpleNamespace] = {}

    def get_asset(self, asset_id: UUID):
        return self.assets.get(asset_id)


class _Posts:
    def __init__(self) -> None:
        self.links: list[SimpleNamespace] = []

    def list_media(self, post_id: UUID) -> list[SimpleNamespace]:
        return [link for link in self.links if link.post_id == post_id]


def test_cover_image_wins_over_later_images() -> None:
    media = _Media()
    posts = _Posts()
    cover = uuid4()
    other = uuid4()
    post_id = uuid4()
    media.assets[cover] = _asset(cover, "image/jpeg", "orgs/cover.jpg")
    media.assets[other] = _asset(other, "image/jpeg", "orgs/other.jpg")
    posts.links.append(SimpleNamespace(post_id=post_id, asset_id=other))
    row = SimpleNamespace(post_id=post_id, cover_media_id=cover, blocks_json="")

    assert CqlPostCovers(posts, media).cover_of(row) == "/media/orgs/cover.jpg"


def test_video_cover_falls_through_to_the_first_image() -> None:
    media = _Media()
    posts = _Posts()
    cover = uuid4()
    image = uuid4()
    post_id = uuid4()
    media.assets[cover] = _asset(cover, "video/mp4", "orgs/clip.mp4")
    media.assets[image] = _asset(image, "image/png", "orgs/still.png")
    posts.links.append(SimpleNamespace(post_id=post_id, asset_id=image))
    row = SimpleNamespace(post_id=post_id, cover_media_id=cover, blocks_json="")

    assert CqlPostCovers(posts, media).cover_of(row) == "/media/orgs/still.png"


def test_image_block_is_used_when_nothing_is_linked() -> None:
    media = _Media()
    asset_id = uuid4()
    media.assets[asset_id] = _asset(asset_id, "image/webp", "orgs/block.webp")
    row = SimpleNamespace(
        post_id=uuid4(),
        cover_media_id=None,
        blocks_json=f'[{{"type": "image", "asset_id": "{asset_id}"}}]',
    )

    assert CqlPostCovers(_Posts(), media).cover_of(row) == "/media/orgs/block.webp"


def test_missing_image_is_none() -> None:
    row = SimpleNamespace(post_id=uuid4(), cover_media_id=None, blocks_json="")
    assert CqlPostCovers(_Posts(), _Media()).cover_of(row) is None
