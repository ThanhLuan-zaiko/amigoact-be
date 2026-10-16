"""auth_sessions: creation on login, touch on refresh, revoke paths."""

from __future__ import annotations

from auth.session_service import SessionService
from core.exceptions import NotFoundError
from tests.unit.auth_fakes import (
    EMAIL,
    PASSWORD,
    FakeRefresh,
    FakeSessions,
    make_service,
    verified_pair,
)


def test_login_creates_session() -> None:
    service, parts = make_service()
    pair = verified_pair(service, parts)
    sessions: FakeSessions = parts["sessions"]
    assert len(sessions.rows) == 1
    row = next(iter(sessions.rows.values()))
    assert row.ip == "127.0.0.1"
    assert row.revoked_at is None
    refresh: FakeRefresh = parts["refresh_tokens"]
    token_row = next(iter(refresh.rows.values()))
    assert row.session_id == token_row.family_id
    assert pair.access_token


def test_refresh_touches_session() -> None:
    service, parts = make_service()
    pair = verified_pair(service, parts)
    sessions: FakeSessions = parts["sessions"]
    row = next(iter(sessions.rows.values()))
    seen = row.last_seen_at
    service.refresh(pair.refresh_token, "10.0.0.1")
    assert row.last_seen_at >= seen


def test_logout_revokes_session_row() -> None:
    service, parts = make_service()
    pair = verified_pair(service, parts)
    service.logout(pair.refresh_token)
    sessions: FakeSessions = parts["sessions"]
    row = next(iter(sessions.rows.values()))
    assert row.revoked_at is not None


def test_logout_all_revokes_every_session() -> None:
    service, parts = make_service()
    verified_pair(service, parts)
    service.login(EMAIL, PASSWORD, "10.0.0.2")
    user_id = next(iter(parts["sessions"].rows.values())).user_id
    service.logout_all(user_id)
    assert all(r.revoked_at is not None for r in parts["sessions"].list_mine(user_id))


def test_session_service_lists_and_revokes() -> None:
    service, parts = make_service()
    pair = verified_pair(service, parts)
    sessions: FakeSessions = parts["sessions"]
    refresh: FakeRefresh = parts["refresh_tokens"]
    user_id = next(iter(sessions.rows.values())).user_id
    svc = SessionService(sessions=sessions, refresh_tokens=refresh)

    views = svc.list_mine(user_id, None)
    assert len(views) == 1 and views[0].current is False
    token_hash = next(iter(refresh.rows))
    views = svc.list_mine(user_id, token_hash)
    assert views[0].current is True

    session_id = views[0].session_id
    svc.revoke(user_id, session_id)
    assert sessions.get(user_id, session_id).revoked_at is not None
    assert refresh.rows[token_hash].revoked_at is not None
    # After revocation the stored refresh token no longer rotates.
    try:
        service.refresh(pair.refresh_token, "10.0.0.3")
    except Exception:  # noqa: BLE001
        pass
    else:  # pragma: no cover
        raise AssertionError("revoked family must not rotate")


def test_session_revoke_unknown_raises() -> None:
    service, parts = make_service()
    verified_pair(service, parts)
    sessions: FakeSessions = parts["sessions"]
    svc = SessionService(sessions=sessions, refresh_tokens=parts["refresh_tokens"])
    from core.ids import uuid7

    user_id = next(iter(sessions.rows.values())).user_id
    try:
        svc.revoke(user_id, uuid7())
    except NotFoundError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected NotFoundError")
