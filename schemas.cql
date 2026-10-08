// =============================================================================
// AmigoACT — ScyllaDB schema (volunteer & extracurricular activity management)
// File: amigoact-be/schemas.cql
//
// Conventions (must match AGENTS.md):
// - All primary keys are CQL `uuid`, generated application-side as UUIDv7
//   (uuid_utils.uuid7()). The single exception is `qr_codes.code`, a short
//   human-scannable string that IS the lookup key.
// - No Secondary Indexes and no ALLOW FILTERING. Every access path has its own
//   query table (e.g. registrations_by_activity / registrations_by_student).
// - Time-ordered feeds use CLUSTERING ORDER BY ... DESC.
// - The Student <-> Activity N-M relationship is modeled explicitly through
//   `registrations` plus both directional query tables.
// - Raw CQL here is the migration/reference source. Runtime access goes through
//   `cassandra.cqlengine` Models in each feature's repository.py (AGENTS.md #5).
// - PERSISTENCE POLICY (no RAM state): ScyllaDB is the single source of truth.
//   Process restarts must lose nothing. Forbidden: in-memory session stores,
//   token caches, rate-limit buckets, request-dedup sets, locks, QR/slot
//   counters kept in app RAM. Read-through caches are allowed only with TTL
//   and DB fallback, never as authoritative state. Concurrent increments
//   (qr_codes.used_count, activity_slots.registered, rate-limit hits) use
//   lightweight transactions (IF / IF NOT EXISTS), never in-process locks.
//   Ephemeral coordination that is typically kept in RAM is persisted instead:
//   `idempotency_keys` (safe retries), `auth_rate_limits` (durable buckets),
//   `job_leases` (single-worker background jobs).
// - 76 tables total: 9 auth + 8 org + 9 rbac + 3 student + 9 activity
//   + 6 registration + 8 attendance + 4 hours + 4 certificate + 4 media
//   + 3 notification + 4 report + 2 review + 3 durability.
// =============================================================================

CREATE KEYSPACE IF NOT EXISTS amigoact
WITH replication = {'class': 'NetworkTopologyStrategy', 'datacenter1': 1};

USE amigoact;

// -----------------------------------------------------------------------------
// 1. AUTH & IDENTITY (6 tables)
// Hybrid auth: stateless JWT access + stateful opaque refresh (SHA-256 hashes).
// -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS users (
    id uuid PRIMARY KEY,
    email text,
    phone text,
    password_hash text,
    full_name text,
    account_type text, // individual | business
    tax_code text,
    company_name text,
    legal_rep_name text,
    legal_rep_id text,
    legal_rep_position text,
    email_verified_at timestamp,
    status text, // active | suspended | deleted
    created_at timestamp,
    updated_at timestamp
);

CREATE TABLE IF NOT EXISTS users_by_email (
    email text PRIMARY KEY,
    user_id uuid
);

CREATE TABLE IF NOT EXISTS users_by_phone (
    phone text PRIMARY KEY,
    user_id uuid
);

CREATE TABLE IF NOT EXISTS auth_refresh_tokens (
    token_hash text PRIMARY KEY,
    user_id uuid,
    family_id uuid,
    expires_at timestamp,
    revoked_at timestamp,
    rotated_from text,
    created_at timestamp
);

CREATE TABLE IF NOT EXISTS refresh_tokens_by_user (
    user_id uuid,
    token_hash text,
    family_id uuid,
    expires_at timestamp,
    revoked_at timestamp,
    PRIMARY KEY ((user_id), token_hash)
);

CREATE TABLE IF NOT EXISTS refresh_tokens_by_family (
    family_id uuid,
    token_hash text,
    user_id uuid,
    expires_at timestamp,
    revoked_at timestamp,
    PRIMARY KEY ((family_id), token_hash)
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    user_id uuid,
    session_id uuid,
    device_label text,
    ip text,
    created_at timestamp,
    last_seen_at timestamp,
    revoked_at timestamp,
    PRIMARY KEY ((user_id), session_id)
);

CREATE TABLE IF NOT EXISTS password_resets (
    token_hash text PRIMARY KEY,
    user_id uuid,
    expires_at timestamp,
    used_at timestamp
);

CREATE TABLE IF NOT EXISTS email_verifications (
    token_hash text PRIMARY KEY,
    user_id uuid,
    email text,
    expires_at timestamp,
    verified_at timestamp
);

