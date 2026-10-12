"""Unit tests for the article block model and request validation."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from posts.blocks import (
    blocks_to_text,
    compact_blocks,
    dump_blocks,
    has_content,
    load_blocks,
    media_refs,
)
from posts.schemas import CreatePostRequest, UpdatePostRequest
from tests.unit.workspace_fakes import _uid


def _req(**payload):  # noqa: ANN003, ANN202
    return CreatePostRequest.model_validate(payload)


def test_discriminated_blocks_round_trip() -> None:
    asset = _uid()
    req = _req(
        title="Story",
        blocks=[
            {"type": "heading", "text": " Part 1 ", "level": 3},
            {"type": "paragraph", "text": "Hello"},
            {"type": "image", "asset_id": str(asset), "caption": "Pic"},
            {"type": "list", "items": ["a", " ", "b"], "ordered": True},
            {"type": "quote", "text": "Q", "cite": "Me"},
            {"type": "divider"},
        ],
    )
    kept = compact_blocks(req.blocks)
    stored = load_blocks(dump_blocks(kept))
    assert stored[0] == {"type": "heading", "text": "Part 1", "level": 3}
    assert stored[3]["items"] == ["a", "b"]
    assert media_refs(kept) == [(asset, "image")]
    assert blocks_to_text(kept) == "Part 1\n\nHello\n\nPic\n\na\nb\n\nQ"


def test_unknown_or_unsafe_blocks_are_rejected() -> None:
    with pytest.raises(ValidationError):
        _req(blocks=[{"type": "html", "text": "<script>"}])
    with pytest.raises(ValidationError):
        _req(blocks=[{"type": "image", "asset_id": "not-a-uuid"}])
    with pytest.raises(ValidationError):
        _req(blocks=[{"type": "heading", "text": "x", "level": 1}])


def test_publish_and_draft_content_rules() -> None:
    with pytest.raises(ValidationError):
        _req(blocks=[{"type": "paragraph", "text": " "}])
    with pytest.raises(ValidationError):
        _req(kind="announcement", body="x")
    with pytest.raises(ValidationError):
        _req(status="draft")
    assert _req(status="draft", title="Idea").status == "draft"
    assert _req(body="legacy").blocks == []
    assert has_content(_req(blocks=[{"type": "video", "asset_id": str(_uid())}]).blocks)


def test_update_cover_presence_and_legacy_body() -> None:
    with pytest.raises(ValidationError):
        UpdatePostRequest.model_validate({"title": "t"})
    plain = UpdatePostRequest.model_validate({"title": "t", "blocks": []})
    assert plain.touches_cover is False
    cleared = UpdatePostRequest.model_validate(
        {"blocks": [], "cover_media_id": None}
    )
    assert cleared.touches_cover is True


def test_corrupt_stored_json_reads_empty() -> None:
    assert load_blocks("") == []
    assert load_blocks("{not json") == []
    assert load_blocks(json.dumps([{"type": "nope"}])) == []
