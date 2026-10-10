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


TEST_KEYSPACE = "amigoact_test"
TEST_JWT_SECRET = "integration-test-secret-32-bytes!"

# Bare Settings() reads env (TestClient lifespan resolves get_settings());
# guarantee the required secret exists on CI runners without .env.
os.environ["JWT_SECRET"] = TEST_JWT_SECRET

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
    "organizations_by_tax_code",
    "organizations_by_legal_status",
    "organization_members",
    "members_by_user",
    "media_assets",
    "media_by_owner",
    "media_by_hash",
    "media_by_uploader",
    "roles",
    "roles_by_org",
    "permissions",
    "role_permissions",
    "user_roles",
    "roles_by_user",
    "user_permission_grants",
    "access_audit_logs",
    "access_audit_by_resource",
    "platform_user_roles",
    "platform_role_roster",
    "notifications",
    "notifications_by_user",
    "ws_tickets",
    "student_profiles",
    "emergency_contacts",
    "skills",
    "skills_by_slug",
    "user_skills",
    "users_by_skill",
    "activities",
    "activities_by_org",
    "activities_by_status",
    "activities_by_category",
    "activities_by_slug",
    "activity_categories",
    "activity_skills",
    "activity_partners",
    "partner_activities_by_org",
    "activity_schedules",
    "schedules_by_activity",
    "activity_staff",
    "activity_announcements",
    "registrations",
    "registrations_by_activity",
    "registrations_by_student",
    "registrations_by_activity_student",
    "registrations_by_token",
    "registration_status_history",
    "attendance_records",
    "attendance_by_registration",
    "attendance_by_activity",
    "attendance_by_student",
    "volunteer_hour_ledger",
    "hours_by_student",
    "hour_entries_by_student",
    "hours_by_activity",
    "pending_hours_by_org",
    "hour_adjustments",
    "certificates",
    "certificates_by_student",
    "certificates_by_serial",
    "certificate_revocations",
    "leaderboard_by_term",
    "leaderboard_terms",
    "reviews_by_activity",
    "reviews_by_student",
    "notification_preferences",
]


TEST_ADMIN_EMAIL = "root@amigoact.test"


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
    # Truncating wipes the seeded catalog; re-seed so role checks work.
    from activities.seed import seed_categories
    from profiles.seed import seed_skills
    from rbac.seed import seed_rbac

    seed_rbac()
    seed_skills()
    seed_categories()
    return TEST_KEYSPACE


@pytest.fixture()
def app_client(clean_tables: str):
    """FastAPI app with test settings (overrides cleared after each test)."""
    import main
    from core.realtime import ConnectionManager

    main.app.dependency_overrides[get_settings] = _test_settings
    if getattr(main.app.state, "ws_manager", None) is None:
        main.app.state.ws_manager = ConnectionManager()
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