// -----------------------------------------------------------------------------
// 2. ORGANIZATIONS & MULTI-TENANCY (8 tables)
// Enterprise scoping: organization -> campus -> department. Every business row
// carries org_id so data never leaks across tenants.
// -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS organizations (
    id uuid PRIMARY KEY,
    name text,
    slug text,
    description text,
    org_type text, // organization | club | group | business
    status text, // active | suspended
    owner_id uuid,
    tax_code text,
    legal_rep_name text,
    legal_rep_id text,
    legal_rep_position text,
    legal_status text, // none | pending | verified
    deleted_at timestamp, // null = alive; set = soft-deleted, restorable
    created_at timestamp,
    updated_at timestamp
);

CREATE TABLE IF NOT EXISTS organizations_by_slug (
    slug text PRIMARY KEY,
    org_id uuid
);

CREATE TABLE IF NOT EXISTS organization_members (
    org_id uuid,
    user_id uuid,
    status text, // active | invited | suspended | left
    joined_at timestamp,
    PRIMARY KEY ((org_id), user_id)
);

CREATE TABLE IF NOT EXISTS members_by_user (
    user_id uuid,
    org_id uuid,
    status text,
    joined_at timestamp,
    PRIMARY KEY ((user_id), org_id)
);

CREATE TABLE IF NOT EXISTS campuses (
    id uuid PRIMARY KEY,
    org_id uuid,
    name text,
    address text,
    status text,
    created_at timestamp
);

CREATE TABLE IF NOT EXISTS campuses_by_org (
    org_id uuid,
    campus_id uuid,
    name text,
    PRIMARY KEY ((org_id), campus_id)
);

CREATE TABLE IF NOT EXISTS departments (
    id uuid PRIMARY KEY,
    org_id uuid,
    campus_id uuid,
    name text,
    code text,
    status text,
    created_at timestamp
);

CREATE TABLE IF NOT EXISTS departments_by_campus (
    campus_id uuid,
    department_id uuid,
    name text,
    code text,
    PRIMARY KEY ((campus_id), department_id)
);

// -----------------------------------------------------------------------------
// 3. RBAC — ENTERPRISE AUTHORIZATION (9 tables)
// Layered model: system/org roles -> permissions, plus direct per-user grants
// with expiry, API keys for integrations, and a full access audit trail.
// Checks always combine role permissions AND direct grants AND ownership.
// -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS roles (
    id uuid PRIMARY KEY,
    org_id uuid, // null = system-wide role
    name text,
    description text,
    is_system boolean,
    created_at timestamp
);

CREATE TABLE IF NOT EXISTS roles_by_org (
    org_id uuid,
    role_id uuid,
    name text,
    PRIMARY KEY ((org_id), role_id)
);

CREATE TABLE IF NOT EXISTS permissions (
    code text PRIMARY KEY, // e.g. 'activity:create'
    module text, // auth | org | activity | attendance | certificate | report
    description text
);

CREATE TABLE IF NOT EXISTS role_permissions (
    role_id uuid,
    permission_code text,
    PRIMARY KEY ((role_id), permission_code)
);

CREATE TABLE IF NOT EXISTS user_roles (
    org_id uuid,
    user_id uuid,
    role_id uuid,
    granted_by uuid,
    granted_at timestamp,
    expires_at timestamp,
    PRIMARY KEY ((org_id), user_id, role_id)
);

CREATE TABLE IF NOT EXISTS roles_by_user (
    user_id uuid,
    org_id uuid,
    role_id uuid,
    granted_at timestamp,
    expires_at timestamp,
    PRIMARY KEY ((user_id), org_id, role_id)
);

CREATE TABLE IF NOT EXISTS user_permission_grants (
    org_id uuid,
    user_id uuid,
    permission_code text,
    reason text,
    granted_by uuid,
    granted_at timestamp,
    expires_at timestamp,
    PRIMARY KEY ((org_id), user_id, permission_code)
);

CREATE TABLE IF NOT EXISTS api_keys (
    key_hash text PRIMARY KEY,
    key_id uuid,
    org_id uuid,
    name text,
    scopes set<text>,
    expires_at timestamp,
    revoked_at timestamp,
    last_used_at timestamp
);

