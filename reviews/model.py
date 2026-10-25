"""cqlengine models for activity reviews and the per-student feed."""

from __future__ import annotations

import core.database  # noqa: F401  (reactor compat shim must run first)
from core.ids import uuid7
from cassandra.cqlengine import columns, models


class ReviewsByActivity(models.Model):
    """Public review feed of one activity, newest first."""

    __table_name__ = "reviews_by_activity"

    activity_id = columns.UUID(primary_key=True)
    created_at = columns.DateTime(
        primary_key=True, clustering_order="DESC"
    )
    review_id = columns.UUID(
        primary_key=True, clustering_order="ASC", default=uuid7
    )
    student_id = columns.UUID()
    rating = columns.Integer()
    comment = columns.Text()


class ReviewsByStudent(models.Model):
    """One student's reviews, doubles as the per-activity dedup index."""

    __table_name__ = "reviews_by_student"

    student_id = columns.UUID(primary_key=True)
    created_at = columns.DateTime(
        primary_key=True, clustering_order="DESC"
    )
    review_id = columns.UUID(
        primary_key=True, clustering_order="ASC", default=uuid7
    )
    activity_id = columns.UUID()
    rating = columns.Integer()
