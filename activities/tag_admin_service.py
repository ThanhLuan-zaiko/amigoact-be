"""Org tag curation: list/create/rename/merge/delete behind tag:manage."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from activities.interfaces import ActivityEvents, OrgTagStore
from activities.model import tag_fold, tag_slug
from activities.tag_model import TagByOrg
from core.exceptions import (
    ForbiddenError,
    InvalidOrgStateError,
    InvalidTagMergeError,
    NotFoundError,
    TagDeletedError,
    TagExistsError,
    TagNotFoundError,
)
from core.security import utcnow
from orgs.interfaces import OrgRepository
from rbac.interfaces import AccessControl

_PERMISSION = "tag:manage"


@dataclass(frozen=True)
class OrgTagSnapshot:
    """One catalog row as the manage screen renders it."""

    id: UUID
    name: str
    slug: str
    activity_count: int
    created_at: datetime
    deleted_at: datetime | None = None


@dataclass(frozen=True)
class OrgTagListing:
    """Tag page plus capability flag and trash badge for managers."""

    items: list[OrgTagSnapshot]
    can_manage: bool
    trash_count: int = 0


class TagAdminService:
    """Catalog mutations; members read, tag:manage holders curate."""

    def __init__(
        self,
        tags: OrgTagStore,
        orgs: OrgRepository,
        access: AccessControl,
        events: ActivityEvents | None = None,
    ) -> None:
        self._tags = tags
        self._orgs = orgs
        self._access = access
        self._events = events

    def _org(self, org_id: UUID) -> object:
        org = self._orgs.get_by_id(org_id)
        if org is None or getattr(org, "deleted_at", None) is not None:
            raise NotFoundError("Organization not found.")
        return org

    def _can_manage(self, org: object, org_id: UUID, user_id: UUID) -> bool:
        return getattr(org, "owner_id", None) == user_id or (
            self._access.has_permission(org_id, user_id, _PERMISSION)
        )

    def _require_manager(self, org_id: UUID, actor_id: UUID) -> object:
        """Owner bypass plus the tag:manage permission for others."""
        org = self._org(org_id)
        if not self._can_manage(org, org_id, actor_id):
            self._access.record(
                org_id, actor_id, _PERMISSION, "tag", None, "denied"
            )
            raise ForbiddenError("Only tag managers can do this.")
        return org

    def _snapshot(
        self, row: TagByOrg, counts: dict[str, int]
    ) -> OrgTagSnapshot:
        return OrgTagSnapshot(
            id=row.tag_id,
            name=row.name,
            slug=row.slug,
            activity_count=counts.get(row.slug, 0),
            created_at=row.created_at,
            deleted_at=row.deleted_at,
        )

    def _audit(
        self,
        org_id: UUID,
        actor_id: UUID,
        action: str,
        tag_id: UUID,
        old: str | None,
        new: str | None,
    ) -> None:
        self._access.record(
            org_id,
            actor_id,
            action,
            "tag",
            tag_id,
            "allowed",
            json.dumps({"tag": {"old": old, "new": new}}, default=str),
        )

    def _emit(
        self, org_id: UUID, action: str, slug: str, actor_id: UUID
    ) -> None:
        """Best-effort fan-out; a dead bus never blocks a mutation."""
        if self._events is None:
            return
        try:
            self._events.tags_changed(org_id, action, slug, actor_id)
        except Exception:  # noqa: BLE001 - live fan-out is advisory
            pass

    def list_tags(
        self,
        org_id: UUID,
        viewer_id: UUID,
        query: str = "",
        limit: int = 500,
        trash: bool = False,
    ) -> OrgTagListing:
        """Member-readable catalog page; the trash view is manager-only
        and counts remembered edges, not live tag_names."""
        org = self._org(org_id)
        if (
            getattr(org, "owner_id", None) != viewer_id
            and not self._orgs.is_member(org_id, viewer_id)
        ):
            raise ForbiddenError("Only org members can list tags.")
        can_manage = self._can_manage(org, org_id, viewer_id)
        if trash and not can_manage:
            self._access.record(
                org_id, viewer_id, _PERMISSION, "tag", None, "denied"
            )
            raise ForbiddenError("Only tag managers can do this.")
        all_rows = self._tags.list(org_id)
        trashed = [r for r in all_rows if r.deleted_at is not None]
        needle = tag_fold(query.strip())
        if trash:
            counts = self._tags.trashed_usage(org_id)
            rows = sorted(
                trashed, key=lambda row: row.deleted_at, reverse=True
            )
        else:
            counts = self._tags.usage(org_id)
            rows = sorted(
                (r for r in all_rows if r.deleted_at is None),
                key=lambda row: row.name.casefold(),
            )
        rows = [
            row
            for row in rows
            if not needle
            or needle in row.slug
            or needle in tag_fold(row.name)
        ]
        return OrgTagListing(
            items=[
                self._snapshot(row, counts) for row in rows[:limit]
            ],
            can_manage=can_manage,
            trash_count=len(trashed) if can_manage else 0,
        )

    def create_tag(
        self, org_id: UUID, actor_id: UUID, name: str
    ) -> OrgTagSnapshot:
        """Manager-curated catalog entry; duplicates conflict by slug."""
        self._require_manager(org_id, actor_id)
        from core.ids import uuid7

        now = utcnow()
        row, created = self._tags.claim(
            org_id, uuid7(), tag_slug(name.strip()), name.strip(), now
        )
        if not created:
            if row.deleted_at is not None:
                raise TagDeletedError(
                    "Tag is in the trash; restore it first."
                )
            raise TagExistsError("Tag already exists.")
        self._audit(org_id, actor_id, "tag.create", row.tag_id, None, row.name)
        self._emit(org_id, "created", row.slug, actor_id)
        return self._snapshot(row, {})

    def rename_tag(
        self, org_id: UUID, actor_id: UUID, slug: str, name: str
    ) -> OrgTagSnapshot:
        """Rename in place; a new slug re-claims and retags activities."""
        self._require_manager(org_id, actor_id)
        row = self._tags.get(org_id, slug)
        if row is None:
            raise TagNotFoundError("Tag not found.")
        if row.deleted_at is not None:
            raise TagDeletedError(
                "Tag is in the trash; restore it first."
            )
        new_name = name.strip()
        if new_name == row.name:
            return self._snapshot(row, self._tags.usage(org_id))
        new_slug = tag_slug(new_name)
        if new_slug != slug:
            target = self._tags.get(org_id, new_slug)
            if target is not None:
                if target.deleted_at is not None:
                    raise TagDeletedError(
                        "Target tag is in the trash; restore it first."
                    )
                raise TagExistsError("Tag already exists.")
        now = utcnow()
        updated = self._tags.rename(org_id, row, new_slug, new_name, now)
        if updated is None:
            raise TagExistsError("Tag already exists.")
        self._tags.retag(org_id, slug, new_name, now)
        if new_slug != slug:
            # Old row outlives retag: a failed sweep leaves the catalog
            # pointing at the tag some activities still carry.
            self._tags.remove(org_id, slug)
        self._audit(
            org_id, actor_id, "tag.rename", row.tag_id, row.name, new_name
        )
        self._emit(org_id, "renamed", updated.slug, actor_id)
        return self._snapshot(updated, self._tags.usage(org_id))

    def merge_tags(
        self, org_id: UUID, actor_id: UUID, slug: str, into: str
    ) -> OrgTagSnapshot:
        """Fold one tag into another; activities keep the target name."""
        self._require_manager(org_id, actor_id)
        if slug == into:
            raise InvalidTagMergeError("Cannot merge a tag into itself.")
        source = self._tags.get(org_id, slug)
        target = self._tags.get(org_id, into)
        if source is None or target is None:
            raise TagNotFoundError("Tag not found.")
        if (
            source.deleted_at is not None
            or target.deleted_at is not None
        ):
            raise TagDeletedError(
                "Tag is in the trash; restore it first."
            )
        self._tags.retag(org_id, slug, target.name, utcnow())
        self._tags.remove(org_id, slug)
        self._audit(
            org_id, actor_id, "tag.merge", source.tag_id,
            source.name, target.name,
        )
        self._emit(org_id, "merged", slug, actor_id)
        return self._snapshot(target, self._tags.usage(org_id))

    def trash_tag(
        self, org_id: UUID, actor_id: UUID, slug: str
    ) -> OrgTagSnapshot:
        """Soft delete: remember the edges, detach everywhere, then
        mark the row so the slug stays reserved in the org trash."""
        self._require_manager(org_id, actor_id)
        row = self._tags.get(org_id, slug)
        if row is None:
            raise TagNotFoundError("Tag not found.")
        if row.deleted_at is not None:
            raise TagDeletedError("Tag is already in the trash.")
        now = utcnow()
        self._tags.snapshot_trash_edges(org_id, slug)
        self._tags.retag(org_id, slug, None, now)
        self._tags.mark_trashed(org_id, slug, now)
        self._audit(
            org_id, actor_id, "tag.trash", row.tag_id, row.name, None
        )
        self._emit(org_id, "trashed", slug, actor_id)
        trashed = self._tags.get(org_id, slug) or row
        return self._snapshot(trashed, self._tags.trashed_usage(org_id))

    def restore_tag(
        self, org_id: UUID, actor_id: UUID, slug: str
    ) -> OrgTagSnapshot:
        """Re-attach the remembered activities and relist the slug."""
        self._require_manager(org_id, actor_id)
        row = self._tags.get(org_id, slug)
        if row is None:
            raise TagNotFoundError("Tag not found.")
        if row.deleted_at is None:
            raise InvalidOrgStateError("Tag is not in the trash.")
        now = utcnow()
        self._tags.restore_edges(org_id, slug, row.name, now)
        self._tags.mark_restored(org_id, slug, row.name, now)
        self._audit(
            org_id, actor_id, "tag.restore", row.tag_id, None, row.name
        )
        self._emit(org_id, "restored", slug, actor_id)
        restored = self._tags.get(org_id, slug) or row
        return self._snapshot(restored, self._tags.usage(org_id))

    def erase_tag(self, org_id: UUID, actor_id: UUID, slug: str) -> None:
        """Hard delete: live rows are stripped off activities first;
        trashed rows are already detached, only catalog and remembered
        rows are purged."""
        self._require_manager(org_id, actor_id)
        row = self._tags.get(org_id, slug)
        if row is None:
            raise TagNotFoundError("Tag not found.")
        if row.deleted_at is None:
            self._tags.retag(org_id, slug, None, utcnow())
        self._tags.remove(org_id, slug)
        self._audit(
            org_id, actor_id, "tag.erase", row.tag_id, row.name, None
        )
        self._emit(org_id, "erased", slug, actor_id)