CREATE TABLE IF NOT EXISTS access_audit_logs (
    org_id uuid,
    occurred_at timestamp,
    log_id uuid,
    actor_id uuid,
    action text,
    resource_type text,
    resource_id uuid,
    result text, // allowed | denied
    ip text,
    metadata text,
    PRIMARY KEY ((org_id), occurred_at, log_id)
) WITH CLUSTERING ORDER BY (occurred_at DESC, log_id ASC);

// -----------------------------------------------------------------------------
// 4. STUDENT PROFILES (3 tables)
// -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS student_profiles (
    user_id uuid PRIMARY KEY,
    student_code text,
    campus_id uuid,
    department_id uuid,
    class_name text,
    enrollment_year int,
    status text, // studying | graduated | suspended
    total_hours double,
    updated_at timestamp
);

CREATE TABLE IF NOT EXISTS student_profiles_by_code (
    campus_id uuid,
    student_code text,
    user_id uuid,
    PRIMARY KEY ((campus_id), student_code)
);

CREATE TABLE IF NOT EXISTS emergency_contacts (
    user_id uuid,
    contact_id uuid,
    name text,
    relation text,
    phone text,
    is_primary boolean,
    PRIMARY KEY ((user_id), contact_id)
);

// -----------------------------------------------------------------------------
// 5. ACTIVITIES / EVENTS (9 tables)
// -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS activities (
    id uuid PRIMARY KEY,
    org_id uuid,
    campus_id uuid,
    title text,
    description text,
    category_id uuid,
    status text, // draft | published | ongoing | completed | cancelled
    location text,
    max_participants int,
    start_at timestamp,
    end_at timestamp,
    hours_awarded double,
    requirements_json text,
    cover_media_id uuid,
    created_by uuid,
    created_at timestamp,
    updated_at timestamp
);

CREATE TABLE IF NOT EXISTS activities_by_org (
    org_id uuid,
    start_at timestamp,
    activity_id uuid,
    title text,
    status text,
    campus_id uuid,
    PRIMARY KEY ((org_id), start_at, activity_id)
) WITH CLUSTERING ORDER BY (start_at DESC, activity_id ASC);

CREATE TABLE IF NOT EXISTS activities_by_status (
    status text,
    start_at timestamp,
    activity_id uuid,
    org_id uuid,
    title text,
    PRIMARY KEY ((status), start_at, activity_id)
) WITH CLUSTERING ORDER BY (start_at DESC, activity_id ASC);

CREATE TABLE IF NOT EXISTS activities_by_category (
    category_id uuid,
    start_at timestamp,
    activity_id uuid,
    org_id uuid,
    title text,
    PRIMARY KEY ((category_id), start_at, activity_id)
) WITH CLUSTERING ORDER BY (start_at DESC, activity_id ASC);

CREATE TABLE IF NOT EXISTS activity_categories (
    id uuid PRIMARY KEY,
    org_id uuid, // null = global category
    name text,
    description text,
    default_hours double,
    color text
);

CREATE TABLE IF NOT EXISTS activity_schedules (
    id uuid PRIMARY KEY,
    activity_id uuid,
    title text,
    location text,
    start_at timestamp,
    end_at timestamp,
    status text, // scheduled | open | closed | cancelled
    created_at timestamp
);

CREATE TABLE IF NOT EXISTS activity_slots (
    schedule_id uuid,
    slot_id uuid,
    title text,
    capacity int,
    registered int,
    start_at timestamp,
    end_at timestamp,
    PRIMARY KEY ((schedule_id), slot_id)
);

CREATE TABLE IF NOT EXISTS activity_staff (
    activity_id uuid,
    user_id uuid,
    staff_role text, // organizer | supervisor | supporter
    assigned_by uuid,
    assigned_at timestamp,
    PRIMARY KEY ((activity_id), user_id)
);

CREATE TABLE IF NOT EXISTS activity_announcements (
    activity_id uuid,
    published_at timestamp,
    announcement_id uuid,
    title text,
    body text,
    created_by uuid,
    PRIMARY KEY ((activity_id), published_at, announcement_id)
) WITH CLUSTERING ORDER BY (published_at DESC, announcement_id ASC);

// -----------------------------------------------------------------------------
// 6. REGISTRATIONS — STUDENT <-> ACTIVITY N-M (6 tables)
// The N-M join is explicit: `registrations` + both directional query tables.
// -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS registrations (
    registration_id uuid PRIMARY KEY,
    activity_id uuid,
    student_id uuid,
    slot_id uuid,
    status text, // pending | approved | rejected | waitlisted | cancelled | attended
    form_data text, // JSON answers to registration_forms questions
    registered_at timestamp,
    decided_by uuid,
    decided_at timestamp
);

