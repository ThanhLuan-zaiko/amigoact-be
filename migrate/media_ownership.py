"""Migration: re-scope legacy chat and board uploads out of the gallery.

Chat attachments and board-editor images used to be stored as org
gallery media (owner_type 'organization', role 'attachment'), and every
new attachment upload demoted the earlier ones to 'gallery', leaking them
into /manage/orgs and the public org surfaces. This pass re-labels each
proven row with the bounded context that owns it:

- chat evidence: listed in a message's attachments_json, indexed in
  org_room_media, or audited as 'chat.attach'
  -> owner_type 'chat', owner_id = the room id (audit-only rows fall
  back to the audited org id, i.e. the general room), role 'attachment';
- board evidence: linked by org_post_media, cover_media_id or a media
  block of a post in the same org
  -> owner_type 'post' (owner_id stays the org), role 'attachment'.

Brand assets (cover/logo role or an org brand pointer), rows with both
kinds of evidence, audit rows from another org and non gallery or
attachment roles are reported and left untouched for a manual decision.
Only conditional UPDATEs (IF EXISTS) on existing media_assets rows are
issued: nothing is deleted, the stale media_by_owner feed rows are
ignored by the owner-type filter on every gallery read, and rows already
owned by another context are skipped, so re-running is a no-op.

    uv run python -m migrate.media_ownership --dry-run
    uv run python -m migrate.media_ownership
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from uuid import UUID

from core.media_rules import (
    ATTACHMENT_ROLE,
    BRAND_ROLES,
    CHAT_OWNER,
    ORG_OWNER,
    POST_OWNER,
)
from migrate import common

logger = logging.getLogger("migrate.media_ownership")

ASSETS = (
    "SELECT asset_id, owner_id, owner_type, role, original_name"
    " FROM {ks}.media_assets"
)
MESSAGES = "SELECT room_id, attachments_json FROM {ks}.org_room_messages"
ROOM_MEDIA = "SELECT room_id, media_id FROM {ks}.org_room_media"
POSTS = (
    "SELECT post_id, org_id, cover_media_id, blocks_json"
    " FROM {ks}.org_posts"
)
POST_MEDIA = "SELECT post_id, asset_id FROM {ks}.org_post_media"
ORGS = "SELECT id, cover_media_id, logo_media_id FROM {ks}.organizations"
AUDIT = (
    "SELECT org_id, action FROM {ks}.access_audit_by_resource"
    " WHERE resource_id = ?"
)
UPDATE = (
    "UPDATE {ks}.media_assets SET owner_type = ?, owner_id = ?, role = ?,"
    " updated_at = ? WHERE asset_id = ? IF EXISTS"
)
_LEGACY_ROLES = ("gallery", ATTACHMENT_ROLE)


@dataclass(frozen=True)
class Change:
    """One planned media_assets re-label."""

    asset_id: UUID
    owner_type: str
    owner_id: UUID
    role: str
    before: str
    evidence: str


@dataclass
class Plan:
    """Planned changes plus the rows a human has to look at."""

    changes: list[Change]
    skipped: list[str]
    unproven_attachments: int


def _paged(session, cql: str):  # noqa: ANN001, ANN202
    from cassandra.query import SimpleStatement

    return session.execute(SimpleStatement(cql, fetch_size=common.FETCH_SIZE))


def _has(session, keyspace: str, table: str) -> bool:  # noqa: ANN001
    return common.table_exists(session, keyspace, table)


def _block_asset_ids(raw: str | None) -> list[UUID]:
    """asset_id of every image/video block in a stored blocks_json."""
    if not raw:
        return []
    try:
        blocks = json.loads(raw)
    except ValueError:
        return []
    out: list[UUID] = []
    for block in blocks if isinstance(blocks, list) else []:
        value = block.get("asset_id") if isinstance(block, dict) else None
        if not value:
            continue
        try:
            out.append(UUID(str(value)))
        except ValueError:
            continue
    return out


def chat_rooms(session, keyspace: str) -> dict[UUID, UUID]:  # noqa: ANN001
    """media_id -> room_id for every attachment a stored message carries."""
    from chat.helpers import decode_attachments

    rooms: dict[UUID, UUID] = {}
    if _has(session, keyspace, "org_room_messages"):
        for row in _paged(session, MESSAGES.format(ks=keyspace)):
            for item in decode_attachments(row.attachments_json):
                rooms.setdefault(item.media_id, row.room_id)
    if _has(session, keyspace, "org_room_media"):
        for row in _paged(session, ROOM_MEDIA.format(ks=keyspace)):
            if row.media_id is not None:
                rooms.setdefault(row.media_id, row.room_id)
    return rooms


def post_refs(session, keyspace: str) -> dict[UUID, set[UUID]]:  # noqa: ANN001
    """asset_id -> org ids of the posts that reference it."""
    refs: dict[UUID, set[UUID]] = {}
    post_org: dict[UUID, UUID] = {}
    if _has(session, keyspace, "org_posts"):
        for row in _paged(session, POSTS.format(ks=keyspace)):
            post_org[row.post_id] = row.org_id
            ids = _block_asset_ids(row.blocks_json)
            if row.cover_media_id is not None:
                ids.append(row.cover_media_id)
            for asset_id in ids:
                refs.setdefault(asset_id, set()).add(row.org_id)
    if _has(session, keyspace, "org_post_media"):
        for row in _paged(session, POST_MEDIA.format(ks=keyspace)):
            org_id = post_org.get(row.post_id)
            if org_id is not None:
                refs.setdefault(row.asset_id, set()).add(org_id)
    return refs


def brand_ids(session, keyspace: str) -> set[UUID]:  # noqa: ANN001
    """Every asset an org currently points at as its cover or logo."""
    ids: set[UUID] = set()
    for row in _paged(session, ORGS.format(ks=keyspace)):
        for value in (row.cover_media_id, row.logo_media_id):
            if value is not None:
                ids.add(value)
    return ids


def audit_org(session, statement, asset_id: UUID) -> UUID | None:  # noqa: ANN001
    """Org id of a 'chat.attach' audit row for this asset, if any."""
    for row in session.execute(statement, (asset_id,)):
        if row.action == "chat.attach" and row.org_id is not None:
            return row.org_id
    return None


def plan(session, keyspace: str) -> Plan:  # noqa: ANN001
    """Read-only pass: decide every re-label, write nothing."""
    rooms = chat_rooms(session, keyspace)
    refs = post_refs(session, keyspace)
    brands = brand_ids(session, keyspace)
    audit = (
        session.prepare(AUDIT.format(ks=keyspace))
        if _has(session, keyspace, "access_audit_by_resource")
        else None
    )
    result = Plan(changes=[], skipped=[], unproven_attachments=0)
    for row in _paged(session, ASSETS.format(ks=keyspace)):
        if (row.owner_type or ORG_OWNER) != ORG_OWNER:
            continue
        role = row.role or "gallery"
        label = f"{row.asset_id} ({ORG_OWNER}/{role}, {row.original_name!r})"
        room_id = rooms.get(row.asset_id)
        evidence = "chat message"
        if room_id is None and audit is not None:
            audited = audit_org(session, audit, row.asset_id)
            if audited is not None and audited != row.owner_id:
                result.skipped.append(f"{label}: chat.attach audit from org {audited}")
                continue
            room_id, evidence = audited, "chat.attach audit"
        in_post = row.owner_id in refs.get(row.asset_id, set())
        if room_id is None and not in_post:
            if role == ATTACHMENT_ROLE:
                result.unproven_attachments += 1
            continue
        before = f"{ORG_OWNER}/{role}"
        if role in BRAND_ROLES or row.asset_id in brands:
            result.skipped.append(f"{label}: brand asset")
        elif room_id is not None and in_post:
            result.skipped.append(f"{label}: used by chat and a post")
        elif role not in _LEGACY_ROLES:
            result.skipped.append(f"{label}: role {role!r}")
        elif room_id is not None:
            result.changes.append(
                Change(
                    row.asset_id, CHAT_OWNER, room_id, ATTACHMENT_ROLE,
                    before, evidence,
                )
            )
        else:
            result.changes.append(
                Change(
                    row.asset_id, POST_OWNER, row.owner_id, ATTACHMENT_ROLE,
                    before, "post reference",
                )
            )
    return result


def apply(session, keyspace: str, changes: list[Change]) -> int:  # noqa: ANN001
    """Write the planned re-labels; rows deleted meanwhile stay deleted."""
    from core.security import utcnow

    statement = session.prepare(UPDATE.format(ks=keyspace))
    now = utcnow()
    applied = 0
    for change in changes:
        outcome = session.execute(
            statement,
            (
                change.owner_type, change.owner_id, change.role, now,
                change.asset_id,
            ),
        )
        if outcome.was_applied:
            applied += 1
    return applied


def run(session, keyspace: str, dry_run: bool) -> dict[str, int]:  # noqa: ANN001
    """Plan, log every decision, then apply unless dry_run."""
    result = plan(session, keyspace)
    suffix = " (dry-run)" if dry_run else ""
    for change in result.changes:
        logger.info(
            "%s: %s -> %s/%s owner_id=%s [evidence: %s]%s",
            change.asset_id, change.before, change.owner_type, change.role,
            change.owner_id, change.evidence, suffix,
        )
    for note in result.skipped:
        logger.warning("left as is: %s", note)
    if result.unproven_attachments:
        logger.info(
            "%d attachment-role rows without chat/post evidence left as is"
            " (the owner-type filter already hides them).",
            result.unproven_attachments,
        )
    applied = 0 if dry_run else apply(session, keyspace, result.changes)
    return {
        "planned": len(result.changes),
        "applied": applied,
        "skipped": len(result.skipped),
        "unproven": result.unproven_attachments,
    }


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = common.parse_args(
        "Re-scope legacy chat attachments and board uploads out of the"
        " org gallery (owner_type chat/post).",
        argv,
    )
    try:
        cfg = common.resolve_config(args)
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 2
    logger.info(
        "Target keyspace '%s' at %s:%d.",
        cfg.keyspace, ",".join(cfg.hosts), cfg.port,
    )
    logger.info("ScyllaDB probe: %s.", common.probe(cfg))
    try:
        cluster, session = common.connect(cfg)
    except Exception as exc:
        logger.error("Cannot reach ScyllaDB: %s", exc)
        return 1
    try:
        stats = run(session, cfg.keyspace, cfg.dry_run)
        logger.info(
            "media_ownership: planned=%d applied=%d skipped=%d unproven=%d%s.",
            stats["planned"], stats["applied"], stats["skipped"],
            stats["unproven"], " (dry-run)" if cfg.dry_run else "",
        )
        return 0
    except Exception as exc:
        logger.error("Migration failed: %s", exc)
        return 1
    finally:
        cluster.shutdown()


if __name__ == "__main__":
    sys.exit(main())
