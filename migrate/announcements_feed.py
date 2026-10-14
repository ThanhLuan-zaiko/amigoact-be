"""Migration: create announcements_feed and backfill public posts.

Non-destructive: `CREATE TABLE IF NOT EXISTS` for the DDL and upsert
inserts keyed by (bucket, post_id) for the data, so re-running is
always safe. Source rows come from `org_posts_feed` (tiny projection
rows, one full scan) and every candidate is re-verified against the
canonical `org_posts` table so drifted feed rows cannot leak into the
guest timeline.

    uv run python -m migrate.announcements_feed --dry-run
    uv run python -m migrate.announcements_feed
"""

from __future__ import annotations

import logging
import sys

from migrate import common

logger = logging.getLogger("migrate.announcements_feed")

TABLE = "announcements_feed"
BUCKET = "all"


def is_public_post(row) -> bool:
    """Same gate as PublicPostService._is_public: live announcement only."""
    return (
        row is not None
        and (row.status or "active") == "active"
        and row.deleted_at is None
        and row.revision_of is None
        and row.kind == "announcement"
    )


def backfill(session, keyspace: str, dry_run: bool) -> dict[str, int]:
    """Copy verified public announcement rows into the global feed."""
    stats = {"scanned": 0, "candidates": 0, "verified": 0, "written": 0}
    select_post = session.prepare(
        f"SELECT status, deleted_at, revision_of, kind "
        f"FROM {keyspace}.org_posts WHERE post_id = ?"
    )
    # Prepared on demand: dry-run may execute before the DDL lands.
    insert_feed = (
        None
        if dry_run
        else session.prepare(
            f"INSERT INTO {keyspace}.{TABLE} (bucket, post_id, org_id) "
            "VALUES (?, ?, ?)"
        )
    )
    scan = session.execute(
        f"SELECT org_id, post_id, kind FROM {keyspace}.org_posts_feed",
        timeout=60.0,
    )
    scan.fetch_size = common.FETCH_SIZE
    candidates = []
    for row in scan:
        stats["scanned"] += 1
        if row.kind == "announcement":
            stats["candidates"] += 1
            candidates.append(row)
    for row in candidates:
        post = session.execute(select_post, [row.post_id]).one()
        if not is_public_post(post):
            continue
        stats["verified"] += 1
        if insert_feed is not None:
            session.execute(insert_feed, [BUCKET, row.post_id, row.org_id])
            stats["written"] += 1
    return stats


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = common.parse_args(
        "Create + backfill announcements_feed (non-destructive).",
        argv,
    )
    try:
        cfg = common.resolve_config(args)
        statements = common.schema_statements(
            common.cql_file(args), cfg.keyspace, TABLE
        )
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
        existed = common.table_exists(session, cfg.keyspace, TABLE)
        logger.info(
            "%s %s.", TABLE, "already exists" if existed else "missing, will create"
        )
        for stmt in statements:
            logger.info("DDL: %s", " ".join(stmt.split()))
            if not cfg.dry_run:
                session.execute(stmt)
        stats = backfill(session, cfg.keyspace, cfg.dry_run)
        logger.info(
            "Backfill%s: scanned=%d candidates=%d verified=%d written=%d.",
            " (dry-run)" if cfg.dry_run else "",
            stats["scanned"],
            stats["candidates"],
            stats["verified"],
            stats["written"],
        )
        return 0
    except Exception as exc:
        logger.error("Migration failed: %s", exc)
        return 1
    finally:
        cluster.shutdown()


if __name__ == "__main__":
    sys.exit(main())