CREATE TABLE IF NOT EXISTS registrations_by_activity (
    activity_id uuid,
    registered_at timestamp,
    registration_id uuid,
    student_id uuid,
    slot_id uuid,
    status text,
    PRIMARY KEY ((activity_id), registered_at, registration_id)
) WITH CLUSTERING ORDER BY (registered_at ASC, registration_id ASC);

CREATE TABLE IF NOT EXISTS registrations_by_student (
    student_id uuid,
    registered_at timestamp,
    registration_id uuid,
    activity_id uuid,
    status text,
    PRIMARY KEY ((student_id), registered_at, registration_id)
) WITH CLUSTERING ORDER BY (registered_at DESC, registration_id ASC);

CREATE TABLE IF NOT EXISTS registration_status_history (
    registration_id uuid,
    changed_at timestamp,
    history_id uuid,
    from_status text,
    to_status text,
    changed_by uuid,
    note text,
    PRIMARY KEY ((registration_id), changed_at, history_id)
) WITH CLUSTERING ORDER BY (changed_at DESC, history_id ASC);

CREATE TABLE IF NOT EXISTS registration_forms (
    activity_id uuid,
    position int,
    question_id uuid,
    label text,
    field_type text, // text | choice | file | consent
    required boolean,
    PRIMARY KEY ((activity_id), position, question_id)
);

CREATE TABLE IF NOT EXISTS waitlist_entries (
    activity_id uuid,
    joined_at timestamp,
    waitlist_id uuid,
    student_id uuid,
    slot_id uuid,
    status text, // waiting | promoted | expired
    promoted_at timestamp,
    PRIMARY KEY ((activity_id), joined_at, waitlist_id)
) WITH CLUSTERING ORDER BY (joined_at ASC, waitlist_id ASC);

// -----------------------------------------------------------------------------
// 7. QR CHECK-IN & ATTENDANCE (8 tables)
// QR flow is simulated: qr_codes are issued per session, scans are validated
// against expiry/max_uses, every scan is logged, disputes go to appeals.
// -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS attendance_sessions (
    schedule_id uuid,
    session_id uuid,
    title text,
    qr_code text,
    opens_at timestamp,
    closes_at timestamp,
    status text, // scheduled | open | closed
    created_by uuid,
    PRIMARY KEY ((schedule_id), session_id)
);

CREATE TABLE IF NOT EXISTS qr_codes (
    code text PRIMARY KEY,
    session_id uuid,
    schedule_id uuid,
    activity_id uuid,
    expires_at timestamp,
    max_uses int,
    used_count int,
    status text // active | expired | disabled
);

CREATE TABLE IF NOT EXISTS qr_scan_logs (
    qr_code text,
    scanned_at timestamp,
    log_id uuid,
    student_id uuid,
    result text, // accepted | duplicate | expired | invalid
    device_info text,
    PRIMARY KEY ((qr_code), scanned_at, log_id)
) WITH CLUSTERING ORDER BY (scanned_at DESC, log_id ASC);

CREATE TABLE IF NOT EXISTS attendance_records (
    record_id uuid PRIMARY KEY,
    session_id uuid,
    schedule_id uuid,
    activity_id uuid,
    student_id uuid,
    method text, // qr | manual
    scanned_at timestamp,
    verified_by uuid
);

CREATE TABLE IF NOT EXISTS attendance_by_activity (
    activity_id uuid,
    scanned_at timestamp,
    record_id uuid,
    student_id uuid,
    session_id uuid,
    method text,
    PRIMARY KEY ((activity_id), scanned_at, record_id)
) WITH CLUSTERING ORDER BY (scanned_at DESC, record_id ASC);

CREATE TABLE IF NOT EXISTS attendance_by_student (
    student_id uuid,
    scanned_at timestamp,
    record_id uuid,
    activity_id uuid,
    session_id uuid,
    method text,
    PRIMARY KEY ((student_id), scanned_at, record_id)
) WITH CLUSTERING ORDER BY (scanned_at DESC, record_id ASC);

CREATE TABLE IF NOT EXISTS attendance_appeals (
    activity_id uuid,
    student_id uuid,
    appeal_id uuid,
    record_id uuid,
    reason text,
    status text, // pending | approved | rejected
    resolved_by uuid,
    resolved_at timestamp,
    created_at timestamp,
    PRIMARY KEY ((activity_id), student_id, appeal_id)
);

