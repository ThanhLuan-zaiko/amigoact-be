"""Which uploaded files are still in use, read from the foreign keys in the database.

The list comes from pg_constraint, not from the ORM models, so a foreign key that the
models do not declare (for example users.avatar_media_id) still counts as a use.
"""

import uuid
from typing import Any

from sqlalchemy import column, func, select, table, text
from sqlalchemy.orm import Session
from sqlalchemy.sql.expression import ColumnClause

# Every single-column foreign key that points at media_assets, as (table, column).
REFERENCING_COLUMNS_SQL = text(
    """
    SELECT rel.relname, att.attname
    FROM pg_constraint con
    JOIN pg_class rel ON rel.oid = con.conrelid
    JOIN pg_attribute att
      ON att.attrelid = con.conrelid AND att.attnum = con.conkey[1]
    WHERE con.contype = 'f'
      AND con.confrelid = 'media_assets'::regclass
      AND array_length(con.conkey, 1) = 1
    """
)


def referencing_columns(db: Session) -> list[tuple[str, str]]:
    return [(row[0], row[1]) for row in db.execute(REFERENCING_COLUMNS_SQL)]


def reference_count(db: Session, asset_id: uuid.UUID) -> int:
    """How many rows, in any table, point at this asset."""
    total = 0
    for table_name, column_name in referencing_columns(db):
        value: ColumnClause[Any] = column(column_name)
        total += (
            db.scalar(
                select(func.count())
                .select_from(table(table_name))
                .where(value == asset_id)
            )
            or 0
        )
    return total


def referenced_asset_ids(db: Session) -> set[uuid.UUID]:
    """Every asset id that some row points at, whatever the table or the action on delete."""
    used: set[uuid.UUID] = set()
    for table_name, column_name in referencing_columns(db):
        value: ColumnClause[Any] = column(column_name)
        query = (
            select(value)
            .select_from(table(table_name))
            .where(value.is_not(None))
            .distinct()
        )
        used.update(db.scalars(query))
    return used
