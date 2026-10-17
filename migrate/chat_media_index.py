"""Migration: org_room_media shared-item index (create + backfill).

Creates the index tables from schemas.cql — the base tab view, the
per-author mirror behind the sender filter, and the (kind, author)
presence rows feeding its option list — then backfills one row per
attachment/extracted link already stored in org_room_messages so older
rooms show their full history in the info panel. Inserts are plain
PK-upserts, so re-running after a partial pass is always safe; link
URLs are re-encrypted with the same body cipher before they land.

    uv run python -m migrate.chat_media_index --dry-run
    uv run python -m migrate.chat_media_index
"""

from __future__ import annotations

import logging
import sys

from migrate import common

logger = logging.getLogger("migrate.chat_media_index")

TABLES = (
    "org_room_media",
    "org_room_media_by_author",
    "org_room_media_authors",
)
SOURCE = "org_room_messages"
SELECT = (
    f"SELECT room_id, bucket, message_id, author_id, body,"
    f" attachments_json, created_at FROM %s.{SOURCE}"
)
INSERT = (
    f"INSERT INTO %s.{TABLES[0]} (room_id, bucket, kind, message_id,"
    " item_index, author_id, media_id, url, mime, name, size_bytes,"
    " created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)
INSERT_BY_AUTHOR = (
    f"INSERT INTO %s.{TABLES[1]} (room_id, kind, author_id, bucket,"
    " message_id, item_index, media_id, url, mime, name, size_bytes,"
    " created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)
INSERT_AUTHOR = (
    f"INSERT INTO %s.{TABLES[2]} (room_id, kind, author_id, last_at)"
    " VALUES (?, ?, ?, ?)"
)


def create_tables(session, cfg: common.Config, cql_path) -> None:  # noqa: ANN001, ANN202
    for table in TABLES:
        if common.table_exists(session, cfg.keyspace, table):
            logger.info("%s: table already present.", table)
            continue
        stmts = common.schema_statements(cql_path, cfg.keyspace, table)
        logger.info(
            "%s: creating table%s.", table, " (dry-run)" if cfg.dry_run else ""
        )
        for stmt in stmts:
            if stmt.upper().startswith(("CREATE KEYSPACE", "USE")):
                continue
            if not cfg.dry_run:
                session.execute(stmt)


def _cipher():
    """Body cipher for link extraction; skipped if settings missing."""
    try:
        from chat.crypto import chat_cipher
        from core.config import get_settings

        return chat_cipher(get_settings())
    except Exception as exc:
        logger.warning("cipher unavailable (%s); links backfill skipped.", exc)
        return None


def backfill(session, cfg: common.Config) -> dict[str, int]:
    """Rebuild index rows for every stored message (idempotent)."""
    from chat.helpers import build_index_items, decode_attachments

    cipher = _cipher()
    if not common.table_exists(session, cfg.keyspace, SOURCE):
        logger.warning("%s missing; nothing to backfill.", SOURCE)
        return {"scanned": 0, "indexed": 0}
    query = session.prepare(SELECT % cfg.keyspace)
    query.fetch_size = common.FETCH_SIZE
    writes = None
    if not cfg.dry_run:
        writes = (
            session.prepare(INSERT % cfg.keyspace),
            session.prepare(INSERT_BY_AUTHOR % cfg.keyspace),
            session.prepare(INSERT_AUTHOR % cfg.keyspace),
        )
    stats = {"scanned": 0, "indexed": 0}
    for row in session.execute(query):
        stats["scanned"] += 1
        attachments = decode_attachments(
            getattr(row, "attachments_json", None)
        )
        body = cipher.decrypt(row.body) if cipher else (row.body or "")
        items = build_index_items(attachments, body, cipher)
        seen_kinds: set[str] = set()
        for item in items:
            stats["indexed"] += 1
            if writes is None:
                continue
            base, by_author, author = writes
            session.execute(
                base,
                (
                    row.room_id, row.bucket, item.kind, row.message_id,
                    item.item_index, row.author_id, item.media_id,
                    item.url, item.mime or None, item.name or None,
                    item.size_bytes or None, row.created_at,
                ),
            )
            session.execute(
                by_author,
                (
                    row.room_id, item.kind, row.author_id, row.bucket,
                    row.message_id, item.item_index, item.media_id,
                    item.url, item.mime or None, item.name or None,
                    item.size_bytes or None, row.created_at,
                ),
            )
            if item.kind not in seen_kinds:
                seen_kinds.add(item.kind)
                session.execute(
                    author,
                    (row.room_id, item.kind, row.author_id, row.created_at),
                )
        if stats["scanned"] % 5000 == 0:
            logger.info("scanned=%d indexed=%d...", *stats.values())
    return stats


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = common.parse_args(
        "Create org_room_media tables and backfill them from"
        " org_room_messages.",
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
        create_tables(session, cfg, common.cql_file(args))
        stats = backfill(session, cfg)
        logger.info(
            "backfill: scanned=%d indexed=%d%s.",
            stats["scanned"], stats["indexed"],
            " (dry-run)" if cfg.dry_run else "",
        )
        return 0
    except Exception as exc:
        logger.error("Migration failed: %s", exc)
        return 1
    finally:
        cluster.shutdown()


if __name__ == "__main__":
    sys.exit(main())
