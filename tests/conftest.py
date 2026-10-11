"""Shared fixtures: real ScyllaDB test keyspace plus HTTP app client."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import os

os.environ.setdefault("CQLENG_ALLOW_SCHEMA_MANAGEMENT", "1")

import tempfile

import pytest
from httpx import ASGITransport, AsyncClient

import core.database  # noqa: F401  (reactor compat shim must run first)
from core.config import Settings, get_settings

# Isolated media root: the test keyspace knows nothing about dev orgs, so
# sharing ./media would let sweep_orphans wipe real dev uploads.
os.environ["MEDIA_ROOT"] = tempfile.mkdtemp(prefix="amigoact-test-media-")


# Each pytest-xdist worker owns an isolated keyspace so parallel runs never
# truncate data another worker is using.
_WORKER = os.environ.get("PYTEST_XDIST_WORKER", "")
TEST_KEYSPACE = "amigoact_test" + (f"_{_WORKER}" if _WORKER else "")
TEST_JWT_SECRET = "integration-test-secret-32-bytes!"

# Bare Settings() reads env (TestClient lifespan resolves get_settings());
# guarantee the required secret exists on CI runners without .env.
os.environ["JWT_SECRET"] = TEST_JWT_SECRET

TEST_ADMIN_EMAIL = "root@amigoact.test"

# Table map filled once by test_db from cluster metadata: every table in the
# keyspace with its partition-key columns. clean_tables deletes dirty rows
# by partition key (write path) instead of TRUNCATE (a schema op serialized
# cluster-wide at ~0.4s per table).
TABLE_PK: dict[str, list[str]] = {}

# Counter tables must not be row-deleted: increments on tombstoned counters
# return inconsistent values, so they still get a real TRUNCATE.
COUNTER_TABLES: set[str] = set()


def _test_settings() -> Settings:
    return Settings(
        scylla_hosts="127.0.0.1",
        scylla_keyspace=TEST_KEYSPACE,
        jwt_secret=TEST_JWT_SECRET,
        env="dev",
        platform_admin_emails=TEST_ADMIN_EMAIL,
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

    import activities.model as activity_models
    import admin.model as admin_models
    import auth.model as models
    import certificates.model as cert_models
    import hours.model as hour_models
    import notifications.model as notification_models
    import orgs.model as org_models
    import profiles.model as profile_models
    import rbac.model as rbac_models
    import realtime.model as realtime_models
    import registrations.model as reg_models
    import reviews.model as review_models

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
        org_models.OrganizationsByTaxCode,
        org_models.OrganizationsByLegalStatus,
        org_models.OrganizationMember,
        org_models.MemberByUser,
        org_models.MediaAsset,
        org_models.MediaByOwner,
        org_models.MediaByHash,
        org_models.MediaByUploader,
        rbac_models.Role,
        rbac_models.RolesByOrg,
        rbac_models.Permission,
        rbac_models.RolePermission,
        rbac_models.UserRole,
        rbac_models.RolesByUser,
        rbac_models.UserPermissionGrant,
        rbac_models.AccessAuditLog,
        rbac_models.AccessAuditByResource,
        admin_models.PlatformUserRole,
        admin_models.PlatformRoleRoster,
        notification_models.Notification,
        notification_models.NotificationsByUser,
        profile_models.StudentProfile,
        profile_models.EmergencyContact,
        profile_models.Skill,
        profile_models.SkillBySlug,
        profile_models.UserSkill,
        profile_models.UserBySkill,
        activity_models.Activity,
        activity_models.ActivitiesByOrg,
        activity_models.ActivitiesByStatus,
        activity_models.ActivitiesByCategory,
        activity_models.ActivitiesBySlug,
        activity_models.ActivityCategory,
        activity_models.ActivitySkill,
        activity_models.ActivityPartner,
        activity_models.PartnerActivitiesByOrg,
        activity_models.ActivitySchedule,
        activity_models.ScheduleByActivity,
        activity_models.ActivityStaff,
        activity_models.ActivityAnnouncement,
        reg_models.Registration,
        reg_models.RegistrationsByActivity,
        reg_models.RegistrationsByStudent,
        reg_models.RegistrationsByActivityStudent,
        reg_models.RegistrationsByToken,
        reg_models.RegistrationStatusHistory,
        reg_models.AttendanceRecord,
        reg_models.AttendanceByRegistration,
        reg_models.AttendanceByActivity,
        reg_models.AttendanceByStudent,
        hour_models.VolunteerHourEntry,
        hour_models.HoursByStudent,
        hour_models.HourEntriesByStudent,
        hour_models.HoursByActivity,
        hour_models.PendingHoursByOrg,
        hour_models.HourAdjustment,
        hour_models.LeaderboardByTerm,
        hour_models.LeaderboardTerm,
        review_models.ReviewsByActivity,
        review_models.ReviewsByStudent,
        notification_models.NotificationPreference,
        cert_models.Certificate,
        cert_models.CertificatesByStudent,
        cert_models.CertificatesBySerial,
        cert_models.CertificateRevocation,
        realtime_models.WsTicket,
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
        raw.cluster.refresh_keyspace_metadata(TEST_KEYSPACE)
        tables_meta = raw.cluster.metadata.keyspaces[TEST_KEYSPACE].tables
        TABLE_PK.update(
            {
                name: [column.name for column in table.partition_key]
                for name, table in tables_meta.items()
                if "$" not in name  # Scylla LWT side-tables are not CQL-legal
            }
        )
        COUNTER_TABLES.update(
            name
            for name, table in tables_meta.items()
            if any(
                column.cql_type == "counter"
                for column in table.columns.values()
            )
        )
        yield TEST_KEYSPACE
    finally:
        for model, keyspace in saved.items():
            model.__keyspace__ = keyspace


@pytest.fixture()
def clean_tables(test_db: str) -> str:
    """Empty every table that actually holds rows.

    TRUNCATE is a schema operation (~0.4s per table, serialized cluster-
    wide), so wiping all 70+ tables before every test dominated the suite.
    Instead: a LIMIT 1 read per table pipelines to ~50ms total, then rows in
    dirty tables are deleted by partition key — plain writes that run
    concurrently and never wait on schema agreement. Counter tables still
    get a real TRUNCATE because increments on tombstoned counters are
    inconsistent. The post-fixture guarantee is unchanged: every table
    starts empty.
    """
    del test_db
    if not TABLE_PK:
        raise RuntimeError("test_db ran but no table metadata was captured")
    from cassandra.cqlengine.connection import get_session

    session = get_session()
    probes = {
        table: session.execute_async(
            f"SELECT * FROM {TEST_KEYSPACE}.{table} LIMIT 1"
        )
        for table in TABLE_PK
    }
    deletes = []
    key_reads = []
    for table, probe in probes.items():
        if not probe.result().current_rows:
            continue
        if table in COUNTER_TABLES:
            # Never row-delete counters (increments on tombstoned counters
            # resurrect stale shards); a dirty probe means a real TRUNCATE.
            session.execute(f"TRUNCATE {TEST_KEYSPACE}.{table}")
            continue
        columns = TABLE_PK[table]
        key_reads.append(
            (
                table,
                session.execute_async(
                    f"SELECT {', '.join(columns)}"
                    f" FROM {TEST_KEYSPACE}.{table}"
                ),
            )
        )
    for table, future in key_reads:
        columns = TABLE_PK[table]
        where = " AND ".join(f"{column} = %s" for column in columns)
        for row in future.result():
            deletes.append(
                session.execute_async(
                    f"DELETE FROM {TEST_KEYSPACE}.{table} WHERE {where}",
                    tuple(row[column] for column in columns),
                )
            )
    for future in deletes:
        future.result()
    # Deleting wipes the seeded catalog; re-seed so role checks work. The
    # three seeders write disjoint tables — run them in parallel since the
    # driver session is thread-safe.
    from concurrent.futures import ThreadPoolExecutor

    from activities.seed import seed_categories
    from profiles.seed import seed_skills
    from rbac.seed import seed_rbac

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda fn: fn(), (seed_rbac, seed_skills, seed_categories)))
    return TEST_KEYSPACE


@pytest.fixture()
def app_client(clean_tables: str):
    """FastAPI app with test settings (overrides cleared after each test)."""
    import core.hashing as hashing
    import main
    from core.realtime import ConnectionManager

    # The app under test still exercises real Argon2id hash/verify, just
    # with the cheap documented test params — full-cost hashing is covered
    # by tests/unit/test_hashing.py.
    prod_hasher = hashing._default_hasher
    hashing._default_hasher = hashing.build_hasher(for_tests=True)
    main.app.dependency_overrides[get_settings] = _test_settings
    if getattr(main.app.state, "ws_manager", None) is None:
        main.app.state.ws_manager = ConnectionManager()
    try:
        yield main.app
    finally:
        hashing._default_hasher = prod_hasher
        main.app.dependency_overrides.clear()


@pytest.fixture()
async def client(app_client) -> AsyncGenerator[AsyncClient, None]:
    """HTTP client speaking to the app over ASGI (lazy routes resolve)."""
    transport = ASGITransport(app=app_client)
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as http:
        yield http