CREATE TABLE IF NOT EXISTS attendance_summaries (
    registration_id uuid PRIMARY KEY,
    activity_id uuid,
    student_id uuid,
    sessions_total int,
    sessions_attended int,
    minutes_attended int,
    status text, // incomplete | complete
    updated_at timestamp
);

// -----------------------------------------------------------------------------
// 8. VOLUNTEER HOURS (4 tables)
// Hours are append-only ledger entries; summaries are maintained per term.
// -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS volunteer_hour_ledger (
    entry_id uuid PRIMARY KEY,
    student_id uuid,
    activity_id uuid,
    source text, // attendance | adjustment
    hours double,
    term text, // e.g. '2026-H1'
    recorded_at timestamp,
    recorded_by uuid,
    note text
);

CREATE TABLE IF NOT EXISTS hours_by_student (
    student_id uuid,
    term text,
    total_hours double,
    activities_count int,
    updated_at timestamp,
    PRIMARY KEY ((student_id), term)
);

CREATE TABLE IF NOT EXISTS hour_adjustments (
    adjustment_id uuid PRIMARY KEY,
    student_id uuid,
    activity_id uuid,
    delta_hours double,
    reason text,
    created_by uuid,
    created_at timestamp
);

CREATE TABLE IF NOT EXISTS hour_rules (
    rule_id uuid PRIMARY KEY,
    org_id uuid,
    category_id uuid,
    multiplier double,
    cap_hours double,
    term text,
    is_active boolean
);

// -----------------------------------------------------------------------------
// 9. CERTIFICATES (4 tables)
// One certificate per (activity, student). PDFs are stored as media_assets.
// -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS certificate_templates (
    template_id uuid PRIMARY KEY,
    org_id uuid,
    name text,
    background_media_id uuid,
    layout_json text,
    is_active boolean,
    created_at timestamp
);

CREATE TABLE IF NOT EXISTS certificates (
    activity_id uuid,
    student_id uuid,
    certificate_id uuid,
    template_id uuid,
    serial_no text,
    issued_at timestamp,
    issued_by uuid,
    file_media_id uuid,
    status text, // issued | revoked
    PRIMARY KEY ((activity_id), student_id)
);

CREATE TABLE IF NOT EXISTS certificates_by_student (
    student_id uuid,
    issued_at timestamp,
    certificate_id uuid,
    activity_id uuid,
    serial_no text,
    status text,
    PRIMARY KEY ((student_id), issued_at, certificate_id)
) WITH CLUSTERING ORDER BY (issued_at DESC, certificate_id ASC);

CREATE TABLE IF NOT EXISTS certificate_revocations (
    revocation_id uuid PRIMARY KEY,
    certificate_id uuid,
    activity_id uuid,
    student_id uuid,
    reason text,
    revoked_by uuid,
    revoked_at timestamp
);

// -----------------------------------------------------------------------------
// 10. MEDIA & IMAGES (4 tables)
// Binary files live in object storage; ScyllaDB stores metadata + references.
// Moderation is an append-only review history; latest row = current status.
// -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS media_assets (
    asset_id uuid PRIMARY KEY,
    owner_id uuid,
    owner_type text, // user | activity | certificate | announcement
    file_url text,
    file_hash text,
    mime text,
    width int,
    height int,
    size_bytes bigint,
    created_at timestamp
);

CREATE TABLE IF NOT EXISTS media_by_owner (
    owner_id uuid,
    created_at timestamp,
    asset_id uuid,
    file_url text,
    mime text,
    owner_type text,
    PRIMARY KEY ((owner_id), created_at, asset_id)
) WITH CLUSTERING ORDER BY (created_at DESC, asset_id ASC);

CREATE TABLE IF NOT EXISTS activity_media (
    activity_id uuid,
    position int,
    asset_id uuid,
    role text, // cover | gallery | document
    caption text,
    PRIMARY KEY ((activity_id), position, asset_id)
);

CREATE TABLE IF NOT EXISTS media_moderation (
    status text,
    created_at timestamp,
    moderation_id uuid,
    asset_id uuid,
    reviewed_by uuid,
    note text,
    PRIMARY KEY ((status), created_at, moderation_id)
) WITH CLUSTERING ORDER BY (created_at DESC, moderation_id ASC);

