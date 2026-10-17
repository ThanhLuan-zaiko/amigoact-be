"""Migration: chat phase 1+2 columns and the reactions table.

Adds, all additive and idempotent (re-running is always safe):
- org_room_messages: reply_to_id/author/body, edited_at,
  attachments_json, mentions_json (phase 1 write path + phase 2
  mentions; bodies may hold AES-GCM ciphertext going forward).
- users: last_seen_at (presence transition stamp).
- org_room_reactions: new table ((room_id,message_id),emoji,user_id).

ALTER TABLE ... ADD is guarded by a system_schema.columns probe so a
re-run never fails on already-applied columns.

    uv run python -m migrate.chat_phase2 --dry-run
    uv run python -m migrate.chat_phase2
"""

from __future__ import annotations

import logging
import sys

from migrate import common

logger = logging.getLogger("migrate.chat_phase2")

REACTION_TABLE = "org_room_reactions"

# (table, [(column, cql_type)]) — every entry is one ALTER ... ADD.
NEW_COLUMNS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "org_room_messages",
        [
            ("reply_to_id", "uuid"),
            ("reply_to_author", "text"),
            ("reply_to_body", "text"),
            ("edited_at", "timestamp"),
            ("attachments_json", "text"),
            ("mentions_json", "text"),
        ],
    ),
    ("users", [("last_seen_at", "timestamp")]),
]


def column_exists(session, keyspace: str, table: str, column: str) -> bool:  # noqa: ANN001, ANN202
    row = session.execute(
        "SELECT column_name FROM system_schema.columns "
        "WHERE keyspace_name = %s AND table_name = %s AND column_name = %s",
        [keyspace, table, column],
    ).one()
    return row is not None


def add_columns(session, cfg: common.Config) -> dict[str, int]:
    stats = {"added": 0, "skipped": 0}
    for table, columns in NEW_COLUMNS:
        if not common.table_exists(session, cfg.keyspace, table):
            logger.warning("%s missing; skipping its columns.", table)
            continue
        for column, cql_type in columns:
            if column_exists(session, cfg.keyspace, table, column):
                stats["skipped"] += 1
                continue
            stmt = (
                f"ALTER TABLE {cfg.keyspace}.{table} "
                f"ADD {column} {cql_type}"
            )
            logger.info(
                "%s.%s: ADD %s %s%s.",
                table, column, column, cql_type,
                " (dry-run)" if cfg.dry_run else "",
            )
            if not cfg.dry_run:
                session.execute(stmt)
            stats["added"] += 1
    return stats


def create_reactions(session, cfg: common.Config, cql_path) -> None:  # noqa: ANN001, ANN202
    if common.table_exists(session, cfg.keyspace, REACTION_TABLE):
        logger.info("%s: table already present.", REACTION_TABLE)
        return
    stmts = common.schema_statements(cql_path, cfg.keyspace, REACTION_TABLE)
    logger.info(
        "%s: creating table%s.",
        REACTION_TABLE, " (dry-run)" if cfg.dry_run else "",
    )
    for stmt in stmts:
        if stmt.upper().startswith(("CREATE KEYSPACE", "USE")):
            continue
        if not cfg.dry_run:
            session.execute(stmt)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = common.parse_args(
        "Add chat phase 1+2 columns and org_room_reactions.", argv
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
        stats = add_columns(session, cfg)
        create_reactions(session, cfg, common.cql_file(args))
        logger.info(
            "columns: added=%d skipped=%d (already present)%s.",
            stats["added"], stats["skipped"],
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
