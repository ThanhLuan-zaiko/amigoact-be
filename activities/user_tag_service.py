"""Personal tags: create a name, attach it from the board or an activity."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from activities.interfaces import ActivityEvents
from activities.user_tag_activities import (
    ActivityHeads,
    ActivityRetag,
    UserTagActivity,
    bind as bind_activity_edges,
    collect as collect_activities,
    drop as drop_activity_edges,
    move as move_activity_edges,
    rewrite_owned,
)
from activities.user_tag_store import CqlUserTagStore
from core.exceptions import TagExistsError, TagNotFoundError
from core.security import utcnow
from core.tags import tag_slug

_MAX_NAME = 40
_POST_LIMIT = 20


class PostHeads(Protocol):
    """The bit of the post store this catalog needs."""

    def get(self, post_id: UUID) -> object | None:
        """Canonical post, or None."""


class PostRetag(Protocol):
    """Rewrite tag_names on every post edged to a slug inside one org."""

    def retag(
        self,
        org_id: UUID,
        slug: str,
        replacement: str | None,
        now: datetime,
    ) -> None:
        """Replace or drop the slug on that org's posts."""


class PostCovers(Protocol):
    """Public image path for a post the rail can show."""

    def cover_of(self, row: object) -> str | None:
        """A /media image path, or None when the post has no image."""


@dataclass(frozen=True)
class UserTagView:
    """One personal tag plus how many visible posts carry it."""

    name: str
    slug: str
    post_count: int
    created_at: datetime
    posts: tuple[UserTagPost, ...] = ()
    activity_count: int = 0
    activities: tuple[UserTagActivity, ...] = ()


@dataclass(frozen=True)
class UserTagPost:
    """A post the rail can open."""

    post_id: UUID
    org_id: UUID
    title: str
    draft: bool
    cover_url: str | None = None


def _usable(names: list[str] | None) -> list[tuple[str, str]]:
    """(slug, stripped name) in order, skipping blanks and duplicates."""
    picked: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in names or []:
        name = raw.strip()
        slug = tag_slug(name)
        if not slug or len(name) > _MAX_NAME or slug in seen:
            continue
        seen.add(slug)
        picked.append((slug, name))
    return picked


def _visible(row: object | None, slug: str) -> bool:
    if row is None or getattr(row, "deleted_at", None) is not None:
        return False
    names = getattr(row, "tag_names", None) or []
    return slug in {tag_slug(name) for name in names}


