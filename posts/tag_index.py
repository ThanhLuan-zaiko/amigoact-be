"""Persistence for post tag edges. No FastAPI and no activity imports."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from core.tags import tag_slug
from posts.model import OrgPost
from posts.tag_model import PostTagsByOrg, TrashedPostTagEdgesByOrg
from posts.tag_rules import MAX_POST_TAGS, dedupe_tag_names


class PostTagIndex(ABC):
    """Post-side mirror of the org tag catalog."""

    @abstractmethod
    def replace(
        self, org_id: UUID, post_id: UUID, names: list[str], now: datetime
    ) -> None:
        """Set tag_names and rewrite this post's edges to match."""

    @abstractmethod
    def forget(self, org_id: UUID, post_id: UUID) -> None:
        """Drop edges and remembered rows for a purged post."""

    @abstractmethod
    def list_ids(self, org_id: UUID, slug: str) -> list[UUID]:
        """Post ids edged to the slug, newest UUIDv7 first."""

    @abstractmethod
    def usage(self, org_id: UUID) -> dict[str, int]:
        """Slug -> published posts that are not in the trash."""

    @abstractmethod
    def trashed_usage(self, org_id: UUID) -> dict[str, int]:
        """Slug -> remembered edges whose post is not trashed."""

    @abstractmethod
    def retag(
        self,
        org_id: UUID,
        slug: str,
        replacement: str | None,
        now: datetime,
    ) -> None:
        """Rewrite tag_names: the matching name becomes replacement."""

    @abstractmethod
    def snapshot_trash(self, org_id: UUID, slug: str) -> None:
        """Copy live edges into the remembered table before a detach."""

    @abstractmethod
    def restore(
        self, org_id: UUID, slug: str, name: str, now: datetime
    ) -> None:
        """Re-attach remembered posts, skipping any already at the cap."""

    @abstractmethod
    def forget_slug(self, org_id: UUID, slug: str) -> None:
        """Drop remembered edges for one slug."""


def _names(row: OrgPost | None) -> list[str]:
    if row is None:
        return []
    return list(getattr(row, "tag_names", None) or [])


def _published(row: OrgPost) -> bool:
    if getattr(row, "deleted_at", None) is not None:
        return False
    return (row.status or "active") != "draft"


class CqlPostTagIndex(PostTagIndex):
    """cqlengine edges plus the denormalized tag_names list."""

    def replace(
        self, org_id: UUID, post_id: UUID, names: list[str], now: datetime
    ) -> None:
        row = OrgPost.objects(post_id=post_id).first()
        if row is None or row.org_id != org_id:
            return
        canonical = dedupe_tag_names(names)[:MAX_POST_TAGS]
        for name in _names(row):
            PostTagsByOrg.objects(
                org_id=org_id, tag_slug=tag_slug(name), post_id=post_id
            ).delete()
        OrgPost.objects(post_id=post_id).update(
            tag_names=canonical, updated_at=now
        )
        for name in canonical:
            PostTagsByOrg.create(
                org_id=org_id, tag_slug=tag_slug(name), post_id=post_id
            )

    def forget(self, org_id: UUID, post_id: UUID) -> None:
        row = OrgPost.objects(post_id=post_id).first()
        for name in _names(row):
            PostTagsByOrg.objects(
                org_id=org_id, tag_slug=tag_slug(name), post_id=post_id
            ).delete()
        for edge in TrashedPostTagEdgesByOrg.objects(org_id=org_id).all():
            if edge.post_id == post_id:
                edge.delete()

    def list_ids(self, org_id: UUID, slug: str) -> list[UUID]:
        ids = [
            edge.post_id
            for edge in PostTagsByOrg.objects(
                org_id=org_id, tag_slug=slug
            ).all()
        ]
        ids.sort(reverse=True)
        return ids

    def usage(self, org_id: UUID) -> dict[str, int]:
        counts: dict[str, int] = {}
        for edge in PostTagsByOrg.objects(org_id=org_id).all():
            row = OrgPost.objects(post_id=edge.post_id).first()
            if row is None or not _published(row):
                continue
            counts[edge.tag_slug] = counts.get(edge.tag_slug, 0) + 1
        return counts

    def trashed_usage(self, org_id: UUID) -> dict[str, int]:
        counts: dict[str, int] = {}
        for edge in TrashedPostTagEdgesByOrg.objects(org_id=org_id).all():
            row = OrgPost.objects(post_id=edge.post_id).first()
            if row is None or getattr(row, "deleted_at", None) is not None:
                continue
            counts[edge.tag_slug] = counts.get(edge.tag_slug, 0) + 1
        return counts

    def retag(
        self,
        org_id: UUID,
        slug: str,
        replacement: str | None,
        now: datetime,
    ) -> None:
        edges = list(
            PostTagsByOrg.objects(org_id=org_id, tag_slug=slug).all()
        )
        for edge in edges:
            row = OrgPost.objects(post_id=edge.post_id).first()
            names = _names(row)
            hit = next(
                (
                    index
                    for index, value in enumerate(names)
                    if tag_slug(value) == slug
                ),
                None,
            )
            if row is None or hit is None:
                edge.delete()
                continue
            if replacement is None:
                names.pop(hit)
            else:
                names[hit] = replacement
            new_names = dedupe_tag_names(names)
            OrgPost.objects(post_id=row.post_id).update(
                tag_names=new_names, updated_at=now
            )
            edge.delete()
            for name in new_names:
                PostTagsByOrg.create(
                    org_id=org_id,
                    tag_slug=tag_slug(name),
                    post_id=row.post_id,
                )

    def snapshot_trash(self, org_id: UUID, slug: str) -> None:
        for edge in PostTagsByOrg.objects(org_id=org_id, tag_slug=slug).all():
            TrashedPostTagEdgesByOrg.create(
                org_id=org_id, tag_slug=slug, post_id=edge.post_id
            )

    def restore(
        self, org_id: UUID, slug: str, name: str, now: datetime
    ) -> None:
        edges = list(
            TrashedPostTagEdgesByOrg.objects(
                org_id=org_id, tag_slug=slug
            ).all()
        )
        for edge in edges:
            row = OrgPost.objects(post_id=edge.post_id).first()
            if row is None:
                continue
            names = _names(row)
            if slug in {tag_slug(value) for value in names}:
                continue
            if len(names) >= MAX_POST_TAGS:
                continue
            names.append(name)
            OrgPost.objects(post_id=row.post_id).update(
                tag_names=names, updated_at=now
            )
            PostTagsByOrg.create(
                org_id=org_id, tag_slug=slug, post_id=row.post_id
            )

    def forget_slug(self, org_id: UUID, slug: str) -> None:
        TrashedPostTagEdgesByOrg.objects(
            org_id=org_id, tag_slug=slug
        ).delete()
