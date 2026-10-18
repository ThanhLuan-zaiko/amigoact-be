"""Integration: migrate.media_ownership re-scopes legacy rows on a real keyspace."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

from chat.helpers import bucket_of, encode_attachments
from chat.dtos import AttachmentBrief
from chat.repository import CqlChatStore
from core.ids import uuid7
from core.media_rules import ATTACHMENT_ROLE, CHAT_OWNER, ORG_OWNER, POST_OWNER
from migrate import media_ownership
from orgs.media_repository import CqlMediaRepository
from orgs.model import Organization
from posts.model import OrgPost, OrgPostMedia
from rbac.model import AccessAuditByResource

NOW = datetime.now(timezone.utc)
UPLOADER = uuid7()


def _legacy_asset(media: CqlMediaRepository, org: UUID, role: str) -> UUID:
    asset_id = uuid7()
    media.create_asset(
        asset_id, org, f"orgs/{org}/{asset_id}.png", "image/png", 4, NOW,
        role, uploader_id=UPLOADER, original_name=f"{asset_id}.png", owner_type="organization")
    return asset_id


def _send_with_attachments(ks: str, room: UUID, *asset_ids: UUID) -> None:
    items = [
        AttachmentBrief(
            media_id=asset_id,
            url=f"/media/orgs/x/{asset_id}.png",
            mime="image/png",
            name="a.png",
            size_bytes=4,
        )
        for asset_id in asset_ids
    ]
    CqlChatStore(ks).create(
        room, bucket_of(NOW), uuid7(), UPLOADER, "", NOW,
        attachments_json=encode_attachments(items),
    )


def _post(org: UUID, blocks: list[dict] | None = None, cover: UUID | None = None) -> UUID:
    post_id = uuid7()
    OrgPost.create(
        post_id=post_id,
        org_id=org,
        author_id=UPLOADER,
        kind="announcement",
        title="T",
        body="",
        blocks_json=json.dumps(blocks or []),
        cover_media_id=cover,
        status="published",
        created_at=NOW,
        updated_at=NOW,
    )
    return post_id


def _seed(ks: str) -> dict[str, UUID]:
    media = CqlMediaRepository()
    org, other_org, room = uuid7(), uuid7(), uuid7()
    owner = uuid7()
    Organization.create(
        id=org, name="Org", slug=f"org-{org}", owner_id=owner,
        created_at=NOW, updated_at=NOW,
    )

    chat_sent = _legacy_asset(media, org, ATTACHMENT_ROLE)
    audit_only = _legacy_asset(media, org, ATTACHMENT_ROLE)
    block_ref = _legacy_asset(media, org, ATTACHMENT_ROLE)
    cover_ref = _legacy_asset(media, org, ATTACHMENT_ROLE)
    post_media_ref = _legacy_asset(media, org, ATTACHMENT_ROLE)
    brand_in_chat = _legacy_asset(media, org, "cover")
    plain_gallery = _legacy_asset(media, org, "gallery")
    chat_and_post = _legacy_asset(media, org, ATTACHMENT_ROLE)
    foreign_audit = _legacy_asset(media, org, ATTACHMENT_ROLE)

    _send_with_attachments(ks, room, chat_sent)
    _send_with_attachments(ks, org, brand_in_chat, chat_and_post)
    AccessAuditByResource.create(
        resource_id=audit_only, occurred_at=NOW, actor_id=UPLOADER,
        org_id=org, action="chat.attach", result="allowed",
    )
    AccessAuditByResource.create(
        resource_id=foreign_audit, occurred_at=NOW, actor_id=UPLOADER,
        org_id=other_org, action="chat.attach", result="allowed",
    )
    post = _post(
        org,
        blocks=[
            {"type": "image", "asset_id": str(block_ref), "caption": ""},
            {"type": "image", "asset_id": str(chat_and_post), "caption": ""},
        ],
    )
    _post(org, cover=cover_ref)
    OrgPostMedia.create(post_id=post, position=0, asset_id=post_media_ref)
    Organization.objects(id=org).update(cover_media_id=brand_in_chat)
    return {
        "org": org,
        "room": room,
        "chat_sent": chat_sent,
        "audit_only": audit_only,
        "block_ref": block_ref,
        "cover_ref": cover_ref,
        "post_media_ref": post_media_ref,
        "brand_in_chat": brand_in_chat,
        "plain_gallery": plain_gallery,
        "chat_and_post": chat_and_post,
        "foreign_audit": foreign_audit,
    }


def _owner(asset_id: UUID) -> tuple[str, UUID, str]:
    row = CqlMediaRepository().get_asset(asset_id)
    return row.owner_type, row.owner_id, row.role


def _plain_session():  # noqa: ANN202
    """Plain driver session, as migrate.common.connect builds it.

    cqlengine's shared session reads rows as dicts; the migrator reads them
    by attribute, exactly like the CLI does on a plain session.
    """
    from cassandra.cluster import Cluster
    from cassandra.io.asyncioreactor import AsyncioConnection

    cluster = Cluster(
        ["127.0.0.1"],
        port=9042,
        protocol_version=4,
        connection_class=AsyncioConnection,
        connect_timeout=10.0,
    )
    return cluster, cluster.connect()


def test_dry_run_writes_nothing_then_apply_relabels_and_is_idempotent(
    clean_tables: str,
) -> None:
    ids = _seed(clean_tables)
    cluster, session = _plain_session()
    try:
        dry = media_ownership.run(session, clean_tables, dry_run=True)
        assert dry == {"planned": 5, "applied": 0, "skipped": 3, "unproven": 0}
        assert _owner(ids["chat_sent"])[0] == ORG_OWNER

        applied = media_ownership.run(session, clean_tables, dry_run=False)
        assert applied == {"planned": 5, "applied": 5, "skipped": 3, "unproven": 0}

        assert _owner(ids["chat_sent"]) == (CHAT_OWNER, ids["room"], ATTACHMENT_ROLE)
        assert _owner(ids["audit_only"]) == (CHAT_OWNER, ids["org"], ATTACHMENT_ROLE)
        for key in ("block_ref", "cover_ref", "post_media_ref"):
            assert _owner(ids[key]) == (POST_OWNER, ids["org"], ATTACHMENT_ROLE)

        assert _owner(ids["brand_in_chat"]) == (ORG_OWNER, ids["org"], "cover")
        assert _owner(ids["plain_gallery"]) == (ORG_OWNER, ids["org"], "gallery")
        assert _owner(ids["chat_and_post"]) == (ORG_OWNER, ids["org"], ATTACHMENT_ROLE)
        assert _owner(ids["foreign_audit"]) == (ORG_OWNER, ids["org"], ATTACHMENT_ROLE)

        again = media_ownership.run(session, clean_tables, dry_run=False)
        assert again["planned"] == 0
        assert again["applied"] == 0
    finally:
        cluster.shutdown()
