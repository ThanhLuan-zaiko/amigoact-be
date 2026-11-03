"""Shared helper for paged lists."""

from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session


def count_rows(db: Session, query: Any) -> int:
    """Count what a list query matches. Pass it before limit and offset are applied."""
    total = db.scalar(
        query.order_by(None).with_only_columns(func.count(), maintain_column_froms=True)
    )
    return total or 0
