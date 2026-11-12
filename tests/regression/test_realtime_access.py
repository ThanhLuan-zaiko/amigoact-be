"""Who may listen to which topic, on subscribe and after losing access."""

import uuid

from tests.activity_helpers import Bearer, user
from tests.conftest import ApiContext
from tests.post_helpers import join, open_org
from tests.realtime_helpers import (
    frames_until_pong,
    org_id_of,
    realtime_ticket,
    subscribe,
)

NOT_FOUND = {"op": "error", "code": "topic_not_found"}


def test_outsiders_and_members_get_only_their_topics(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, owner_id = user(api, bearer, "owner")
    member, _ = user(api, bearer, "member")
    stranger, _ = user(api, bearer, "stranger")
    slug = open_org(api, owner)
    join(api, slug, member)
    org_id = org_id_of(api, slug, owner)

    with api.client.websocket_connect(
        f"/ws?ticket={realtime_ticket(api, member)}"
    ) as ws:
        assert subscribe(ws, f"org:{org_id}")["op"] == "subscribed"
        assert subscribe(ws, f"org-managers:{org_id}") == NOT_FOUND
        assert subscribe(ws, f"user:{owner_id}") == NOT_FOUND
    with api.client.websocket_connect(
        f"/ws?ticket={realtime_ticket(api, stranger)}"
    ) as ws:
        assert subscribe(ws, f"org:{org_id}") == NOT_FOUND
        assert subscribe(ws, f"room:{org_id}") == NOT_FOUND
        assert subscribe(ws, f"org:{uuid.uuid7()}") == NOT_FOUND
        assert subscribe(ws, "post:1") == {"op": "error", "code": "topic_invalid"}


def test_demoted_admin_loses_the_review_topic(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    admin, admin_id = user(api, bearer, "admin")
    slug = open_org(api, owner)
    join(api, slug, admin)
    path = f"/organizations/{slug}/members/{admin_id}"
    api.client.patch(path, headers=owner, json={"role": "admin"})
    review = f"org-managers:{org_id_of(api, slug, owner)}"

    with api.client.websocket_connect(
        f"/ws?ticket={realtime_ticket(api, admin)}"
    ) as ws:
        assert subscribe(ws, review)["op"] == "subscribed"
        api.client.patch(path, headers=owner, json={"role": "member"})
        frames = frames_until_pong(ws)
        again = subscribe(ws, review)

    assert {"op": "revoked", "topic": review} in frames
    assert again == NOT_FOUND


def test_removed_member_loses_every_org_topic(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    member, member_id = user(api, bearer, "member")
    slug = open_org(api, owner)
    join(api, slug, member)
    members = f"org:{org_id_of(api, slug, owner)}"

    with api.client.websocket_connect(
        f"/ws?ticket={realtime_ticket(api, member)}"
    ) as ws:
        subscribe(ws, members)
        api.client.delete(f"/organizations/{slug}/members/{member_id}", headers=owner)
        frames = frames_until_pong(ws)
        api.client.patch(f"/organizations/{slug}", headers=owner, json={"city": "Hue"})
        later = frames_until_pong(ws)

    assert {"op": "revoked", "topic": members} in frames
    # Events after the cut never reach the removed member.
    assert [f for f in later if f.get("topic") == members] == []
