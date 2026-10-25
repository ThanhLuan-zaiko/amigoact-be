"""Regression locks for the browse feed, the signed-in view and events:feed."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import uuid_utils
from fastapi.routing import APIRoute

from activities.browse_schemas import (
    BrowseFacets,
    BrowseItem,
    BrowseOrg,
    BrowsePage,
    MineBrowseItem,
    MineBrowsePage,
    MineFacets,
    MyRegistration,
    StatusFacet,
)
from activities.model import tag_slug
from core.realtime import CHANNEL_KINDS, PUBLIC_CHANNEL_SUBJECTS
from registrations.schemas import RegistrationBriefResponse
from tests.unit.activity_fakes import (
    _fields,
    _org_with_owner,
    make_services,
)


def _flat_routes() -> list[tuple[str, frozenset[str]]]:
    import main

    flat: list[tuple[str, frozenset[str]]] = []
    for route in main.app.routes:
        children = getattr(
            getattr(route, "original_router", None), "routes", [route]
        )
        for child in children:
            if isinstance(child, APIRoute):
                flat.append((child.path, frozenset(child.methods)))
    return flat


def test_browse_route_is_mounted_before_the_activity_id_route() -> None:
    # Otherwise /activities/browse is captured by /activities/{activity_id}
    # and answers 422 for a non-UUID path segment.
    paths = [path for path, _ in _flat_routes()]
    assert paths.index("/activities/browse") < paths.index(
        "/activities/{activity_id}"
    )


def test_signed_in_and_brief_routes_are_registered() -> None:
    routes = dict(_flat_routes())
    assert routes["/activities/browse/mine"] == frozenset({"GET"})
    assert routes["/registrations/mine/brief"] == frozenset({"GET"})


def test_browse_contract_keys_are_frozen() -> None:
    assert set(BrowsePage.model_fields) == {"items", "total", "truncated", "facets"}
    assert set(BrowseFacets.model_fields) == {"cities", "categories", "tags"}
    assert set(BrowseOrg.model_fields) == {"id", "name", "slug", "logo_url", "verified"}
    assert set(BrowseItem.model_fields) == {
        "id", "org_id", "slug", "title", "status", "phase",
        "start_at", "end_at", "city", "location", "is_remote",
        "hours_awarded", "category_id", "tags", "excerpt", "cover_url",
        "max_participants", "registered_count", "seats_left",
        "registration_deadline", "registration_open", "org",
    }


def test_public_item_has_no_per_viewer_field() -> None:
    # The public feed is cacheable across accounts; per-viewer data stays
    # on the signed-in model only.
    assert "my_registration" not in BrowseItem.model_fields
    assert "my_registration" in MineBrowseItem.model_fields
    assert set(MineBrowsePage.model_fields) == {"items", "total", "truncated", "facets"}
    assert set(MineFacets.model_fields) == {"cities", "categories", "tags", "my_status"}
    assert set(StatusFacet.model_fields) == {"status", "count"}
    assert set(MyRegistration.model_fields) == {"registration_id", "status", "registered_at"}


def test_brief_response_keys_are_frozen() -> None:
    assert set(RegistrationBriefResponse.model_fields) == {
        "activity_id", "registration_id", "status", "registered_at",
    }


def test_events_channel_is_a_public_literal_subject() -> None:
    assert "events" in CHANNEL_KINDS
    assert PUBLIC_CHANNEL_SUBJECTS["events"] == "feed"


def test_legacy_category_feed_never_serves_drafts() -> None:
    service, _, _, orgs, _, categories, *_ = make_services()
    owner = uuid_utils.uuid7()
    org = _org_with_owner(orgs, owner)
    category = categories.seed("Moi truong", "moi-truong")
    service.create_activity(
        org.id, owner, _fields(None, category_id=category.id)
    )
    # Still a draft: the category feed holds it, the public list must not.
    assert service.list_public("published", category_id=category.id) == []


def test_legacy_tag_feed_honours_the_requested_status() -> None:
    service, _, _, orgs, _, _, *_ = make_services()
    owner = uuid_utils.uuid7()
    org = _org_with_owner(orgs, owner)
    start = datetime.now(UTC) + timedelta(days=7)
    row = service.create_activity(
        org.id,
        owner,
        _fields(None, tag_names=["Moi truong"], start_at=start),
    )
    service.set_status(org.id, row.id, owner, "published")
    slug = tag_slug("Moi truong")
    assert len(service.list_public("published", tag_slug=slug)) == 1
    assert service.list_public("completed", tag_slug=slug) == []
