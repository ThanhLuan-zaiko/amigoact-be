"""Migration: personal tag catalog, then a copy of live org tags.

Creates tags_by_user, post_tags_by_user and user_post_tag_sets.
Then copies each live tags_by_org row onto that org's owner, and
records posts that still carry the name. Org rows are left in place.
A slug the user already has keeps its spelling. Idempotent.

    uv run python -m migrate.user_tags --dry-run
    uv run python -m migrate.user_tags
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from uuid import UUID

from core.tags import tag_slug
from migrate import common
from posts.tag_rules import take_post_tags

logger = logging.getLogger("migrate.user_tags")

TABLES = ("tags_by_user", "post_tags_by_user", "user_post_tag_sets")


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


def _post_pairs(names: list[str] | None) -> list[tuple[str, str]]:
    """(slug, name) from a post, capped at 3, first spelling wins."""
    picked: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in take_post_tags(names):
        name = raw.strip()
        slug = tag_slug(name)
        if not slug or slug in seen:
            continue
        seen.add(slug)
        picked.append((slug, name))
    return picked


def copy_owned(session, keyspace: str, dry_run: bool) -> dict[str, int]:  # noqa: ANN001
    """Copy live org tags onto the owner and bind posts that use them."""
    stats = {"tags_copied": 0, "tags_kept": 0, "edges": 0, "sets": 0}
    owners: dict[UUID, UUID] = {}
    for org in _paged(
        session,
        f"SELECT id, owner_id, deleted_at FROM {keyspace}.organizations",
    ):
        if org.deleted_at is None and org.owner_id is not None:
            owners[org.id] = org.owner_id

    seen: set[tuple[UUID, str]] = set()

    def claim(
        user_id: UUID, slug: str, name: str,
        created_at: datetime, updated_at: datetime,
    ) -> None:
        key = (user_id, slug)
        if key in seen:
            return
        seen.add(key)
        row = _one(
            session,
            f"SELECT name FROM {keyspace}.tags_by_user"
            " WHERE user_id = %s AND slug = %s",
            [user_id, slug],
        )
        if row is not None:
            stats["tags_kept"] += 1
            return
        stats["tags_copied"] += 1
        logger.info(
            "Copy tag '%s' (%s) onto user %s%s.",
            name, slug, user_id, " (dry-run)" if dry_run else "",
        )
        if dry_run:
            return
        session.execute(
            f"INSERT INTO {keyspace}.tags_by_user"
            " (user_id, slug, name, created_at, updated_at)"
            " VALUES (%s, %s, %s, %s, %s) IF NOT EXISTS",
            [user_id, slug, name, created_at, updated_at],
        )

    for tag in _paged(
        session,
        f"SELECT org_id, slug, name, created_at, updated_at, deleted_at"
        f" FROM {keyspace}.tags_by_org",
    ):
        owner = owners.get(tag.org_id)
        if tag.deleted_at is not None or owner is None or not tag.slug:
            continue
        claim(
            owner, tag.slug, tag.name,
            tag.created_at, tag.updated_at or tag.created_at,
        )

    now = datetime.now(timezone.utc)
    for post in _paged(
        session,
        f"SELECT post_id, org_id, author_id, tag_names, deleted_at,"
        f" revision_of FROM {keyspace}.org_posts",
    ):
        if post.deleted_at is not None or post.revision_of is not None:
            continue
        pairs = _post_pairs(list(post.tag_names or []))
        owner = owners.get(post.org_id)
        if not pairs or owner is None:
            continue
        people = [owner]
        if post.author_id is not None and post.author_id not in people:
            people.append(post.author_id)
        slugs = [slug for slug, _name in pairs]
        for user_id in people:
            for slug, name in pairs:
                claim(user_id, slug, name, now, now)
                _bind_edge(
                    session, keyspace, dry_run, stats,
                    user_id, slug, post.post_id, post.org_id,
                )
            _bind_set(
                session, keyspace, dry_run, stats,
                user_id, post.post_id, post.org_id, slugs,
            )
    return stats


def _bind_edge(  # noqa: PLR0913
    session, keyspace: str, dry_run: bool, stats: dict[str, int],  # noqa: ANN001
    user_id: UUID, slug: str, post_id: UUID, org_id: UUID,
) -> None:
    row = _one(
        session,
        f"SELECT org_id FROM {keyspace}.post_tags_by_user"
        " WHERE user_id = %s AND tag_slug = %s AND post_id = %s",
        [user_id, slug, post_id],
    )
    if row is not None:
        return
    stats["edges"] += 1
    if dry_run:
        return
    session.execute(
        f"INSERT INTO {keyspace}.post_tags_by_user"
        " (user_id, tag_slug, post_id, org_id) VALUES (%s, %s, %s, %s)",
        [user_id, slug, post_id, org_id],
    )


def _bind_set(  # noqa: PLR0913
    session, keyspace: str, dry_run: bool, stats: dict[str, int],  # noqa: ANN001
    user_id: UUID, post_id: UUID, org_id: UUID, slugs: list[str],
) -> None:
    row = _one(
        session,
        f"SELECT slugs FROM {keyspace}.user_post_tag_sets"
        " WHERE user_id = %s AND post_id = %s",
        [user_id, post_id],
    )
    if row is None:
        stats["sets"] += 1
        if not dry_run:
            session.execute(
                f"INSERT INTO {keyspace}.user_post_tag_sets"
                " (user_id, post_id, org_id, slugs)"
                " VALUES (%s, %s, %s, %s)",
                [user_id, post_id, org_id, slugs],
            )
        return
    current = list(row.slugs or [])
    merged = current + [slug for slug in slugs if slug not in current]
    if merged == current:
        return
    stats["sets"] += 1
    if dry_run:
        return
    session.execute(
        f"UPDATE {keyspace}.user_post_tag_sets SET slugs = %s"
        " WHERE user_id = %s AND post_id = %s",
        [merged, user_id, post_id],
    )


def _tables_ready(session, keyspace: str) -> bool:  # noqa: ANN001
    return all(
        common.table_exists(session, keyspace, table) for table in TABLES
    )


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = common.parse_args(
        "Create personal tag tables and copy live org tags onto owners.",
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
        stats = create_tables(session, cfg, common.cql_file(args))
        if cfg.dry_run and not _tables_ready(session, cfg.keyspace):
            copied = {"tags_copied": 0, "tags_kept": 0, "edges": 0, "sets": 0}
            logger.info("Copy skipped; personal tables are not created yet.")
        else:
            copied = copy_owned(session, cfg.keyspace, cfg.dry_run)
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
