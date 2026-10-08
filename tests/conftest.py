"""Shared fixtures: real ScyllaDB test keyspace plus HTTP app client."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import os

os.environ.setdefault("CQLENG_ALLOW_SCHEMA_MANAGEMENT", "1")

import pytest
from httpx import ASGITransport, AsyncClient

import core.database  # noqa: F401  (reactor compat shim must run first)
from core.config import Settings, get_settings


TEST_KEYSPACE = "amigoact_test"
TEST_JWT_SECRET = "integration-test-secret-32-bytes!"

TABLES = [
    "users",
    "users_by_email",
    "users_by_phone",
    "auth_refresh_tokens",
    "refresh_tokens_by_user",
    "refresh_tokens_by_family",
    "email_verifications",
    "password_resets",
    "auth_rate_limits",
    "organizations",
    "organizations_by_slug",
    "organization_members",
    "members_by_user",
    "media_assets",
    "media_by_owner",
]


def _test_settings() -> Settings:
    return Settings(
        scylla_hosts="127.0.0.1",
        scylla_keyspace=TEST_KEYSPACE,
        jwt_secret=TEST_JWT_SECRET,
        env="dev",
    )


def _scylla_reachable(host: str, port: int) -> bool:
    """TCP probe so CI without ScyllaDB skips with reason instead of failing."""
    import socket

    sock = socket.socket()
    sock.settimeout(2.0)
    try:
        return sock.connect_ex((host, port)) == 0
    except OSError:
        return False
    finally:
        sock.close()


@pytest.fixture(scope="session")
def test_db() -> str:
    """Create amigoact_test once and sync auth tables (migration stand-in)."""
    if not _scylla_reachable("127.0.0.1", 9042):
        pytest.skip("ScyllaDB unavailable at 127.0.0.1:9042")
    from cassandra.cluster import Cluster
    from cassandra.cqlengine import connection
    from cassandra.cqlengine.management import sync_table
    from cassandra.io.asyncioreactor import AsyncioConnection

    import auth.model as models
    import orgs.model as org_models

    cluster = Cluster(
        ["127.0.0.1"],
        port=9042,
        protocol_version=4,
        connection_class=AsyncioConnection,
        connect_timeout=10.0,
    )
    session = cluster.connect()
    try:
        session.execute(
            f"CREATE KEYSPACE IF NOT EXISTS {TEST_KEYSPACE}"
            " WITH replication = {"
            " 'class': 'NetworkTopologyStrategy', 'datacenter1': 1}"
        )
    finally:
        cluster.shutdown()

    targets = [
        models.User,
        models.UsersByEmail,
        models.UsersByPhone,
        models.AuthRefreshToken,
        models.RefreshTokenByUser,
        models.RefreshTokenByFamily,
        models.EmailVerification,
        models.PasswordReset,
        org_models.Organization,
        org_models.OrganizationsBySlug,
        org_models.OrganizationMember,
        org_models.MemberByUser,
        org_models.MediaAsset,
        org_models.MediaByOwner,
    ]
    saved = {model: model.__keyspace__ for model in targets}
    try:
        for model in targets:
            model.__keyspace__ = TEST_KEYSPACE
        connection.setup(["127.0.0.1"], TEST_KEYSPACE, protocol_version=4)
        for model in targets:
            sync_table(model)
        # Counter tables have no cqlengine model; mirror schemas.cql here.
        raw = connection.get_session()
        raw.execute(
            f"CREATE TABLE IF NOT EXISTS {TEST_KEYSPACE}.auth_rate_limits ("
            " bucket text, window_start timestamp, hits counter,"
            " PRIMARY KEY ((bucket), window_start))"
        )
        yield TEST_KEYSPACE
    finally:
        for model, keyspace in saved.items():
            model.__keyspace__ = keyspace


@pytest.fixture()
def clean_tables(test_db: str) -> str:
    """Truncate every auth table so tests never depend on order."""
    del test_db
    from cassandra.cqlengine.connection import get_session

    session = get_session()
    for table in TABLES:
        session.execute(f"TRUNCATE {TEST_KEYSPACE}.{table}")
    return TEST_KEYSPACE


@pytest.fixture()
def app_client(clean_tables: str):
    """FastAPI app with test settings (overrides cleared after each test)."""
    import main

    main.app.dependency_overrides[get_settings] = _test_settings
    try:
        yield main.app
    finally:
        main.app.dependency_overrides.clear()


@pytest.fixture()
async def client(app_client) -> AsyncGenerator[AsyncClient, None]:
    """HTTP client speaking to the app over ASGI (lazy routes resolve)."""
    transport = ASGITransport(app=app_client)
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as http:
        yield http
