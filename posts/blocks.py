"""Article block model: typed content blocks stored as JSON on the post.

Blocks are the long-form body of a board article (paragraph, heading,
quote, list, image, video, divider). Media blocks only carry an org
asset id; URLs are resolved at read time through the post media links so
a stored article never embeds raw URLs or HTML (no XSS surface).
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal, Union
from uuid import UUID

from pydantic import BaseModel, Field, TypeAdapter, field_validator

MAX_BLOCKS = 200
MAX_MEDIA_BLOCKS = 40
MAX_BODY_CHARS = 20000


def _trim(value: object) -> object:
    return value.strip() if isinstance(value, str) else value


class ParagraphBlock(BaseModel):
    type: Literal["paragraph"]
    text: str = Field(default="", max_length=10000)

    _text = field_validator("text", mode="before")(_trim)  # noqa: SLF001


class HeadingBlock(BaseModel):
    type: Literal["heading"]
    text: str = Field(default="", max_length=200)
    level: Literal[2, 3] = 2

    _text = field_validator("text", mode="before")(_trim)  # noqa: SLF001


class QuoteBlock(BaseModel):
    type: Literal["quote"]
    text: str = Field(default="", max_length=2000)
    cite: str = Field(default="", max_length=200)

    _text = field_validator("text", "cite", mode="before")(_trim)  # noqa: SLF001


class ListBlock(BaseModel):
    type: Literal["list"]
    ordered: bool = False
    items: list[Annotated[str, Field(max_length=1000)]] = Field(
        default_factory=list, max_length=50
    )

    @field_validator("items", mode="before")
    @classmethod
    def _trim_items(cls, value: object) -> object:
        if isinstance(value, list):
            return [_trim(item) for item in value]
        return value


class ImageBlock(BaseModel):
    type: Literal["image"]
    asset_id: UUID
    caption: str = Field(default="", max_length=300)

    _caption = field_validator("caption", mode="before")(_trim)  # noqa: SLF001


class VideoBlock(BaseModel):
    type: Literal["video"]
    asset_id: UUID
    caption: str = Field(default="", max_length=300)

    _caption = field_validator("caption", mode="before")(_trim)  # noqa: SLF001


class DividerBlock(BaseModel):
    type: Literal["divider"]


Block = Annotated[
    Union[
        ParagraphBlock,
        HeadingBlock,
        QuoteBlock,
        ListBlock,
        ImageBlock,
        VideoBlock,
        DividerBlock,
    ],
    Field(discriminator="type"),
]

_BLOCKS = TypeAdapter(list[Block])


def block_text(block: BaseModel) -> str:
    """Plain-text projection of one block (media blocks keep captions)."""
    if isinstance(block, ListBlock):
        return "\n".join(item for item in block.items if item)
    if isinstance(block, (ImageBlock, VideoBlock)):
        return block.caption
    return str(getattr(block, "text", "") or "")


def compact_blocks(blocks: list[Any]) -> list[Any]:
    """Drop empty text blocks; media and dividers always survive."""
    kept: list[Any] = []
    for block in blocks:
        if isinstance(block, (ImageBlock, VideoBlock, DividerBlock)):
            kept.append(block)
        elif isinstance(block, ListBlock):
            items = [item for item in block.items if item]
            if items:
                kept.append(block.model_copy(update={"items": items}))
        elif block_text(block):
            kept.append(block)
    return kept


def has_content(blocks: list[Any]) -> bool:
    """True when the article carries readable text or any media block."""
    return any(
        isinstance(block, (ImageBlock, VideoBlock)) or block_text(block)
        for block in blocks
    )


def blocks_to_text(blocks: list[Any]) -> str:
    """Searchable/plain body derived from the blocks (capped)."""
    parts = [block_text(block) for block in blocks]
    return "\n\n".join(part for part in parts if part)[:MAX_BODY_CHARS]


def media_refs(blocks: list[Any]) -> list[tuple[UUID, str]]:
    """(asset_id, kind) for every media block, in document order."""
    refs: list[tuple[UUID, str]] = []
    for block in blocks:
        if isinstance(block, ImageBlock):
            refs.append((block.asset_id, "image"))
        elif isinstance(block, VideoBlock):
            refs.append((block.asset_id, "video"))
    return refs


def dump_blocks(blocks: list[Any]) -> str:
    """Serialize validated blocks for the blocks_json column."""
    if not blocks:
        return ""
    return json.dumps(
        _BLOCKS.dump_python(blocks, mode="json"), ensure_ascii=False
    )


def load_blocks(raw: str | None) -> list[dict[str, Any]]:
    """Parse stored JSON back into plain dicts; corrupt rows read empty."""
    if not raw:
        return []
    try:
        parsed = _BLOCKS.validate_python(json.loads(raw))
    except (ValueError, TypeError):
        return []
    return _BLOCKS.dump_python(parsed, mode="json")
