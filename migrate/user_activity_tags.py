"""Migration: personal activity-tag edges.

Creates activity_tags_by_user and user_activity_tag_sets. Then, for each
live activity, claims its tag names onto the creator and records the
edges. Existing personal spellings are kept. Idempotent.

    uv run python -m migrate.user_activity_tags --dry-run
    uv run python -m migrate.user_activity_tags
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from uuid import UUID

from core.tags import tag_slug
from migrate import common

logger = logging.getLogger("migrate.user_activity_tags")

TABLES = (
    "tags_by_user",
    "activity_tags_by_user",
    "user_activity_tag_sets",
)
_MAX_NAME = 40
_MAX_TAGS = 10


def create_tables(session, cfg: common.Config, cql_path) -> dict[str, int]:  # noqa: ANN001, ANN202
    stats = {"created": 0, "skipped": 0}
    for table in TABLES:
        if common.table_exists(session, cfg.keyspace, table):
            stats["skipped"] += 1
            continue
        stmts = common.schema_statements(cql_path, cfg.keyspace, table)
        logger.info(
            "%s: creating table%s.",
            table, " (dry-run)" if cfg.dry_run else "",
        )
        for stmt in stmts:
            if stmt.upper().startswith(("CREATE KEYSPACE", "USE")):
                continue
            if not cfg.dry_run:
                session.execute(stmt)
        stats["created"] += 1
    return stats


def _paged(session, cql: str):  # noqa: ANN001, ANN202
    from cassandra.query import SimpleStatement

    return session.execute(SimpleStatement(cql, fetch_size=common.FETCH_SIZE))


def _one(session, cql: str, params: list):  # noqa: ANN001, ANN202
    return session.execute(cql, params).one()


def _pairs(names: list[str] | None) -> list[tuple[str, str]]:
    picked: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in names or []:
        if not isinstance(raw, str):
            continue
        name = raw.strip()
        slug = tag_slug(name)
        if not slug or len(name) > _MAX_NAME or slug in seen:
            continue
        seen.add(slug)
        picked.append((slug, name))
        if len(picked) >= _MAX_TAGS:
            break
    return picked


def copy_activities(session, keyspace: str, dry_run: bool) -> dict[str, int]:  # noqa: ANN001
    """Claim each live activity's tags onto its creator and bind the edges."""
    stats = {"tags_copied": 0, "tags_kept": 0, "edges": 0, "sets": 0}
    now = datetime.now(timezone.utc)
    held: set[tuple[UUID, str]] = set()
    for row in _paged(
        session,
        f"SELECT id, org_id, created_by, tag_names, deleted_at"
        f" FROM {keyspace}.activities",
    ):
        if row.deleted_at is not None or row.created_by is None:
            continue
        pairs = _pairs(list(row.tag_names or []))
        if not pairs:
            continue
        for slug, name in pairs:
            _claim(
                session, keyspace, dry_run, stats, held,
                row.created_by, slug, name, now,
            )
            _edge(
                session, keyspace, dry_run, stats,
                row.created_by, slug, row.id, row.org_id,
            )
        _set(
            session, keyspace, dry_run, stats,
            row.created_by, row.id, row.org_id, [slug for slug, _name in pairs],
        )
    return stats


def _claim(  # noqa: PLR0913
    session, keyspace: str, dry_run: bool, stats: dict[str, int],  # noqa: ANN001
    held: set[tuple[UUID, str]], user_id: UUID, slug: str, name: str,
    now: datetime,
) -> None:
    key = (user_id, slug)
    if key in held:
        return
    held.add(key)
    current = _one(
        session,
        f"SELECT name FROM {keyspace}.tags_by_user"
        " WHERE user_id = %s AND slug = %s",
        [user_id, slug],
    )
    if current is not None:
        stats["tags_kept"] += 1
        return
    stats["tags_copied"] += 1
    if dry_run:
        return
    session.execute(
        f"INSERT INTO {keyspace}.tags_by_user"
        " (user_id, slug, name, created_at, updated_at)"
        " VALUES (%s, %s, %s, %s, %s) IF NOT EXISTS",
        [user_id, slug, name, now, now],
    )


def _edge(  # noqa: PLR0913
    session, keyspace: str, dry_run: bool, stats: dict[str, int],  # noqa: ANN001
    user_id: UUID, slug: str, activity_id: UUID, org_id: UUID,
) -> None:
    current = _one(
        session,
        f"SELECT org_id FROM {keyspace}.activity_tags_by_user"
        " WHERE user_id = %s AND tag_slug = %s AND activity_id = %s",
        [user_id, slug, activity_id],
    )
    if current is not None:
        return
    stats["edges"] += 1
    if dry_run:
        return
    session.execute(
        f"INSERT INTO {keyspace}.activity_tags_by_user"
        " (user_id, tag_slug, activity_id, org_id)"
        " VALUES (%s, %s, %s, %s)",
        [user_id, slug, activity_id, org_id],
    )


def _set(  # noqa: PLR0913
    session, keyspace: str, dry_run: bool, stats: dict[str, int],  # noqa: ANN001
    user_id: UUID, activity_id: UUID, org_id: UUID, slugs: list[str],
) -> None:
    current = _one(
        session,
        f"SELECT slugs FROM {keyspace}.user_activity_tag_sets"
        " WHERE user_id = %s AND activity_id = %s",
        [user_id, activity_id],
    )
    if current is None:
        stats["sets"] += 1
        if not dry_run:
            session.execute(
                f"INSERT INTO {keyspace}.user_activity_tag_sets"
                " (user_id, activity_id, org_id, slugs)"
                " VALUES (%s, %s, %s, %s)",
                [user_id, activity_id, org_id, slugs],
            )
        return
    merged = list(current.slugs or [])
    extra = [slug for slug in slugs if slug not in merged]
    if not extra:
        return
    stats["sets"] += 1
    if dry_run:
        return
    session.execute(
        f"UPDATE {keyspace}.user_activity_tag_sets SET slugs = %s"
        " WHERE user_id = %s AND activity_id = %s",
        [merged + extra, user_id, activity_id],
    )


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = common.parse_args(
        "Create personal activity-tag tables and bind live activities.",
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
    try:
        cluster, session = common.connect(cfg)
    except Exception as exc:
        logger.error("Cannot reach ScyllaDB: %s", exc)
        return 1
    try:
        stats = create_tables(session, cfg, common.cql_file(args))
        ready = all(
            common.table_exists(session, cfg.keyspace, table)
            for table in TABLES
        )
        if cfg.dry_run and not ready:
            copied = {"tags_copied": 0, "tags_kept": 0, "edges": 0, "sets": 0}
            logger.info("Copy skipped; activity tag tables are not created yet.")
        else:
            copied = copy_activities(session, cfg.keyspace, cfg.dry_run)
        logger.info(
            "tables: created=%d skipped=%d; copy: tags=%d kept=%d"
            " edges=%d sets=%d%s.",
            stats["created"], stats["skipped"],
            copied["tags_copied"], copied["tags_kept"],
            copied["edges"], copied["sets"],
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
