"""Non-destructive keyspace migrations, one module per change.

Each `<topic>.py` module is one migration runnable from the repo
root: `uv run python -m migrate.announcements_feed --dry-run`.
Shared plumbing (flags, config, driver session, DDL extraction) lives
in `migrate/common.py`; a migration file keeps only its own logic.
"""
