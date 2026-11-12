import json

from sqlalchemy import text

from src.app import app
from src.realtime import bus
from tests.activity_helpers import Bearer, make_org, user
from tests.conftest import ApiContext
from tests.notification_helpers import apply
from tests.post_helpers import join, open_org
from tests.realtime_helpers import (
    event_types,
    frames_until_pong,
    org_id_of,
    realtime_ticket,
    subscribe,
)


def test_one_socket_hears_org_and_review_topics(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    applicant, applicant_id = user(api, bearer, "applicant")
    slug = make_org(api, owner)
    org_id = org_id_of(api, slug, owner)
    members, review = f"org:{org_id}", f"org-managers:{org_id}"

    with api.client.websocket_connect(
        f"/ws?ticket={realtime_ticket(api, owner)}"
    ) as ws:
        assert subscribe(ws, members) == {"op": "subscribed", "topic": members}
        assert subscribe(ws, review) == {"op": "subscribed", "topic": review}
        apply(api, slug, applicant, None)
        applied = frames_until_pong(ws)
        api.client.post(
            f"/organizations/{slug}/applications/{applicant_id}/approve", headers=owner
        )
        approved = frames_until_pong(ws)

    assert event_types(applied, review) == ["applications.changed"]
    assert event_types(applied, members) == []
    assert event_types(approved, review) == ["applications.changed"]
    assert event_types(approved, members) == ["members.changed"]
    assert approved[-1]["org_id"] == org_id


def test_own_topic_hears_membership_changes(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    joiner, joiner_id = user(api, bearer, "joiner")
    slug = open_org(api, owner)
    mine = f"user:{joiner_id}"

    with api.client.websocket_connect(
        f"/ws?ticket={realtime_ticket(api, joiner)}"
    ) as ws:
        join(api, slug, joiner)
        joined = frames_until_pong(ws)
        api.client.delete(f"/organizations/{slug}/membership", headers=joiner)
        left = frames_until_pong(ws)

    assert event_types(joined, mine) == ["membership.changed"]
    assert "membership.changed" in event_types(left, mine)


def test_role_change_reaches_the_member_list(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    member, member_id = user(api, bearer, "member")
    slug = open_org(api, owner)
    join(api, slug, member)
    members = f"org:{org_id_of(api, slug, owner)}"

    with api.client.websocket_connect(
        f"/ws?ticket={realtime_ticket(api, member)}"
    ) as ws:
        subscribe(ws, members)
        api.client.patch(
            f"/organizations/{slug}/members/{member_id}",
            headers=owner,
            json={"role": "admin"},
        )
        frames = frames_until_pong(ws)

    assert event_types(frames, members) == ["members.changed"]
    assert event_types(frames, f"user:{member_id}") == ["membership.changed"]


def test_events_from_another_worker_arrive(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    slug = open_org(api, owner)
    members = f"org:{org_id_of(api, slug, owner)}"
    message = {"o": "other-worker", "k": "emit", "t": members, "e": {"type": "ping"}}

    with api.client.websocket_connect(
        f"/ws?ticket={realtime_ticket(api, owner)}"
    ) as ws:
        subscribe(ws, members)
        with app.state.engine.begin() as connection:
            connection.execute(
                text("SELECT pg_notify(:channel, :payload)"),
                {"channel": bus.CHANNEL, "payload": json.dumps(message)},
            )
        frame = ws.receive_json()

    assert frame == {"type": "ping", "topic": members}


def test_chat_aliases_still_work(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    slug = open_org(api, owner)
    org_id = org_id_of(api, slug, owner)
    old_ticket = api.client.post("/chat/tickets", headers=owner).json()["ticket"]

    with api.client.websocket_connect(f"/ws/chat?ticket={old_ticket}") as ws:
        ws.send_json({"op": "subscribe", "room_id": org_id})
        assert ws.receive_json() == {"op": "subscribed", "room_id": org_id}
        assert subscribe(ws, f"room:{org_id}")["op"] == "subscribed"


def test_room_list_changes_reach_the_right_people(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, owner_id = user(api, bearer, "owner")
    member, member_id = user(api, bearer, "member")
    slug = open_org(api, owner)
    join(api, slug, member)
    members = f"org:{org_id_of(api, slug, owner)}"

    with api.client.websocket_connect(
        f"/ws?ticket={realtime_ticket(api, member)}"
    ) as ws:
        subscribe(ws, members)
        api.client.post(
            f"/organizations/{slug}/chat/channels",
            headers=owner,
            json={"name": "tin-tuc"},
        )
        created = frames_until_pong(ws)
        api.client.post(
            f"/organizations/{slug}/chat/dms",
            headers=owner,
            json={"user_id": member_id},
        )
        opened = frames_until_pong(ws)

    assert event_types(created, members) == ["rooms.changed"]
    assert event_types(opened, f"user:{member_id}") == ["rooms.changed"]
    assert owner_id not in str(opened)
