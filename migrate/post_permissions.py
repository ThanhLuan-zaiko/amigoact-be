"""Migration: keep existing orgs' members writing posts after the RBAC split.

Writing, publishing and commenting used to need only membership. They now
need post:create, post:publish and comment:create, so every existing org
gets those codes in its member baseline and its members keep working.
New orgs start without them. Additive and idempotent, safe to re-run.

    uv run python -m migrate.post_permissions --dry-run
    uv run python -m migrate.post_permissions
"""

from __future__ import annotations

import logging
import sys

from migrate import common

logger = logging.getLogger("migrate.post_permissions")

DEFAULTS_TABLE = "org_member_defaults"
LEGACY_CODES = ("post:create", "post:publish", "comment:create")


def grant_legacy_baseline(session, cfg: common.Config) -> int:  # noqa: ANN001
    """Insert the legacy codes into every org's baseline; returns org count."""
    org_ids = [
        row.id
        for row in session.execute(f"SELECT id FROM {cfg.keyspace}.organizations")
    ]
    insert = session.prepare(
        f"INSERT INTO {cfg.keyspace}.{DEFAULTS_TABLE} "
        "(org_id, permission_code) VALUES (?, ?)"
    )
    for org_id in org_ids:
        for code in LEGACY_CODES:
            if not cfg.dry_run:
                session.execute(insert, (org_id, code))
    return len(org_ids)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = common.parse_args(
        "Add post:create/post:publish/comment:create to every org baseline.",
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
        if not common.table_exists(session, cfg.keyspace, DEFAULTS_TABLE):
            logger.error(
                "%s is missing; run migrate.role_appearance first.",
                DEFAULTS_TABLE,
            )
            return 1
        count = grant_legacy_baseline(session, cfg)
        logger.info(
            "Baseline %s granted to %d org(s)%s.",
            ", ".join(LEGACY_CODES), count,
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
