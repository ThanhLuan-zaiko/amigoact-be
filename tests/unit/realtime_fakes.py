"""Shared in-memory ports + WS app fixture for realtime unit tests."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import uuid_utils
from fastapi import WebSocket
from fastapi.testclient import TestClient

from core.config import Settings
from core.realtime import ConnectionManager
from realtime.interfaces import (
    AttendanceAccess,
    OrgMembership,
    PresenceDirectory,
    WsTicketStore,
)
from realtime.service import RealtimeService


def uid() -> UUID:
    return UUID(str(uuid_utils.uuid7()))


class MemTickets(WsTicketStore):
    """In-memory single-use ticket rows."""

    def __init__(self) -> None:
        self.rows: dict[str, SimpleNamespace] = {}

    def create(self, ticket_hash, user_id, expires_at, now) -> None:  # noqa: ANN001, ANN202
        self.rows[ticket_hash] = SimpleNamespace(
            ticket_hash=ticket_hash,
            user_id=user_id,
            expires_at=expires_at,
            created_at=now,
        )

    def consume(self, ticket_hash):  # noqa: ANN001, ANN202
        return self.rows.pop(ticket_hash, None)


class FakeMembership(OrgMembership):
    """Channel ACL pairs: (org_id, user_id) that count as members."""

    def __init__(self, pairs: set[tuple[UUID, UUID]] | None = None) -> None:
        self._pairs = pairs or set()

    def is_member(self, org_id: UUID, user_id: UUID) -> bool:
        return (org_id, user_id) in self._pairs


class FakeAttendance(AttendanceAccess):
    """Live-feed ACL pairs: (activity_id, user_id) allowed to watch."""

    def __init__(self, pairs: set[tuple[UUID, UUID]] | None = None) -> None:
        self._pairs = pairs or set()

    def can_view(self, activity_id: UUID, user_id: UUID) -> bool:
        return (activity_id, user_id) in self._pairs


class FakePresence(PresenceDirectory):
    """Active-membership pairs for presence fan-out and snapshots."""

    def __init__(self, pairs: set[tuple[UUID, UUID]] | None = None) -> None:
        self._pairs = pairs or set()

    def orgs_of(self, user_id: UUID) -> list[UUID]:
        return sorted(org for org, user in self._pairs if user == user_id)

    def member_ids_of(self, org_id: UUID) -> list[UUID]:
        return sorted(user for org, user in self._pairs if org == org_id)


def make_service(
    store: MemTickets | None = None,
    members: OrgMembership | None = None,
    attendance: AttendanceAccess | None = None,
    ticket_ttl_seconds: int = 60,
    presence: PresenceDirectory | None = None,
) -> RealtimeService:
    return RealtimeService(
        tickets=store or MemTickets(),
        membership=members or FakeMembership(),
        attendance=attendance,
        ticket_ttl_seconds=ticket_ttl_seconds,
        presence=presence,
    )


class FakeSocket:
    """Duck-typed WebSocket recording every frame and close code."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.closed: int | None = None

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = code


def ws(sock: FakeSocket) -> WebSocket:
    return cast(WebSocket, sock)


_ACTIVE_USER_PATCH: Any = None


def ws_app(
    members: FakeMembership | None = None,
    attendance: AttendanceAccess | None = None,
    heartbeat: int = 120,
    pong_timeout: int = 120,
    presence: PresenceDirectory | None = None,
) -> tuple[TestClient, MemTickets, RealtimeService]:
    """App with realtime deps swapped for in-memory fakes (no ScyllaDB)."""
    import main
    from core.config import get_settings
    from core.dependencies import get_realtime_service
    from core.realtime import ConnectionManager

    global _ACTIVE_USER_PATCH
    from unittest import mock

    class _ActiveUsers:
        """Router-level user check always sees an active account."""

        def __init__(self, *_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
            pass

        def get_by_id(self, user_id):  # noqa: ANN001, ANN202
            return SimpleNamespace(id=user_id, status="active")

    _ACTIVE_USER_PATCH = mock.patch(
        "auth.repository.CqlUserRepository", _ActiveUsers
    )
    _ACTIVE_USER_PATCH.start()

    store = MemTickets()
    service = RealtimeService(
        store, members or FakeMembership(), attendance, 60, presence
    )
    settings = Settings(
        jwt_secret="unit-test-secret-32-bytes-padded!",
        env="dev",
        ws_heartbeat_seconds=heartbeat,
        ws_pong_timeout_seconds=pong_timeout,
    )
    if getattr(main.app.state, "ws_manager", None) is None:
        main.app.state.ws_manager = ConnectionManager()
    main.app.dependency_overrides.update(
        {
            get_realtime_service: lambda: service,
            get_settings: lambda: settings,
        }
    )
    return TestClient(main.app), store, service


def clear_overrides() -> None:
    import main

    main.app.dependency_overrides.clear()
    global _ACTIVE_USER_PATCH
    if _ACTIVE_USER_PATCH is not None:
        _ACTIVE_USER_PATCH.stop()
        _ACTIVE_USER_PATCH = None
