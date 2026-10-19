"""Migration: backfill the org-scoped tag catalog from tag_names.

Reads every activities row (trashed included) and, per stored display
name, claims the (org_id, slug) catalog row via INSERT IF NOT EXISTS,
mirrors the winner's name into public_tag_directory, and upserts the
activity_tags_by_org edge. The legacy tags_by_slug table is never read
or touched. All writes are idempotent: re-running reports
catalog_created == 0.

    uv run python -m migrate.org_tags --dry-run
    uv run python -m migrate.org_tags
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone

from activities.model import tag_slug
from core.ids import uuid7
from migrate import activity_tags, common

logger = logging.getLogger("migrate.org_tags")

TABLES = (
    "tags_by_org",
    "activity_tags_by_org",
    "trashed_tag_edges_by_org",
    "public_tag_directory",
)

ACTIVITIES = (
    "SELECT id, org_id, tag_names, created_at FROM {ks}.activities"
)
CLAIM = (
    "INSERT INTO {ks}.tags_by_org"
    " (org_id, slug, tag_id, name, created_at, updated_at)"
    " VALUES (%s, %s, %s, %s, %s, %s) IF NOT EXISTS"
)
DIRECTORY = (
    "INSERT INTO {ks}.public_tag_directory (bucket, slug, org_id, name)"
    " VALUES ('all', %s, %s, %s)"
)
EDGE = (
    "INSERT INTO {ks}.activity_tags_by_org"
    " (org_id, tag_slug, activity_id) VALUES (%s, %s, %s)"
)


def _paged(session, cql: str):  # noqa: ANN001, ANN202
    from cassandra.query import SimpleStatement

    return session.execute(SimpleStatement(cql, fetch_size=common.FETCH_SIZE))


def create_tables(session, keyspace: str, cql_path, dry_run: bool) -> int:  # noqa: ANN001
    """Create the three tag tables from schemas.cql when missing."""
    created = 0
    for table in TABLES:
        if common.table_exists(session, keyspace, table):
            continue
        statements = common.schema_statements(cql_path, keyspace, table)
        for stmt in statements:
            if stmt.upper().startswith(("CREATE KEYSPACE", "USE")):
                continue
            logger.info(
                "%s DDL%s:\n%s",
                table, " (dry-run)" if dry_run else "", stmt,
            )
            if not dry_run:
                session.execute(stmt)
        created += 1
    return created


def _claim_catalog(
    session, keyspace: str, org_id, slug: str, name: str,  # noqa: ANN001
    created_at, now: datetime, dry_run: bool,  # noqa: ANN001
    catalog_exists: bool,
) -> tuple[str, bool]:
    """Return the canonical name plus whether the row was created."""
    if dry_run:
        if not catalog_exists:
            return name, True
        row = session.execute(
            f"SELECT name FROM {keyspace}.tags_by_org"
            " WHERE org_id = %s AND slug = %s",
            [org_id, slug],
        ).one()
        return (row.name if row else name), row is None
    applied = session.execute(
        CLAIM.format(ks=keyspace),
        (org_id, slug, uuid7(), name, created_at, now),
    )
    if applied.was_applied:
        return name, True
    existing = applied.one() if applied.current_rows else None
    return (
        getattr(existing, "name", None) or name
    ), False


def add_deleted_at(session, keyspace: str, dry_run: bool) -> bool:  # noqa: ANN001
    """ALTER tags_by_org for keyspaces created before soft delete."""
    if not common.table_exists(session, keyspace, "tags_by_org"):
        return False
    if activity_tags._column_exists(
        session, keyspace, "tags_by_org", "deleted_at"
    ):
        return False
    stmt = (
        f"ALTER TABLE {keyspace}.tags_by_org ADD deleted_at timestamp"
    )
    logger.info(
        "tags_by_org DDL%s:\n%s",
        " (dry-run)" if dry_run else "",
        stmt,
    )
    if not dry_run:
        session.execute(stmt)
    return True


def run(
    session, keyspace: str, dry_run: bool, cql_path=None  # noqa: ANN001
) -> dict[str, int]:
    """Backfill catalog, directory and edges; counters per write.

    Dry-run predicts a real run's counters exactly: it reads only the
    activities table, never the new tag tables (which may not exist
    yet), and tracks planned (org_id, slug) claims in memory.
    """
    created = create_tables(
        session,
        keyspace,
        cql_path or common.resolve_path("schemas.cql"),
        dry_run,
    )
    if created:
        logger.info(
            "created %d tag table%s%s.",
            created, "s" if created > 1 else "",
            " (dry-run)" if dry_run else "",
        )
    add_deleted_at(session, keyspace, dry_run)
    stats = {
        "activities": 0,
        "catalog_created": 0,
        "edges": 0,
        "directory": 0,
    }
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    catalog_exists = not dry_run or common.table_exists(
        session, keyspace, "tags_by_org"
    )
    planned: dict[tuple, str] = {}
    for row in _paged(session, ACTIVITIES.format(ks=keyspace)):
        if not row.tag_names:
            continue
        stats["activities"] += 1
        seen: set[str] = set()
        for name in row.tag_names:
            slug = tag_slug(name)
            if not slug or slug in seen:
                continue
            seen.add(slug)
            key = (row.org_id, slug)
            if key in planned:
                canonical = planned[key]
            else:
                canonical, created = _claim_catalog(
                    session, keyspace, row.org_id, slug, name,
                    row.created_at or now, now, dry_run, catalog_exists,
                )
                planned[key] = canonical
                if created:
                    stats["catalog_created"] += 1
            if not dry_run:
                session.execute(
                    DIRECTORY.format(ks=keyspace),
                    (slug, row.org_id, canonical),
                )
                session.execute(
                    EDGE.format(ks=keyspace),
                    (row.org_id, slug, row.id),
                )
            stats["directory"] += 1
            stats["edges"] += 1
    return stats


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = common.parse_args(
        "Backfill org tag catalogs, directory and edges from tag_names.",
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
        stats = run(
            session, cfg.keyspace, cfg.dry_run, common.cql_file(args)
        )
        logger.info(
            "org_tags: activities=%d catalog_created=%d"
            " edges=%d directory=%d%s.",
            stats["activities"], stats["catalog_created"],
            stats["edges"], stats["directory"],
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
