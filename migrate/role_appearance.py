"""Migration: role colour/position and per-org member default permissions.

Adds roles.color and roles.position, and creates org_member_defaults
straight from schemas.cql. Additive and idempotent, safe to re-run.

    uv run python -m migrate.role_appearance --dry-run
    uv run python -m migrate.role_appearance
"""

from __future__ import annotations

import logging
import sys

from migrate import common
from migrate.activity_tags import _column_exists

logger = logging.getLogger("migrate.role_appearance")

DEFAULTS_TABLE = "org_member_defaults"
NEW_COLUMNS = (("color", "text"), ("position", "int"))


def create_defaults_table(session, cfg: common.Config, cql_path) -> bool:  # noqa: ANN001
    if common.table_exists(session, cfg.keyspace, DEFAULTS_TABLE):
        return False
    stmts = common.schema_statements(cql_path, cfg.keyspace, DEFAULTS_TABLE)
    logger.info(
        "%s: creating table%s.",
        DEFAULTS_TABLE, " (dry-run)" if cfg.dry_run else "",
    )
    for stmt in stmts:
        if stmt.upper().startswith(("CREATE KEYSPACE", "USE")):
            continue
        if not cfg.dry_run:
            session.execute(stmt)
    return True


def add_role_columns(session, cfg: common.Config) -> list[str]:  # noqa: ANN001
    added: list[str] = []
    for name, cql_type in NEW_COLUMNS:
        if _column_exists(session, cfg.keyspace, "roles", name):
            continue
        logger.info(
            "roles.%s: adding column%s.",
            name, " (dry-run)" if cfg.dry_run else "",
        )
        if not cfg.dry_run:
            session.execute(
                f"ALTER TABLE {cfg.keyspace}.roles ADD {name} {cql_type}"
            )
        added.append(name)
    return added


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = common.parse_args(
        "Add roles.color/position and create org_member_defaults.", argv
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
        created = create_defaults_table(session, cfg, common.cql_file(args))
        added = add_role_columns(session, cfg)
        logger.info(
            "%s: %s; new role columns: %s%s.",
            DEFAULTS_TABLE,
            "created" if created else "already present",
            ", ".join(added) or "none",
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
