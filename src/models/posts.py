"""Organization feed tables: posts, their tags, pictures, and comments."""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from src.models import (  # noqa: F401  registers the foreign key targets
    activities,
    auth,
    media,
    organizations,
    tags,
)
from src.models.base import Base


class OrgPost(Base):
    __tablename__ = "org_posts"

    post_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    # Allowed values are enforced by CHECK constraints in schema.sql.
    kind: Mapped[str]
    title: Mapped[str | None]
    body: Mapped[str | None]
    status: Mapped[str] = mapped_column(server_default="active")
    visibility: Mapped[str] = mapped_column(server_default="members")
    pinned_at: Mapped[datetime | None]
    edited_at: Mapped[datetime | None]
    published_at: Mapped[datetime | None]
    deleted_at: Mapped[datetime | None]
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    hidden_at: Mapped[datetime | None]
    hidden_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # The activity this post is about, if any. Readers sign up from the post.
    activity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("activities.id", ondelete="SET NULL")
    )


class PostTag(Base):
    __tablename__ = "post_tags"

    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("org_posts.post_id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )


class PostMedia(Base):
    __tablename__ = "org_post_media"

    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("org_posts.post_id", ondelete="CASCADE"), primary_key=True
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("media_assets.asset_id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(server_default="0")


class PostComment(Base):
    __tablename__ = "org_post_comments"

    comment_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("org_posts.post_id", ondelete="CASCADE")
    )
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str]
    edited_at: Mapped[datetime | None]
    deleted_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
