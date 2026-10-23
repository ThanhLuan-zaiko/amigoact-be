"""Activity saves claim the author's personal tag book, then bind the row."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
import uuid_utils

from activities.service import ActivityService
from activities.tag_service import TagService
from activities.user_tag_service import UserTagService
from tests.unit.activity_fakes import (
    FakeAccess,
    FakeActivities,
    FakeCategories,
    FakeOrgs,
    _fields,
    _org_with_owner,
)
from tests.unit.tag_fakes import FakeOrgTags
from tests.unit.test_user_tags import Posts, Store


class Book:
    def __init__(self) -> None:
        self.ensured: list[list[str]] = []
        self.bound: list[tuple[object, list[str]]] = []
        self.claimed_by: list[object] = []
        self.bound_by: list[object] = []

    def ensure(self, user_id: object, names: list[str] | None) -> list[str]:
        self.claimed_by.append(user_id)
        self.ensured.append(list(names or []))
        return ["Mua he"]

    def bind_activity(
        self,
        user_id: object,
        org_id: object,
        activity_id: object,
        names: list[str] | None,
    ) -> None:
        self.bound_by.append(user_id)
        self.bound.append((activity_id, list(names or [])))


def test_create_claims_the_personal_book_then_binds() -> None:
    activities = FakeActivities()
    orgs = FakeOrgs()
    owner = uuid_utils.uuid7()
    org = _org_with_owner(orgs, owner, "book-org")
    book = Book()
    service = ActivityService(
        activities=activities,
        categories=FakeCategories(),
        orgs=orgs,
        access=FakeAccess(),
        tags=TagService(FakeOrgTags(activities)),
        user_tags=book,
    )
    row = service.create_activity(
        org.id, owner, _fields(service, tag_names=["  Mua he  ", "mua he"])
    )
    assert book.ensured == [["  Mua he  ", "mua he"]]
    assert row.tag_names == ["Mua he"]
    assert book.bound == [(row.id, ["Mua he"])]


def test_update_reclaims_the_book_and_rebinds() -> None:
    activities = FakeActivities()
    orgs = FakeOrgs()
    owner = uuid_utils.uuid7()
    org = _org_with_owner(orgs, owner, "book-org-update")
    book = Book()
    service = ActivityService(
        activities=activities,
        categories=FakeCategories(),
        orgs=orgs,
        access=FakeAccess(),
        tags=TagService(FakeOrgTags(activities)),
        user_tags=book,
    )
    row = service.create_activity(
        org.id, owner, _fields(service, tag_names=["Mua he"])
    )
    book.ensured.clear()
    book.bound.clear()
    updated = service.update_activity(
        org.id,
        row.id,
        owner,
        _fields(service, tag_names=["Mua he", "Sach"]),
    )
    assert book.ensured == [["Mua he", "Sach"]]
    assert updated.tag_names == ["Mua he"]
    assert book.bound == [(row.id, ["Mua he"])]


def test_bound_activity_shows_on_the_personal_tag() -> None:
    user = uuid4()
    org = uuid4()
    activity_id = uuid4()
    heads = SimpleNamespace(
        rows={
            activity_id: SimpleNamespace(
                title="Don dep",
                tag_names=["Mua he"],
                status="draft",
                deleted_at=None,
            )
        }
    )

    class Heads:
        def get(self, activity_id: object) -> object | None:
            return heads.rows.get(activity_id)

    service = UserTagService(Store(), Posts(), activity_heads=Heads())  # type: ignore[arg-type]
    service.create(user, "Mua he")
    service.bind_activity(user, org, activity_id, ["Mua he"])
    listed = service.list_tags(user)
    assert listed[0].activity_count == 1
    assert listed[0].activities[0].activity_id == activity_id
    assert listed[0].activities[0].draft is True
    assert listed[0].post_count == 0


class Retag:
    def __init__(self) -> None:
        self.calls: list[tuple[object, str, str | None, set[object]]] = []
        self.guards: list[tuple[object, str]] = []

    def guard_replacement(self, org_id, replacement) -> None:  # noqa: ANN001
        self.guards.append((org_id, replacement))

    def retag(self, org_id, slug, replacement, now, only=None) -> list:  # noqa: ANN001
        self.calls.append((org_id, slug, replacement, set(only or [])))
        return []


def test_delete_retags_only_the_caller_activities() -> None:
    user = uuid4()
    org = uuid4()
    activity_id = uuid4()
    retag = Retag()
    service = UserTagService(  # type: ignore[arg-type]
        Store(), Posts(), activity_tags=retag
    )
    service.create(user, "Mua he")
    service.bind_activity(user, org, activity_id, ["Mua he"])
    service.delete(user, "mua-he")
    assert retag.calls == [(org, "mua-he", None, {activity_id})]
    assert service._store.activities_for(user, "mua-he") == []  # noqa: SLF001


def test_same_slug_rename_does_not_rewrite_activities() -> None:
    user = uuid4()
    org = uuid4()
    activity_id = uuid4()
    retag = Retag()
    service = UserTagService(  # type: ignore[arg-type]
        Store(), Posts(), activity_tags=retag
    )
    service.create(user, "Mua he")
    service.bind_activity(user, org, activity_id, ["Mua he"])
    service.rename(user, "mua-he", "MUA HE")
    assert retag.calls == []
    assert retag.guards == []


def test_slug_change_guards_before_writing() -> None:
    from core.exceptions import TagDeletedError

    user = uuid4()
    org = uuid4()
    activity_id = uuid4()
    retag = Retag()

    def refuse(org_id, replacement) -> None:  # noqa: ANN001
        retag.guards.append((org_id, replacement))
        raise TagDeletedError("Tag is in the trash.")

    retag.guard_replacement = refuse  # type: ignore[method-assign]
    service = UserTagService(  # type: ignore[arg-type]
        Store(), Posts(), activity_tags=retag
    )
    service.create(user, "Mua he")
    service.bind_activity(user, org, activity_id, ["Mua he"])
    with pytest.raises(TagDeletedError):
        service.rename(user, "mua-he", "Bi cam")
    assert retag.calls == []
    assert service.list_tags(user)[0].slug == "mua-he"


def test_update_by_a_co_manager_stays_on_the_author() -> None:
    activities = FakeActivities()
    orgs = FakeOrgs()
    owner = uuid_utils.uuid7()
    editor = uuid_utils.uuid7()
    org = _org_with_owner(orgs, owner, "book-org-editor")
    access = FakeAccess()
    access.perms[(org.id, editor)] = {"activity:manage"}
    book = Book()
    service = ActivityService(
        activities=activities,
        categories=FakeCategories(),
        orgs=orgs,
        access=access,
        tags=TagService(FakeOrgTags(activities)),
        user_tags=book,
    )
    row = service.create_activity(
        org.id, owner, _fields(service, tag_names=["Mua he"])
    )
    book.claimed_by.clear()
    book.bound_by.clear()
    service.update_activity(
        org.id,
        row.id,
        editor,
        _fields(service, tag_names=["Mua he", "Sach"]),
    )
    assert book.claimed_by == [owner]
    assert book.bound_by == [owner]


def test_catalog_rename_moves_the_author_edge() -> None:
    from datetime import datetime

    from activities.user_tag_activities import follow_catalog

    user = uuid4()
    org = uuid4()
    activity_id = uuid4()
    store = Store()
    service = UserTagService(store, Posts(), activity_heads=_heads(  # type: ignore[arg-type]
        activity_id, ["Mua dong"]
    ))
    service.create(user, "Mua he")
    service.bind_activity(user, org, activity_id, ["Mua he"])
    follow_catalog(
        store,  # type: ignore[arg-type]
        user,
        org,
        activity_id,
        "mua-he",
        "mua-dong",
        "Mua dong",
        datetime(2026, 10, 24, 8, 0, 0),
    )
    listed = {row.slug: row for row in service.list_tags(user)}
    assert listed["mua-dong"].activity_count == 1
    assert listed["mua-dong"].activities[0].activity_id == activity_id
    assert listed["mua-he"].activity_count == 0


def test_activity_edge_read_is_not_capped() -> None:
    import inspect

    from activities.user_tag_store import CqlUserTagStore

    assert "limit(" not in inspect.getsource(CqlUserTagStore.activities_for)


def _heads(activity_id: object, names: list[str]) -> object:
    rows = {
        activity_id: SimpleNamespace(
            title="Don dep",
            tag_names=names,
            status="draft",
            deleted_at=None,
        )
    }

    class Heads:
        def get(self, wanted: object) -> object | None:
            return rows.get(wanted)

    return Heads()
