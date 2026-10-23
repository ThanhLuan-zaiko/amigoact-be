"""Personal tags are a name first and a post attachment second."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

from activities.user_tag_service import UserTagService

NOW = datetime(2026, 10, 23, 12, 0, 0)


class Store:
    def __init__(self) -> None:
        self.tags: dict[tuple[UUID, str], SimpleNamespace] = {}
        self.edges: list[SimpleNamespace] = []
        self.sets: dict[tuple[UUID, UUID], SimpleNamespace] = {}
        self.activity_edges: list[SimpleNamespace] = []
        self.activity_sets: dict[tuple[UUID, UUID], SimpleNamespace] = {}

    def list_tags(self, user_id: UUID) -> list[SimpleNamespace]:
        return [row for (owner, _slug), row in self.tags.items() if owner == user_id]

    def get(self, user_id: UUID, slug: str) -> SimpleNamespace | None:
        return self.tags.get((user_id, slug))

    def insert(self, user_id: UUID, slug: str, name: str, now: datetime) -> bool:
        if (user_id, slug) in self.tags:
            return False
        self.tags[(user_id, slug)] = SimpleNamespace(
            name=name, slug=slug, created_at=now, updated_at=now
        )
        return True

    def update_name(self, user_id: UUID, slug: str, name: str, now: datetime) -> None:
        self.tags[(user_id, slug)].name = name
        self.tags[(user_id, slug)].updated_at = now

    def delete_tag(self, user_id: UUID, slug: str) -> None:
        self.tags.pop((user_id, slug), None)

    def posts_for(self, user_id: UUID, slug: str) -> list[SimpleNamespace]:
        return [
            edge for edge in self.edges
            if edge.user_id == user_id and edge.tag_slug == slug
        ]

    def orgs_for(self, user_id: UUID, slug: str) -> set[UUID]:
        return {edge.org_id for edge in self.posts_for(user_id, slug)}

    def slugs_of(self, user_id: UUID, post_id: UUID) -> list[str]:
        row = self.sets.get((user_id, post_id))
        return list(row.slugs) if row is not None else []

    def add_edge(self, user_id: UUID, slug: str, post_id: UUID, org_id: UUID) -> None:
        self.edges.append(SimpleNamespace(
            user_id=user_id, tag_slug=slug, post_id=post_id, org_id=org_id
        ))

    def remove_edge(self, user_id: UUID, slug: str, post_id: UUID) -> None:
        self.edges = [
            edge for edge in self.edges
            if not (
                edge.user_id == user_id
                and edge.tag_slug == slug
                and edge.post_id == post_id
            )
        ]

    def write_set(self, user_id, post_id, org_id, slugs) -> None:  # noqa: ANN001
        if not slugs:
            self.sets.pop((user_id, post_id), None)
            return
        self.sets[(user_id, post_id)] = SimpleNamespace(
            post_id=post_id, org_id=org_id, slugs=list(slugs)
        )

    def sets_for(self, user_id: UUID) -> list[SimpleNamespace]:
        return [row for (owner, _post), row in self.sets.items() if owner == user_id]

    def activities_for(self, user_id: UUID, slug: str) -> list[SimpleNamespace]:
        return [
            edge for edge in getattr(self, "activity_edges", [])
            if edge.user_id == user_id and edge.tag_slug == slug
        ]

    def activity_slugs_of(self, user_id: UUID, activity_id: UUID) -> list[str]:
        row = getattr(self, "activity_sets", {}).get((user_id, activity_id))
        return list(row.slugs) if row is not None else []

    def add_activity_edge(
        self, user_id: UUID, slug: str, activity_id: UUID, org_id: UUID
    ) -> None:
        self.activity_edges.append(SimpleNamespace(
            user_id=user_id, tag_slug=slug, activity_id=activity_id, org_id=org_id
        ))

    def remove_activity_edge(
        self, user_id: UUID, slug: str, activity_id: UUID
    ) -> None:
        self.activity_edges = [
            edge for edge in self.activity_edges
            if not (
                edge.user_id == user_id
                and edge.tag_slug == slug
                and edge.activity_id == activity_id
            )
        ]

    def write_activity_set(
        self, user_id, activity_id, org_id, slugs
    ) -> None:  # noqa: ANN001
        if not hasattr(self, "activity_sets"):
            self.activity_sets = {}
        if not slugs:
            self.activity_sets.pop((user_id, activity_id), None)
            return
        self.activity_sets[(user_id, activity_id)] = SimpleNamespace(
            activity_id=activity_id, org_id=org_id, slugs=list(slugs)
        )

    def activity_sets_for(self, user_id: UUID) -> list[SimpleNamespace]:
        return [
            row for (owner, _activity), row
            in getattr(self, "activity_sets", {}).items()
            if owner == user_id
        ]


class Posts:
    def __init__(self) -> None:
        self.rows: dict[UUID, SimpleNamespace] = {}

    def get(self, post_id: UUID) -> SimpleNamespace | None:
        return self.rows.get(post_id)


def test_create_does_not_attach_a_post() -> None:
    user = uuid4()
    service = UserTagService(Store(), Posts())  # type: ignore[arg-type]
    created = service.create(user, "Mua he")
    assert created.slug == "mua-he"
    assert created.post_count == 0
    assert service.list_posts(user, "mua-he") == []


def test_binding_a_post_shows_it_on_the_tag() -> None:
    user = uuid4()
    org = uuid4()
    post_id = uuid4()
    posts = Posts()
    posts.rows[post_id] = SimpleNamespace(
        title="Chao he", tag_names=["Mua he"], status="active", deleted_at=None
    )
    service = UserTagService(Store(), posts)  # type: ignore[arg-type]
    service.create(user, "Mua he")
    service.bind(user, org, post_id, ["Mua he"])
    listed = service.list_posts(user, "mua-he")
    assert [(row.post_id, row.org_id, row.draft, row.cover_url) for row in listed] == [
        (post_id, org, False, None)
    ]
    catalog = service.list_tags(user)
    assert catalog[0].post_count == 1
    assert catalog[0].posts[0].post_id == post_id


def test_listed_post_carries_its_cover() -> None:
    user = uuid4()
    org = uuid4()
    post_id = uuid4()
    posts = Posts()
    posts.rows[post_id] = SimpleNamespace(
        title="Chao he", tag_names=["Mua he"], status="active", deleted_at=None
    )

    class Covers:
        def cover_of(self, row: object) -> str:
            return "/media/orgs/cover.jpg"

    service = UserTagService(Store(), posts, covers=Covers())  # type: ignore[arg-type]
    service.create(user, "Mua he")
    service.bind(user, org, post_id, ["Mua he"])
    assert service.list_posts(user, "mua-he")[0].cover_url == "/media/orgs/cover.jpg"


def test_delete_detaches_the_post() -> None:
    user = uuid4()
    org = uuid4()
    post_id = uuid4()
    posts = Posts()
    posts.rows[post_id] = SimpleNamespace(
        title="Chao he", tag_names=["Mua he"], status="active", deleted_at=None
    )
    service = UserTagService(Store(), posts)  # type: ignore[arg-type]
    service.create(user, "Mua he")
    service.bind(user, org, post_id, ["Mua he"])
    service.delete(user, "mua-he")
    assert service.list_tags(user) == []
    assert service._store.posts_for(user, "mua-he") == []  # noqa: SLF001