// -----------------------------------------------------------------------------
// 11. NOTIFICATIONS (3 tables)
// -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS notifications (
    notification_id uuid PRIMARY KEY,
    user_id uuid,
    type text, // registration | attendance | certificate | announcement
    title text,
    body text,
    data_json text,
    channel text, // inapp | email
    status text, // unread | read
    created_at timestamp
);

CREATE TABLE IF NOT EXISTS notifications_by_user (
    user_id uuid,
    created_at timestamp,
    notification_id uuid,
    title text,
    status text,
    PRIMARY KEY ((user_id), created_at, notification_id)
) WITH CLUSTERING ORDER BY (created_at DESC, notification_id ASC);

CREATE TABLE IF NOT EXISTS notification_preferences (
    user_id uuid PRIMARY KEY,
    channels map<text, boolean>,
    muted_types set<text>,
    updated_at timestamp
);

// -----------------------------------------------------------------------------
// 12. REPORTS, STATISTICS & EXPORTS (4 tables)
// Pre-aggregated stats keep dashboards fast; exports run as async jobs.
// -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS report_snapshots (
    org_id uuid,
    created_at timestamp,
    snapshot_id uuid,
    report_type text, // activity_summary | hours_leaderboard | participation
    period_start timestamp,
    period_end timestamp,
    payload_json text,
    created_by uuid,
    PRIMARY KEY ((org_id), created_at, snapshot_id)
) WITH CLUSTERING ORDER BY (created_at DESC, snapshot_id ASC);

CREATE TABLE IF NOT EXISTS activity_daily_stats (
    activity_id uuid,
    day date,
    registrations int,
    attendees int,
    hours_awarded double,
    PRIMARY KEY ((activity_id), day)
) WITH CLUSTERING ORDER BY (day DESC);

CREATE TABLE IF NOT EXISTS org_monthly_stats (
    org_id uuid,
    month text, // e.g. '2026-10'
    activities int,
    participants int,
    hours double,
    certificates int,
    PRIMARY KEY ((org_id), month)
) WITH CLUSTERING ORDER BY (month DESC);

CREATE TABLE IF NOT EXISTS export_jobs (
    requested_by uuid,
    created_at timestamp,
    job_id uuid,
    org_id uuid,
    job_type text, // certificates_pdf | roster_csv | stats_xlsx
    status text, // queued | running | done | failed
    file_url text,
    error text,
    finished_at timestamp,
    PRIMARY KEY ((requested_by), created_at, job_id)
) WITH CLUSTERING ORDER BY (created_at DESC, job_id ASC);

// -----------------------------------------------------------------------------
// 13. REVIEWS & FEEDBACK (2 tables)
// -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS reviews_by_activity (
    activity_id uuid,
    created_at timestamp,
    review_id uuid,
    student_id uuid,
    rating int,
    comment text,
    PRIMARY KEY ((activity_id), created_at, review_id)
) WITH CLUSTERING ORDER BY (created_at DESC, review_id ASC);

CREATE TABLE IF NOT EXISTS reviews_by_student (
    student_id uuid,
    created_at timestamp,
    review_id uuid,
    activity_id uuid,
    rating int,
    PRIMARY KEY ((student_id), created_at, review_id)
) WITH CLUSTERING ORDER BY (created_at DESC, review_id ASC);

// -----------------------------------------------------------------------------
// 14. DURABILITY — REPLACES TYPICAL RAM STATE (3 tables)
// Nothing authoritative lives in process memory. Retries deduplicate by key,
// rate limits accumulate in counter buckets, background jobs take DB leases.
// -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS idempotency_keys (
    key text PRIMARY KEY, // client-supplied idempotency key (hash)
    user_id uuid,
    status text, // in_progress | completed | failed
    response_json text, // stored response for safe replay
    created_at timestamp,
    expires_at timestamp
);

CREATE TABLE IF NOT EXISTS auth_rate_limits (
    bucket text, // e.g. 'login:192.0.2.10' or 'refresh:<user_id>'
    window_start timestamp, // fixed window start (e.g. per minute)
    hits counter,
    PRIMARY KEY ((bucket), window_start)
);

CREATE TABLE IF NOT EXISTS job_leases (
    job_id uuid PRIMARY KEY,
    owner text, // worker identity holding the lease
    status text, // free | held | done
    acquired_at timestamp,
    expires_at timestamp // acquire with LWT: IF status = 'free' OR expired
);
