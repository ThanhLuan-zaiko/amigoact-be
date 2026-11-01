"""Declarative base shared by all ORM models."""

import uuid
from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import DateTime, Uuid
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeEngine


class Base(DeclarativeBase):
    """Base class for ORM models.

    The schema is owned by schema.sql. Models only map existing tables, so
    create_all and migrations are never used to create them.
    """

    type_annotation_map: ClassVar[dict[type, TypeEngine[Any]]] = {
        uuid.UUID: Uuid(),
        datetime: DateTime(timezone=True),
    }