class UserTagService:
    """The signed-in user's tag list and the posts and activities on it."""

    def __init__(
        self,
        store: CqlUserTagStore,
        posts: PostHeads,
        post_tags: PostRetag | None = None,
        covers: PostCovers | None = None,
        activity_heads: ActivityHeads | None = None,
        activity_tags: ActivityRetag | None = None,
        events: ActivityEvents | None = None,
    ) -> None:
        self._store = store
        self._posts = posts
        self._post_tags = post_tags
        self._covers = covers
        self._activity_heads = activity_heads
        self._activity_tags = activity_tags
        self._events = events

    def list_tags(self, user_id: UUID) -> list[UserTagView]:
        rows = self._store.list_tags(user_id)
        rows.sort(key=lambda row: row.name.casefold())
        views: list[UserTagView] = []
        for row in rows:
            total, posts = self._collect(user_id, row.slug)
            views.append(
                self._view(
                    user_id, row.name, row.slug, total, row.created_at, posts
                )
            )
        return views

    def create(self, user_id: UUID, name: str) -> UserTagView:
        picked = _usable([name])
        if not picked:
            raise TagNotFoundError("Tag name is empty.")
        slug, clean = picked[0]
        now = utcnow()
        if not self._store.insert(user_id, slug, clean, now):
            raise TagExistsError("You already have this tag.")
        row = self._store.get(user_id, slug)
        created = row.created_at if row is not None else now
        return UserTagView(clean, slug, 0, created)

    def rename(self, user_id: UUID, slug: str, name: str) -> UserTagView:
        current = self._store.get(user_id, slug)
        if current is None:
            raise TagNotFoundError("Tag not found.")
        picked = _usable([name])
        if not picked:
            raise TagNotFoundError("Tag name is empty.")
        new_slug, clean = picked[0]
        now = utcnow()
        if new_slug != slug:
            if self._store.get(user_id, new_slug) is not None:
                raise TagExistsError("You already have this tag.")
            self._retag(user_id, slug, clean, now)
            self._move_edges(user_id, slug, new_slug)
            if not self._store.insert(user_id, new_slug, clean, now):
                self._store.update_name(user_id, new_slug, clean, now)
            self._store.delete_tag(user_id, slug)
            slug = new_slug
        else:
            self._store.update_name(user_id, slug, clean, now)
            self._retag(user_id, slug, clean, now)
        total, posts = self._collect(user_id, slug)
        return self._view(
            user_id, clean, slug, total, current.created_at, posts
        )

    def delete(self, user_id: UUID, slug: str) -> None:
        if self._store.get(user_id, slug) is None:
            raise TagNotFoundError("Tag not found.")
        self._retag(user_id, slug, None, utcnow())
        for edge in self._store.posts_for(user_id, slug):
            self._store.remove_edge(user_id, slug, edge.post_id)
        for bundle in self._store.sets_for(user_id):
            if slug not in (bundle.slugs or []):
                continue
            self._store.write_set(
                user_id,
                bundle.post_id,
                bundle.org_id,
                [item for item in bundle.slugs if item != slug],
            )
        drop_activity_edges(self._store, user_id, slug)
        self._store.delete_tag(user_id, slug)

    def list_posts(self, user_id: UUID, slug: str) -> list[UserTagPost]:
        if self._store.get(user_id, slug) is None:
            raise TagNotFoundError("Tag not found.")
        _total, posts = self._collect(user_id, slug)
        return posts

    def ensure(self, user_id: UUID, names: list[str] | None) -> list[str]:
        """Claim missing names and return this user's spelling."""
        canonical: list[str] = []
        now = utcnow()
        for slug, name in _usable(names):
            row = self._store.get(user_id, slug)
            if row is None:
                self._store.insert(user_id, slug, name, now)
                row = self._store.get(user_id, slug)
            canonical.append(row.name if row is not None else name)
        return canonical

    def bind(
        self,
        user_id: UUID,
        org_id: UUID,
        post_id: UUID,
        names: list[str] | None,
    ) -> None:
        """Point this post at the slugs it carries now."""
        wanted = [slug for slug, _name in _usable(names)]
        previous = set(self._store.slugs_of(user_id, post_id))
        current = set(wanted)
        for slug in previous - current:
            self._store.remove_edge(user_id, slug, post_id)
        for slug in current - previous:
            self._store.add_edge(user_id, slug, post_id, org_id)
        self._store.write_set(user_id, post_id, org_id, wanted)

    def bind_activity(
        self,
        user_id: UUID,
        org_id: UUID,
        activity_id: UUID,
        names: list[str] | None,
    ) -> None:
        """Point this activity at the slugs it carries now."""
        bind_activity_edges(self._store, user_id, org_id, activity_id, names)

    def _view(
        self,
        user_id: UUID,
        name: str,
        slug: str,
        post_count: int,
        created_at: datetime,
        posts: list[UserTagPost],
    ) -> UserTagView:
        activity_count, activities = self._activity_slice(user_id, slug)
        return UserTagView(
            name,
            slug,
            post_count,
            created_at,
            tuple(posts),
            activity_count,
            tuple(activities),
        )

    def _activity_slice(
        self, user_id: UUID, slug: str
    ) -> tuple[int, list[UserTagActivity]]:
        if self._activity_heads is None:
            return 0, []
        return collect_activities(
            self._store, self._activity_heads, user_id, slug
        )

    def _collect(
        self, user_id: UUID, slug: str
    ) -> tuple[int, list[UserTagPost]]:
        """Visible posts for one tag. The list stops at the rail cap."""
        total = 0
        found: list[UserTagPost] = []
        for edge in self._store.posts_for(user_id, slug):
            row = self._posts.get(edge.post_id)
            if not _visible(row, slug):
                continue
            total += 1
            if len(found) >= _POST_LIMIT:
                continue
            status = getattr(row, "status", "active") or "active"
            title = (getattr(row, "title", "") or "").strip()
            cover = (
                self._covers.cover_of(row) if self._covers is not None else None
            )
            found.append(
                UserTagPost(
                    post_id=edge.post_id,
                    org_id=edge.org_id,
                    title=title,
                    draft=status == "draft",
                    cover_url=cover,
                )
            )
        return total, found

    def _retag(
        self, user_id: UUID, slug: str, replacement: str | None, now: datetime
    ) -> None:
        if self._post_tags is not None:
            for org_id in self._store.orgs_for(user_id, slug):
                self._post_tags.retag(org_id, slug, replacement, now)
        rewrite_owned(
            self._store,
            self._activity_tags,
            self._events,
            user_id,
            slug,
            replacement,
            now,
        )

    def _move_edges(self, user_id: UUID, old: str, new: str) -> None:
        for edge in list(self._store.posts_for(user_id, old)):
            self._store.remove_edge(user_id, old, edge.post_id)
            self._store.add_edge(user_id, new, edge.post_id, edge.org_id)
        for bundle in self._store.sets_for(user_id):
            if old not in (bundle.slugs or []):
                continue
            self._store.write_set(
                user_id,
                bundle.post_id,
                bundle.org_id,
                [new if item == old else item for item in bundle.slugs],
            )
        move_activity_edges(self._store, user_id, old, new)
