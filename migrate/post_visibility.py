"""Migration: add + backfill `visibility` on org_posts / org_posts_feed.

Adds the audience column to the canonical post table and its board feed
projection, backfills every NULL row from `kind` (announcement ->
public, anything else -> members) so pre-visibility data keeps its
exact old audience, then reconciles `announcements_feed` so it holds
exactly the live public posts (missing rows inserted, stale rows
dropped). Idempotent: ALTERs run only when the column is missing, the
backfill only touches NULL rows, and the timeline writes are
upsert/delete-by-key, so re-running is always safe.

    uv run python -m migrate.post_visibility --dry-run
    uv run python -m migrate.post_visibility
"""

from __future__ import annotations

import logging
import sys

from migrate import common

logger = logging.getLogger("migrate.post_visibility")

TABLES = {
    # table -> (primary-key columns for the UPDATE, scan columns)
    "org_posts": ("post_id", "post_id, kind, visibility"),
    "org_posts_feed": ("org_id, post_id", "org_id, post_id, kind, visibility"),
}
FEED_TABLE = "announcements_feed"
BUCKET = "all"


def _derive(kind) -> str:  # noqa: ANN001, ANN202
    """Legacy audience rule: announcements were public, the rest not."""
    return "public" if kind == "announcement" else "members"


def _effective(row) -> str:  # noqa: ANN001, ANN202
    """Audience of a row: explicit visibility wins, else kind-derived."""
    vis = getattr(row, "visibility", None)
    return vis if vis in ("public", "members") else _derive(row.kind)


def _is_live(row) -> bool:  # noqa: ANN001, ANN202
    """Same gate as PublicPostService._is_public minus the audience."""
    return (
        row is not None
        and (row.status or "active") == "active"
        and row.deleted_at is None
        and row.revision_of is None
    )


def column_exists(session, keyspace: str, table: str, column: str) -> bool:
    row = session.execute(
        "SELECT column_name FROM system_schema.columns "
        "WHERE keyspace_name = %s AND table_name = %s AND column_name = %s",
        [keyspace, table, column],
    ).one()
    return row is not None


def add_column(session, keyspace: str, table: str, dry_run: bool) -> bool:
    """Apply the ALTER when the column is still missing."""
    if column_exists(session, keyspace, table, "visibility"):
        return False
    stmt = f"ALTER TABLE {keyspace}.{table} ADD visibility text"
    logger.info("DDL: %s", stmt)
    if not dry_run:
        session.execute(stmt)
    return True


def backfill_table(
    session, keyspace: str, table: str, dry_run: bool
) -> dict[str, int]:
    """Set visibility on every row where it is still NULL."""
    stats = {"scanned": 0, "written": 0}
    pk_cols, select_cols = TABLES[table]
    if not column_exists(session, keyspace, table, "visibility"):
        # Dry-run before the ALTER: the column is not selectable yet and
        # every row counts as missing (NULL -> kind-derived).
        select_cols = select_cols.replace(", visibility", "")
    scan = session.execute(
        f"SELECT {select_cols} FROM {keyspace}.{table}", timeout=60.0
    )
    scan.fetch_size = common.FETCH_SIZE
    update = (
        None
        if dry_run
        else session.prepare(
            f"UPDATE {keyspace}.{table} SET visibility = ? "
            f"WHERE {pk_cols.replace(', ', ' = ? AND ')} = ?"
        )
    )
    for row in scan:
        stats["scanned"] += 1
        if getattr(row, "visibility", None) is not None:
            continue
        if update is not None:
            keys = [getattr(row, col.strip()) for col in pk_cols.split(",")]
            session.execute(update, [_derive(row.kind), *keys])
        stats["written"] += 1
    return stats


def reconcile_feed(
    session, keyspace: str, dry_run: bool
) -> dict[str, int]:
    """Make announcements_feed hold exactly the live public posts.

    Pass one inserts verified public posts missing from the timeline;
    pass two drops feed rows whose post turned members-only, draft,
    trashed or was deleted. Insert/delete by key, so it is idempotent.
    """
    stats = {"scanned": 0, "inserted": 0, "checked": 0, "removed": 0}
    post_cols = "status, deleted_at, revision_of, kind"
    if column_exists(session, keyspace, "org_posts", "visibility"):
        post_cols += ", visibility"
    insert_feed = None if dry_run else session.prepare(
        f"INSERT INTO {keyspace}.{FEED_TABLE} (bucket, post_id, org_id) "
        "VALUES (?, ?, ?)"
    )
    scan = session.execute(
        f"SELECT post_id, org_id, {post_cols} "
        f"FROM {keyspace}.org_posts",
        timeout=60.0,
    )
    scan.fetch_size = common.FETCH_SIZE
    for row in scan:
        stats["scanned"] += 1
        if not (_is_live(row) and _effective(row) == "public"):
            continue
        if insert_feed is not None:
            session.execute(insert_feed, [BUCKET, row.post_id, row.org_id])
        stats["inserted"] += 1
    select_post = session.prepare(
        f"SELECT {post_cols} FROM {keyspace}.org_posts WHERE post_id = ?"
    )
    delete_feed = None if dry_run else session.prepare(
        f"DELETE FROM {keyspace}.{FEED_TABLE} WHERE bucket = ? AND post_id = ?"
    )
    scan = session.execute(
        f"SELECT post_id FROM {keyspace}.{FEED_TABLE}", timeout=60.0
    )
    scan.fetch_size = common.FETCH_SIZE
    for row in scan:
        stats["checked"] += 1
        post = session.execute(select_post, [row.post_id]).one()
        if _is_live(post) and _effective(post) == "public":
            continue
        if delete_feed is not None:
            session.execute(delete_feed, [BUCKET, row.post_id])
        stats["removed"] += 1
    return stats


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = common.parse_args(
        "Add + backfill visibility on org_posts / org_posts_feed.",
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
        for table in TABLES:
            if add_column(session, cfg.keyspace, table, cfg.dry_run):
                logger.info("%s: visibility column added.", table)
            else:
                logger.info("%s: visibility column already present.", table)
            stats = backfill_table(session, cfg.keyspace, table, cfg.dry_run)
            logger.info(
                "%s backfill%s: scanned=%d written=%d.",
                table,
                " (dry-run)" if cfg.dry_run else "",
                stats["scanned"],
                stats["written"],
            )
        if not common.table_exists(session, cfg.keyspace, FEED_TABLE):
            logger.warning(
                "%s missing; run migrate.announcements_feed first.",
                FEED_TABLE,
            )
            return 0
        stats = reconcile_feed(session, cfg.keyspace, cfg.dry_run)
        logger.info(
            "%s reconcile%s: scanned=%d inserted=%d checked=%d removed=%d.",
            FEED_TABLE,
            " (dry-run)" if cfg.dry_run else "",
            stats["scanned"],
            stats["inserted"],
            stats["checked"],
            stats["removed"],
        )
        return 0
    except Exception as exc:
        logger.error("Migration failed: %s", exc)
        return 1
    finally:
        cluster.shutdown()


if __name__ == "__main__":
    sys.exit(main())
