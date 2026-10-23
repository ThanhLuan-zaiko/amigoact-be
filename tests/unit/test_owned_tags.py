"""Unit tests: copy-suggestions stay inside orgs the caller owns."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import uuid_utils

from activities.owned_tag_service import OwnedTagService
from core.exceptions import ForbiddenError, NotFoundError
from tests.unit.activity_fakes import FakeActivities, FakeOrgs, _org_with_owner
from tests.unit.tag_fakes import FakeOrgTags
from tests.unit.test_org_tags import _claim

NOW = datetime.now(UTC)


def _service():
    tags = FakeOrgTags(FakeActivities())
    orgs = FakeOrgs()
    owner = uuid_utils.uuid7()
    source = _org_with_owner(orgs, owner, "owned-a")
    source.name = "Alpha Club"
    current = _org_with_owner(orgs, owner, "owned-b")
    current.name = "Beta Club"
    return OwnedTagService(tags, orgs), tags, orgs, owner, source, current


def test_lists_live_tags_from_other_owned_orgs() -> None:
    service, tags, _, owner, source, current = _service()
    _claim(tags, source.id, "Hoc bong")
    rows = service.list_owned(current.id, owner)
    assert [(row.name, row.slug, row.org_name) for row in rows] == [
        ("Hoc bong", "hoc-bong", "Alpha Club")
    ]


def test_skips_slugs_already_in_the_current_org() -> None:
    service, tags, _, owner, source, current = _service()
    _claim(tags, source.id, "Hoc bong")
    _claim(tags, current.id, "Hoc bong")
    assert service.list_owned(current.id, owner) == []


def test_skips_a_slug_sitting_in_the_current_trash() -> None:
    service, tags, _, owner, source, current = _service()
    _claim(tags, source.id, "Hoc bong")
    blocked = _claim(tags, current.id, "Hoc bong")
    blocked.deleted_at = NOW
    assert service.list_owned(current.id, owner) == []


def test_skips_trashed_tags_and_deleted_orgs() -> None:
    service, tags, orgs, owner, source, current = _service()
    trashed = _claim(tags, source.id, "Y te")
    trashed.deleted_at = NOW
    gone = _org_with_owner(orgs, owner, "owned-gone")
    gone.name = "Gone Club"
    gone.deleted_at = NOW
    _claim(tags, gone.id, "Cu")
    assert service.list_owned(current.id, owner) == []


def test_keeps_both_spellings_and_dedupes_the_same_pair() -> None:
    service, tags, orgs, owner, source, current = _service()
    _claim(tags, source.id, "Hoc bong")
    other = _org_with_owner(orgs, owner, "owned-c")
    other.name = "Cedar Club"
    _claim(tags, other.id, "HOC BONG")
    third = _org_with_owner(orgs, owner, "owned-d")
    third.name = "Delta Club"
    _claim(tags, third.id, "Hoc bong")
    rows = service.list_owned(current.id, owner)
    assert [(row.name, row.org_name) for row in rows] == [
        ("Hoc bong", "Alpha Club"),
        ("HOC BONG", "Cedar Club"),
    ]


def test_member_only_sees_orgs_they_own() -> None:
    service, tags, orgs, owner, source, current = _service()
    _claim(tags, source.id, "Hoc bong")
    member = uuid_utils.uuid7()
    orgs.members[current.id].add(member)
    theirs = _org_with_owner(orgs, member, "owned-member")
    theirs.name = "Member Club"
    _claim(tags, theirs.id, "Rieng")
    rows = service.list_owned(current.id, member)
    assert [row.org_name for row in rows] == ["Member Club"]


def test_outsider_and_missing_org_are_rejected() -> None:
    service, _, _, _, _, current = _service()
    with pytest.raises(ForbiddenError):
        service.list_owned(current.id, uuid_utils.uuid7())
    current.deleted_at = NOW
    with pytest.raises(NotFoundError):
        service.list_owned(current.id, uuid_utils.uuid7())
